use serde::{Deserialize, Serialize};
use serialport::{SerialPort, SerialPortType, UsbPortInfo};
use std::io::{Read, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PortInfo {
    pub port_name: String,
    pub description: String,
    pub vid: Option<u16>,
    pub pid: Option<u16>,
    pub manufacturer: Option<String>,
    pub product: Option<String>,
    pub serial_number: Option<String>,
    pub is_daplink: bool,
    pub device_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerialRxPayload {
    pub port: String,
    pub data: Vec<u8>,
    pub timestamp_ms: u64,
}

pub struct SerialManager {
    port: Arc<Mutex<Option<Box<dyn SerialPort>>>>,
    active_port_name: Arc<Mutex<Option<String>>>,
    active_is_daplink: Arc<AtomicBool>,
    is_running: Arc<AtomicBool>,
    pub dtr_state: Arc<AtomicBool>,
    pub rts_state: Arc<AtomicBool>,
}

impl SerialManager {
    pub fn new() -> Self {
        Self {
            port: Arc::new(Mutex::new(None)),
            active_port_name: Arc::new(Mutex::new(None)),
            active_is_daplink: Arc::new(AtomicBool::new(false)),
            is_running: Arc::new(AtomicBool::new(false)),
            dtr_state: Arc::new(AtomicBool::new(false)),
            rts_state: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn list_ports() -> Vec<PortInfo> {
        let ports = serialport::available_ports().unwrap_or_default();
        ports
            .into_iter()
            .map(|p| {
                let mut vid = None;
                let mut pid = None;
                let mut manufacturer = None;
                let mut product = None;
                let mut serial_number = None;
                let mut is_daplink = false;
                let mut device_type = "generic".to_string();

                if let SerialPortType::UsbPort(UsbPortInfo {
                    vid: v,
                    pid: pi,
                    serial_number: s,
                    manufacturer: ref m,
                    product: ref pr,
                }) = p.port_type
                {
                    vid = Some(v);
                    pid = Some(pi);
                    serial_number = s;
                    manufacturer = m.clone();
                    product = pr.clone();

                    let pr_lower = pr.as_deref().unwrap_or("").to_lowercase();
                    let m_lower = m.as_deref().unwrap_or("").to_lowercase();

                    // Check if DAPLink (VID 0x0D28 is ARM DAPLink, or product/mfg string matches)
                    if v == 0x0D28
                        || pr_lower.contains("cmsis")
                        || pr_lower.contains("daplink")
                        || pr_lower.contains("dap")
                        || m_lower.contains("cmsis")
                        || m_lower.contains("dap")
                    {
                        is_daplink = true;
                        device_type = "daplink".to_string();
                    }
                    // Check if J-Link (VID 0x1366 is SEGGER, or product/mfg string matches)
                    else if v == 0x1366
                        || pr_lower.contains("j-link")
                        || pr_lower.contains("jlink")
                        || pr_lower.contains("segger")
                        || m_lower.contains("segger")
                    {
                        device_type = "jlink".to_string();
                    }
                }

                let desc = product
                    .clone()
                    .or_else(|| manufacturer.clone())
                    .unwrap_or_else(|| p.port_name.clone());

                PortInfo {
                    port_name: p.port_name,
                    description: desc,
                    vid,
                    pid,
                    manufacturer,
                    product,
                    serial_number,
                    is_daplink,
                    device_type,
                }
            })
            .collect()
    }

    pub fn open(
        &self,
        app: AppHandle,
        port_name: &str,
        baud_rate: u32,
    ) -> Result<(), String> {
        self.close()?;

        let port_builder = serialport::new(port_name, baud_rate)
            .timeout(Duration::from_millis(20))
            .data_bits(serialport::DataBits::Eight)
            .stop_bits(serialport::StopBits::One)
            .parity(serialport::Parity::None);

        let mut port = port_builder
            .open()
            .map_err(|e| format!("Failed to open port {}: {}", port_name, e))?;

        // Initialize default pin state: DTR 0 (RESET released), RTS 0 (Normal mode)
        let _ = port.write_data_terminal_ready(false);
        let _ = port.write_request_to_send(false);
        self.dtr_state.store(false, Ordering::SeqCst);
        self.rts_state.store(false, Ordering::SeqCst);

        // Try clone port for the background reader thread
        let reader_port = port.try_clone().map_err(|e| e.to_string())?;

        // Determine if target port is DAPLink
        let port_list = Self::list_ports();
        let is_daplink = port_list
            .iter()
            .find(|p| p.port_name.eq_ignore_ascii_case(port_name))
            .map(|p| p.is_daplink)
            .unwrap_or(false);
        self.active_is_daplink.store(is_daplink, Ordering::SeqCst);

        {
            let mut port_guard = self.port.lock().unwrap();
            *port_guard = Some(port);
            let mut name_guard = self.active_port_name.lock().unwrap();
            *name_guard = Some(port_name.to_string());
        }

        self.is_running.store(true, Ordering::SeqCst);

        // Background reader thread with batching and throttling (prevents UI freeze at 921600 baud)
        let is_running_clone = Arc::clone(&self.is_running);
        let current_port_name = port_name.to_string();

        std::thread::spawn(move || {
            let mut reader = reader_port;
            let mut batch_buffer: Vec<u8> = Vec::with_capacity(4096);
            let mut read_buf = [0u8; 1024];
            let mut last_flush = Instant::now();

            while is_running_clone.load(Ordering::SeqCst) {
                match reader.read(&mut read_buf) {
                    Ok(n) if n > 0 => {
                        batch_buffer.extend_from_slice(&read_buf[..n]);
                    }
                    Ok(_) => {}
                    Err(ref e) if e.kind() == std::io::ErrorKind::TimedOut => {}
                    Err(_) => {
                        // Connection dropped or port closed
                        break;
                    }
                }

                // Throttle emission: flush if batch buffer >= 2048 bytes or 30ms passed
                let should_flush = !batch_buffer.is_empty()
                    && (batch_buffer.len() >= 2048 || last_flush.elapsed() >= Duration::from_millis(30));

                if should_flush {
                    let now_ms = std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .unwrap_or_default()
                        .as_millis() as u64;

                    let payload = SerialRxPayload {
                        port: current_port_name.clone(),
                        data: std::mem::take(&mut batch_buffer),
                        timestamp_ms: now_ms,
                    };

                    let _ = app.emit("serial-rx", payload);
                    last_flush = Instant::now();
                }

                std::thread::sleep(Duration::from_millis(2));
            }
        });

        Ok(())
    }

    pub fn close(&self) -> Result<(), String> {
        self.is_running.store(false, Ordering::SeqCst);
        self.active_is_daplink.store(false, Ordering::SeqCst);
        let mut port_guard = self.port.lock().unwrap();
        *port_guard = None;
        let mut name_guard = self.active_port_name.lock().unwrap();
        *name_guard = None;
        Ok(())
    }

    pub fn write_data(&self, data: &[u8]) -> Result<usize, String> {
        let mut port_guard = self.port.lock().unwrap();
        if let Some(ref mut port) = *port_guard {
            port.write_all(data)
                .map_err(|e| format!("Write failed: {}", e))?;
            port.flush().map_err(|e| format!("Flush failed: {}", e))?;
            Ok(data.len())
        } else {
            Err("Port is not open".to_string())
        }
    }

    pub fn set_dtr(&self, level: bool) -> Result<(), String> {
        let mut port_guard = self.port.lock().unwrap();
        if let Some(ref mut port) = *port_guard {
            port.write_data_terminal_ready(level)
                .map_err(|e| format!("Set DTR failed: {}", e))?;
            self.dtr_state.store(level, Ordering::SeqCst);
            Ok(())
        } else {
            Err("Port is not open".to_string())
        }
    }

    pub fn set_rts(&self, level: bool) -> Result<(), String> {
        let mut port_guard = self.port.lock().unwrap();
        if let Some(ref mut port) = *port_guard {
            port.write_request_to_send(level)
                .map_err(|e| format!("Set RTS failed: {}", e))?;
            self.rts_state.store(level, Ordering::SeqCst);
            Ok(())
        } else {
            Err("Port is not open".to_string())
        }
    }

    pub async fn execute_reset(&self, is_bootloader: bool) -> Result<(), String> {
        let (is_open, _, _, _, is_daplink) = self.get_status();
        if !is_open {
            return Err("串口未打开，无法执行硬件复位。".to_string());
        }
        if !is_daplink {
            return Err(
                "当前串口设备不是 DAPLink 探针，仅 DAPLink 硬件支持通过 RTS/DTR 硬件引脚控制复位与进入 BOOT。"
                    .to_string(),
            );
        }

        if is_bootloader {
            // Enter Bootloader State Machine:
            // 1. RTS = 1 -> 设置进入 BOOT 模式
            self.set_rts(true)?;
            // 2. 硬件电平建立/延时 500ms
            tokio::time::sleep(Duration::from_millis(500)).await;

            // 3. DTR = 1 -> 产生复位脉冲 (拉低 RESET 100ms)
            self.set_dtr(true)?;
            tokio::time::sleep(Duration::from_millis(100)).await;

            // 4. DTR = 0 -> 释放复位 (MCU 在 RTS=1 下采样进入 Bootloader)
            self.set_dtr(false)?;
        } else {
            // Normal Reset:
            // 1. RTS = 0 -> 普通运行模式
            self.set_rts(false)?;
            tokio::time::sleep(Duration::from_millis(50)).await;

            // 2. DTR = 1 -> 产生复位脉冲 (拉低 RESET 100ms)
            self.set_dtr(true)?;
            tokio::time::sleep(Duration::from_millis(100)).await;

            // 3. DTR = 0 -> 释放复位 (MCU 在 RTS=0 下采样进入正常运行)
            self.set_dtr(false)?;
        }
        Ok(())
    }

    pub fn get_status(&self) -> (bool, Option<String>, bool, bool, bool) {
        let name = self.active_port_name.lock().unwrap().clone();
        let is_open = name.is_some();
        let dtr = self.dtr_state.load(Ordering::SeqCst);
        let rts = self.rts_state.load(Ordering::SeqCst);
        let is_dap = self.active_is_daplink.load(Ordering::SeqCst);
        (is_open, name, dtr, rts, is_dap)
    }
}
