//! Modbus Protocol Engine & Native High-Precision Background Poller / Slave Emulator.
//! Supports both Modbus RTU (Binary + CRC16) and Modbus ASCII (Colon ':' header, CRLF ending, LRC checksum).

use super::checksum::{append_modbus_crc, lrc_modbus_ascii, validate_modbus_crc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use tauri::AppHandle;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "lowercase")]
pub enum ModbusMode {
    Rtu,
    Ascii,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModbusParsedRegister {
    pub address: u16,
    pub raw_hex: String,
    pub u16_val: u16,
    pub i16_val: i16,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModbusResponsePayload {
    pub port: String,
    pub mode: ModbusMode,
    pub slave_id: u8,
    pub func_code: u8,
    pub is_exception: bool,
    pub exception_code: Option<u8>,
    pub exception_desc: Option<String>,
    pub registers: Vec<ModbusParsedRegister>,
    pub raw_hex: String,
    pub raw_ascii: Option<String>,
    pub timestamp_ms: u64,
}

/// Builds a raw binary Modbus PDU/ADU payload without final RTU/ASCII framing.
pub fn build_modbus_pdu(
    slave_id: u8,
    func_code: u8,
    start_addr: u16,
    count_or_val: u16,
    extra_values: Option<&[u16]>,
) -> Vec<u8> {
    let mut frame = Vec::with_capacity(16);
    frame.push(slave_id);
    frame.push(func_code);

    match func_code {
        // Read Coils (01), Read Discrete Inputs (02), Read Holding Regs (03), Read Input Regs (04)
        0x01 | 0x02 | 0x03 | 0x04 => {
            frame.push(((start_addr >> 8) & 0xFF) as u8);
            frame.push((start_addr & 0xFF) as u8);
            frame.push(((count_or_val >> 8) & 0xFF) as u8);
            frame.push((count_or_val & 0xFF) as u8);
        }
        // Write Single Coil (05) - 0xFF00 = ON, 0x0000 = OFF
        0x05 => {
            frame.push(((start_addr >> 8) & 0xFF) as u8);
            frame.push((start_addr & 0xFF) as u8);
            let val = if count_or_val != 0 { 0xFF00u16 } else { 0x0000u16 };
            frame.push(((val >> 8) & 0xFF) as u8);
            frame.push((val & 0xFF) as u8);
        }
        // Write Single Register (06)
        0x06 => {
            frame.push(((start_addr >> 8) & 0xFF) as u8);
            frame.push((start_addr & 0xFF) as u8);
            frame.push(((count_or_val >> 8) & 0xFF) as u8);
            frame.push((count_or_val & 0xFF) as u8);
        }
        // Write Multiple Registers (16 / 0x10)
        0x10 => {
            let values = extra_values.unwrap_or(&[]);
            let reg_count = values.len() as u16;
            frame.push(((start_addr >> 8) & 0xFF) as u8);
            frame.push((start_addr & 0xFF) as u8);
            frame.push(((reg_count >> 8) & 0xFF) as u8);
            frame.push((reg_count & 0xFF) as u8);
            frame.push((reg_count * 2) as u8); // Byte count
            for &v in values {
                frame.push(((v >> 8) & 0xFF) as u8);
                frame.push((v & 0xFF) as u8);
            }
        }
        _ => {
            frame.push(((start_addr >> 8) & 0xFF) as u8);
            frame.push((start_addr & 0xFF) as u8);
            frame.push(((count_or_val >> 8) & 0xFF) as u8);
            frame.push((count_or_val & 0xFF) as u8);
        }
    }
    frame
}

/// Builds a Modbus RTU request frame with automatic CRC16 appended.
pub fn build_modbus_request(
    slave_id: u8,
    func_code: u8,
    start_addr: u16,
    count_or_val: u16,
    extra_values: Option<&[u16]>,
) -> Vec<u8> {
    let mut frame = build_modbus_pdu(slave_id, func_code, start_addr, count_or_val, extra_values);
    append_modbus_crc(&mut frame);
    frame
}

/// Converts binary bytes to Modbus ASCII format (':', hex chars, LRC, "\r\n").
pub fn encode_modbus_ascii(data: &[u8]) -> Vec<u8> {
    let lrc = lrc_modbus_ascii(data);
    let mut ascii_str = String::with_capacity(data.len() * 2 + 5);
    ascii_str.push(':');
    for &b in data {
        ascii_str.push_str(&format!("{:02X}", b));
    }
    ascii_str.push_str(&format!("{:02X}\r\n", lrc));
    ascii_str.into_bytes()
}

/// Decodes Modbus ASCII string/bytes into binary bytes and validates LRC.
pub fn decode_modbus_ascii(ascii_bytes: &[u8]) -> Result<Vec<u8>, String> {
    let s = std::str::from_utf8(ascii_bytes)
        .map_err(|e| format!("Invalid UTF-8 in Modbus ASCII: {}", e))?
        .trim();

    if !s.starts_with(':') {
        return Err("Modbus ASCII 必须以冒号 ':' 起始".to_string());
    }

    let hex_part = &s[1..];
    if hex_part.len() < 4 || hex_part.len() % 2 != 0 {
        return Err("Modbus ASCII 长度非法".to_string());
    }

    let mut binary_data = Vec::with_capacity(hex_part.len() / 2);
    for i in (0..hex_part.len()).step_by(2) {
        let byte = u8::from_str_radix(&hex_part[i..i + 2], 16)
            .map_err(|e| format!("Invalid hex byte in ASCII frame: {}", e))?;
        binary_data.push(byte);
    }

    // Last byte is LRC
    let data_len = binary_data.len() - 1;
    let expected_lrc = lrc_modbus_ascii(&binary_data[..data_len]);
    let actual_lrc = binary_data[data_len];

    if expected_lrc != actual_lrc {
        return Err(format!(
            "Modbus ASCII LRC 校验失败: 期望 0x{:02X}, 实际 0x{:02X}",
            expected_lrc, actual_lrc
        ));
    }

    Ok(binary_data[..data_len].to_vec())
}

/// Builds a Modbus ASCII request frame.
pub fn build_modbus_ascii_request(
    slave_id: u8,
    func_code: u8,
    start_addr: u16,
    count_or_val: u16,
    extra_values: Option<&[u16]>,
) -> Vec<u8> {
    let pdu = build_modbus_pdu(slave_id, func_code, start_addr, count_or_val, extra_values);
    encode_modbus_ascii(&pdu)
}

/// Parses a Modbus response frame (automatically detecting RTU or ASCII).
pub fn parse_modbus_response(
    port: &str,
    start_addr: u16,
    frame: &[u8],
) -> Result<ModbusResponsePayload, String> {
    if frame.is_empty() {
        return Err("Modbus 帧长度为空".to_string());
    }

    let (mode, raw_pdu, raw_ascii) = if frame[0] == b':' {
        // ASCII frame
        let ascii_str = String::from_utf8_lossy(frame).to_string();
        let pdu = decode_modbus_ascii(frame)?;
        (ModbusMode::Ascii, pdu, Some(ascii_str))
    } else {
        // RTU frame
        if frame.len() < 3 {
            return Err("Modbus 帧长度不足 3 字节".to_string());
        }
        if !validate_modbus_crc(frame) {
            return Err("Modbus CRC16 校验失败".to_string());
        }
        let data_len = frame.len() - 2;
        (ModbusMode::Rtu, frame[..data_len].to_vec(), None)
    };

    if raw_pdu.len() < 2 {
        return Err("Modbus PDU 数据不足".to_string());
    }

    let slave_id = raw_pdu[0];
    let func = raw_pdu[1];
    let raw_hex = raw_pdu.iter().map(|b| format!("{:02X}", b)).collect::<Vec<_>>().join(" ");
    let now_ms = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64;

    // Check if exception response (func & 0x80)
    if (func & 0x80) != 0 {
        let err_code = if raw_pdu.len() >= 3 { raw_pdu[2] } else { 0 };
        let desc = match err_code {
            0x01 => "01: 非法功能码 (ILLEGAL FUNCTION)",
            0x02 => "02: 非法数据地址 (ILLEGAL DATA ADDRESS)",
            0x03 => "03: 非法数据值 (ILLEGAL DATA VALUE)",
            0x04 => "04: 从机设备故障 (SLAVE DEVICE FAILURE)",
            0x05 => "05: 确认应答 (ACKNOWLEDGE)",
            0x06 => "06: 从机设备忙 (SLAVE DEVICE BUSY)",
            0x08 => "08: 存储奇偶性差错 (MEMORY PARITY ERROR)",
            0x0A => "0A: 网关路径不可用 (GATEWAY PATH UNAVAILABLE)",
            0x0B => "0B: 网关目标设备未响应 (GATEWAY TARGET DEVICE FAILED TO RESPOND)",
            _ => "未知 Modbus 异常码",
        };
        return Ok(ModbusResponsePayload {
            port: port.to_string(),
            mode,
            slave_id,
            func_code: func & 0x7F,
            is_exception: true,
            exception_code: Some(err_code),
            exception_desc: Some(desc.to_string()),
            registers: Vec::new(),
            raw_hex,
            raw_ascii,
            timestamp_ms: now_ms,
        });
    }

    let mut registers = Vec::new();
    // Functions 03 & 04 return: [Slave, Func, ByteCount, High0, Low0, High1, Low1, ...]
    if (func == 0x03 || func == 0x04) && raw_pdu.len() >= 3 {
        let byte_count = raw_pdu[2] as usize;
        let data_bytes = &raw_pdu[3..3 + byte_count.min(raw_pdu.len() - 3)];
        let num_regs = data_bytes.len() / 2;

        for i in 0..num_regs {
            let h = data_bytes[i * 2] as u16;
            let l = data_bytes[i * 2 + 1] as u16;
            let u16_val = (h << 8) | l;
            let i16_val = u16_val as i16;
            let addr = start_addr + i as u16;
            registers.push(ModbusParsedRegister {
                address: addr,
                raw_hex: format!("{:02X} {:02X}", h, l),
                u16_val,
                i16_val,
            });
        }
    }

    Ok(ModbusResponsePayload {
        port: port.to_string(),
        mode,
        slave_id,
        func_code: func,
        is_exception: false,
        exception_code: None,
        exception_desc: None,
        registers,
        raw_hex,
        raw_ascii,
        timestamp_ms: now_ms,
    })
}

/// Simulated Modbus Slave Storage Area in Rust Memory
pub struct ModbusSlaveStorage {
    pub slave_id: u8,
    pub holding_registers: Arc<Mutex<HashMap<u16, u16>>>,
    pub input_registers: Arc<Mutex<HashMap<u16, u16>>>,
    pub coils: Arc<Mutex<HashMap<u16, bool>>>,
    pub discrete_inputs: Arc<Mutex<HashMap<u16, bool>>>,
}

impl ModbusSlaveStorage {
    pub fn new(slave_id: u8) -> Self {
        Self {
            slave_id,
            holding_registers: Arc::new(Mutex::new(HashMap::new())),
            input_registers: Arc::new(Mutex::new(HashMap::new())),
            coils: Arc::new(Mutex::new(HashMap::new())),
            discrete_inputs: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Process an incoming Modbus Master request and generate response ADU
    pub fn handle_request(&self, request_pdu: &[u8], is_ascii: bool) -> Option<Vec<u8>> {
        if request_pdu.len() < 2 {
            return None;
        }
        let dev_id = request_pdu[0];
        if dev_id != self.slave_id && dev_id != 0 {
            // Not for this slave (and not broadcast)
            return None;
        }

        let func = request_pdu[1];
        let mut response_pdu = Vec::new();
        response_pdu.push(self.slave_id);

        match func {
            // Read Holding Registers (0x03) or Read Input Registers (0x04)
            0x03 | 0x04 => {
                if request_pdu.len() < 6 {
                    return None;
                }
                let start_addr = ((request_pdu[2] as u16) << 8) | (request_pdu[3] as u16);
                let count = ((request_pdu[4] as u16) << 8) | (request_pdu[5] as u16);
                let byte_count = (count * 2) as u8;

                response_pdu.push(func);
                response_pdu.push(byte_count);

                let map_guard = if func == 0x03 {
                    self.holding_registers.lock().unwrap()
                } else {
                    self.input_registers.lock().unwrap()
                };

                for i in 0..count {
                    let addr = start_addr + i;
                    let val = map_guard.get(&addr).copied().unwrap_or(0);
                    response_pdu.push(((val >> 8) & 0xFF) as u8);
                    response_pdu.push((val & 0xFF) as u8);
                }
            }
            // Write Single Register (0x06)
            0x06 => {
                if request_pdu.len() < 6 {
                    return None;
                }
                let addr = ((request_pdu[2] as u16) << 8) | (request_pdu[3] as u16);
                let val = ((request_pdu[4] as u16) << 8) | (request_pdu[5] as u16);

                let mut map_guard = self.holding_registers.lock().unwrap();
                map_guard.insert(addr, val);

                // Echo back the request PDU
                response_pdu = request_pdu[..6].to_vec();
            }
            _ => {
                // Illegal function
                response_pdu.push(func | 0x80);
                response_pdu.push(0x01); // Exception code 01: Illegal Function
            }
        }

        if is_ascii {
            Some(encode_modbus_ascii(&response_pdu))
        } else {
            let mut rtu = response_pdu;
            append_modbus_crc(&mut rtu);
            Some(rtu)
        }
    }
}

/// OS-level high precision native background poller for Modbus.
pub struct ModbusPoller {
    active_pollers: Mutex<HashMap<String, Arc<AtomicBool>>>,
}

impl ModbusPoller {
    pub fn new() -> Self {
        Self {
            active_pollers: Mutex::new(HashMap::new()),
        }
    }

    pub fn start_polling(
        &self,
        _app: AppHandle,
        port_name: String,
        mode: ModbusMode,
        slave_id: u8,
        start_addr: u16,
        count: u16,
        interval_ms: u64,
        serial_manager: Arc<super::serial_manager::SerialManager>,
    ) -> Result<(), String> {
        self.stop_polling(&port_name);

        let running = Arc::new(AtomicBool::new(true));
        {
            let mut map = self.active_pollers.lock().unwrap();
            map.insert(port_name.clone(), Arc::clone(&running));
        }

        let port_cloned = port_name.clone();
        let frame = if mode == ModbusMode::Ascii {
            build_modbus_ascii_request(slave_id, 0x03, start_addr, count, None)
        } else {
            build_modbus_request(slave_id, 0x03, start_addr, count, None)
        };

        thread::spawn(move || {
            let sleep_dur = Duration::from_millis(interval_ms.max(50));
            while running.load(Ordering::Relaxed) {
                if let Err(e) = serial_manager.write_data(&frame, Some(&port_cloned)) {
                    eprintln!("[ModbusPoller] Send error on {}: {}", port_cloned, e);
                }
                thread::sleep(sleep_dur);
            }
        });

        Ok(())
    }

    pub fn stop_polling(&self, port_name: &str) {
        let mut map = self.active_pollers.lock().unwrap();
        if let Some(flag) = map.remove(port_name) {
            flag.store(false, Ordering::Relaxed);
        }
    }

    pub fn is_polling(&self, port_name: &str) -> bool {
        let map = self.active_pollers.lock().unwrap();
        map.get(port_name)
            .map(|f| f.load(Ordering::Relaxed))
            .unwrap_or(false)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_modbus_rtu_build_and_parse() {
        let req = build_modbus_request(1, 0x03, 0x0000, 2, None);
        assert_eq!(req, vec![0x01, 0x03, 0x00, 0x00, 0x00, 0x02, 0xC4, 0x0B]);

        // Simulated RTU response: Slave 1, Func 03, ByteCount 4, Reg0 = 0x0012, Reg1 = 0x0034
        let mut resp = vec![0x01, 0x03, 0x04, 0x00, 0x12, 0x00, 0x34];
        append_modbus_crc(&mut resp);

        let parsed = parse_modbus_response("COM1", 0, &resp).unwrap();
        assert_eq!(parsed.slave_id, 1);
        assert_eq!(parsed.registers.len(), 2);
        assert_eq!(parsed.registers[0].u16_val, 0x0012);
        assert_eq!(parsed.registers[1].u16_val, 0x0034);
    }

    #[test]
    fn test_modbus_ascii_encode_decode() {
        // Request: 01 03 00 00 00 02 (LRC is FA) -> ":010300000002FA\r\n"
        let req_ascii = build_modbus_ascii_request(1, 0x03, 0x0000, 2, None);
        let req_str = String::from_utf8(req_ascii.clone()).unwrap();
        assert_eq!(req_str, ":010300000002FA\r\n");

        let decoded = decode_modbus_ascii(&req_ascii).unwrap();
        assert_eq!(decoded, vec![0x01, 0x03, 0x00, 0x00, 0x00, 0x02]);
    }

    #[test]
    fn test_modbus_slave_simulation() {
        let slave = ModbusSlaveStorage::new(1);
        {
            let mut regs = slave.holding_registers.lock().unwrap();
            regs.insert(0x0000, 1234);
            regs.insert(0x0001, 5678);
        }

        // Master reads 2 registers starting at 0
        let req_pdu = vec![0x01, 0x03, 0x00, 0x00, 0x00, 0x02];
        let resp_rtu = slave.handle_request(&req_pdu, false).unwrap();
        assert!(validate_modbus_crc(&resp_rtu));

        let parsed = parse_modbus_response("VIRTUAL", 0, &resp_rtu).unwrap();
        assert_eq!(parsed.registers.len(), 2);
        assert_eq!(parsed.registers[0].u16_val, 1234);
        assert_eq!(parsed.registers[1].u16_val, 5678);
    }
}
