use serde::{Deserialize, Serialize};
use serialport::{SerialPort, SerialPortType, UsbPortInfo};
use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::TcpStream;
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

use super::protocol_engine::{ProtocolConfig, ProtocolEngine};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WaveformPointsPayload {
    pub port: String,
    pub points: Vec<HashMap<String, f64>>,
    pub timestamp_ms: u64,
}

/// A dedicated session for a single opened COM port or RTT TCP bridge
pub struct PortSession {
    pub port_name: String,
    pub port: Option<Box<dyn SerialPort>>,
    pub rtt_stream: Option<TcpStream>,
    pub is_daplink: bool,
    pub is_running: Arc<AtomicBool>,
    pub dtr_state: Arc<AtomicBool>,
    pub rts_state: Arc<AtomicBool>,
}

impl PortSession {
    pub fn close(&mut self) {
        self.is_running.store(false, Ordering::SeqCst);
        self.port = None;
        self.rtt_stream = None;
    }
}

pub struct SerialManager {
    sessions: Arc<Mutex<HashMap<String, Arc<Mutex<PortSession>>>>>,
    last_active_port: Arc<Mutex<Option<String>>>,
    pub waveform_source: Arc<Mutex<Option<String>>>,
    pub protocol_engine: Arc<Mutex<Option<ProtocolEngine>>>,
}

impl SerialManager {
    pub fn new() -> Self {
        Self {
            sessions: Arc::new(Mutex::new(HashMap::new())),
            last_active_port: Arc::new(Mutex::new(None)),
            waveform_source: Arc::new(Mutex::new(None)),
            protocol_engine: Arc::new(Mutex::new(None)),
        }
    }

    pub fn set_protocol_config(&self, config_json: &str) -> Result<(), String> {
        let config: ProtocolConfig = serde_json::from_str(config_json)
            .map_err(|e| format!("Invalid protocol JSON config: {}", e))?;
        let mut engine_guard = self.protocol_engine.lock().unwrap();
        if let Some(engine) = engine_guard.as_mut() {
            engine.update_config(config);
        } else {
            *engine_guard = Some(ProtocolEngine::new(config));
        }
        Ok(())
    }

    pub fn clear_protocol(&self) {
        let mut engine_guard = self.protocol_engine.lock().unwrap();
        *engine_guard = None;
    }

    pub fn set_waveform_source(&self, port_name: Option<String>) {
        let mut source_guard = self.waveform_source.lock().unwrap();
        *source_guard = port_name;
    }

    pub fn get_waveform_source(&self) -> Option<String> {
        self.waveform_source.lock().unwrap().clone()
    }

    pub fn list_ports() -> Vec<PortInfo> {
        let ports = serialport::available_ports().unwrap_or_default();
        let mut result: Vec<PortInfo> = ports
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
                    serial_number: ref s,
                    manufacturer: ref m,
                    product: ref pr,
                }) = p.port_type
                {
                    vid = Some(v);
                    pid = Some(pi);
                    serial_number = s.clone();
                    manufacturer = m.clone();
                    product = pr.clone();

                    let pr_lower = pr.as_deref().unwrap_or("").to_lowercase();
                    let m_lower = m.as_deref().unwrap_or("").to_lowercase();

                    if v == 0x0D28
                        || pr_lower.contains("cmsis")
                        || pr_lower.contains("daplink")
                        || pr_lower.contains("dap")
                        || m_lower.contains("cmsis")
                        || m_lower.contains("dap")
                    {
                        is_daplink = true;
                        device_type = "daplink".to_string();
                    } else if v == 0x1366 || pr_lower.contains("j-link") || pr_lower.contains("jlink") {
                        device_type = "jlink".to_string();
                    } else {
                        device_type = "usb_serial".to_string();
                    }
                }

                PortInfo {
                    port_name: p.port_name.clone(),
                    description: match &p.port_type {
                        SerialPortType::UsbPort(usb) => {
                            let mut desc_parts = Vec::new();
                            if let Some(mfg) = &usb.manufacturer {
                                desc_parts.push(mfg.as_str());
                            }
                            if let Some(prod) = &usb.product {
                                desc_parts.push(prod.as_str());
                            }
                            if desc_parts.is_empty() {
                                "USB 虚拟串口设备".to_string()
                            } else {
                                desc_parts.join(" ")
                            }
                        }
                        SerialPortType::PciPort => "PCI 板载硬件串口".to_string(),
                        SerialPortType::BluetoothPort => "蓝牙无线串口 (SPP)".to_string(),
                        SerialPortType::Unknown => "系统通信端口 (COM)".to_string(),
                    },
                    vid,
                    pid,
                    manufacturer,
                    product,
                    serial_number,
                    is_daplink,
                    device_type,
                }
            })
            .collect();

        // Virtual SEGGER RTT options
        result.push(PortInfo {
            port_name: "RTT (J-Link 实时传输)".to_string(),
            description: "SEGGER J-Link 高速 RTT 虚拟串口通道".to_string(),
            vid: Some(0x1366),
            pid: None,
            manufacturer: Some("SEGGER".to_string()),
            product: Some("J-Link RTT Stream".to_string()),
            serial_number: None,
            is_daplink: false,
            device_type: "rtt_jlink".to_string(),
        });

        result.push(PortInfo {
            port_name: "RTT (DAPLink 实时传输)".to_string(),
            description: "DAPLink / CMSIS-DAP SWD 内存轮询 RTT 通道".to_string(),
            vid: Some(0x0D28),
            pid: None,
            manufacturer: Some("ARM".to_string()),
            product: Some("DAPLink RTT Stream".to_string()),
            serial_number: None,
            is_daplink: false,
            device_type: "rtt_daplink".to_string(),
        });

        result
    }

    pub fn list_active_sessions(&self) -> Vec<String> {
        let sessions = self.sessions.lock().unwrap();
        sessions.keys().cloned().collect()
    }

    pub fn open_rtt(
        &self,
        app: AppHandle,
        port_name: &str,
        tcp_port: u16,
    ) -> Result<(), String> {
        // If already open, close previous session for this port
        let _ = self.close(Some(port_name));

        let stream = TcpStream::connect(format!("127.0.0.1:{}", tcp_port))
            .map_err(|e| format!("Failed to connect to RTT TCP bridge (port {}): {}", tcp_port, e))?;
        stream
            .set_read_timeout(Some(Duration::from_millis(50)))
            .map_err(|e| e.to_string())?;

        let reader_stream = stream.try_clone().map_err(|e| e.to_string())?;

        let is_running = Arc::new(AtomicBool::new(true));
        let session = Arc::new(Mutex::new(PortSession {
            port_name: port_name.to_string(),
            port: None,
            rtt_stream: Some(stream),
            is_daplink: false,
            is_running: Arc::clone(&is_running),
            dtr_state: Arc::new(AtomicBool::new(false)),
            rts_state: Arc::new(AtomicBool::new(false)),
        }));

        {
            let mut sessions_guard = self.sessions.lock().unwrap();
            sessions_guard.insert(port_name.to_string(), Arc::clone(&session));
            let mut last_active = self.last_active_port.lock().unwrap();
            *last_active = Some(port_name.to_string());
            // If waveform source not set, bind default
            let mut wf_guard = self.waveform_source.lock().unwrap();
            if wf_guard.is_none() {
                *wf_guard = Some(port_name.to_string());
            }
        }

        let is_running_clone = Arc::clone(&is_running);
        let current_port_name = port_name.to_string();
        let protocol_engine_clone = Arc::clone(&self.protocol_engine);
        let waveform_source_clone = Arc::clone(&self.waveform_source);

        // Background reader thread for RTT TCP stream
        std::thread::spawn(move || {
            let mut reader = reader_stream;
            let mut batch_buffer: Vec<u8> = Vec::with_capacity(4096);
            let mut read_buf = [0u8; 1024];
            let mut last_flush = Instant::now();

            while is_running_clone.load(Ordering::SeqCst) {
                match reader.read(&mut read_buf) {
                    Ok(n) if n > 0 => {
                        let incoming = &read_buf[..n];

                        // If waveform is bound to this port, feed to protocol engine
                        let is_target_wf = {
                            if let Ok(wf_guard) = waveform_source_clone.lock() {
                                wf_guard.as_deref() == Some(&current_port_name) || wf_guard.is_none()
                            } else {
                                false
                            }
                        };

                        if is_target_wf {
                            let mut parsed_points = Vec::new();
                            {
                                if let Ok(mut engine_opt) = protocol_engine_clone.lock() {
                                    if let Some(engine) = engine_opt.as_mut() {
                                        parsed_points = engine.parse_chunk(incoming);
                                    }
                                }
                            }
                            if !parsed_points.is_empty() {
                                let now_ms = std::time::SystemTime::now()
                                    .duration_since(std::time::UNIX_EPOCH)
                                    .unwrap_or_default()
                                    .as_millis() as u64;
                                let points_payload = WaveformPointsPayload {
                                    port: current_port_name.clone(),
                                    points: parsed_points,
                                    timestamp_ms: now_ms,
                                };
                                let _ = app.emit("waveform-points", points_payload);
                            }
                        }

                        batch_buffer.extend_from_slice(incoming);
                    }
                    Ok(_) => {}
                    Err(ref e) if e.kind() == std::io::ErrorKind::TimedOut || e.kind() == std::io::ErrorKind::WouldBlock => {}
                    Err(_) => {
                        break;
                    }
                }

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

    pub fn open(
        &self,
        app: AppHandle,
        port_name: &str,
        baud_rate: u32,
    ) -> Result<(), String> {
        let _ = self.close(Some(port_name));

        let port_builder = serialport::new(port_name, baud_rate)
            .timeout(Duration::from_millis(20))
            .data_bits(serialport::DataBits::Eight)
            .stop_bits(serialport::StopBits::One)
            .parity(serialport::Parity::None);

        let mut port = port_builder
            .open()
            .map_err(|e| format!("Failed to open port {}: {}", port_name, e))?;

        let _ = port.write_data_terminal_ready(false);
        let _ = port.write_request_to_send(false);

        let reader_port = port.try_clone().map_err(|e| e.to_string())?;

        let port_list = Self::list_ports();
        let is_daplink = port_list
            .iter()
            .find(|p| p.port_name.eq_ignore_ascii_case(port_name))
            .map(|p| p.is_daplink)
            .unwrap_or(false);

        let is_running = Arc::new(AtomicBool::new(true));
        let dtr_state = Arc::new(AtomicBool::new(false));
        let rts_state = Arc::new(AtomicBool::new(false));

        let session = Arc::new(Mutex::new(PortSession {
            port_name: port_name.to_string(),
            port: Some(port),
            rtt_stream: None,
            is_daplink,
            is_running: Arc::clone(&is_running),
            dtr_state: Arc::clone(&dtr_state),
            rts_state: Arc::clone(&rts_state),
        }));

        {
            let mut sessions_guard = self.sessions.lock().unwrap();
            sessions_guard.insert(port_name.to_string(), Arc::clone(&session));
            let mut last_active = self.last_active_port.lock().unwrap();
            *last_active = Some(port_name.to_string());
            let mut wf_guard = self.waveform_source.lock().unwrap();
            if wf_guard.is_none() {
                *wf_guard = Some(port_name.to_string());
            }
        }

        let is_running_clone = Arc::clone(&is_running);
        let current_port_name = port_name.to_string();
        let protocol_engine_clone = Arc::clone(&self.protocol_engine);
        let waveform_source_clone = Arc::clone(&self.waveform_source);

        std::thread::spawn(move || {
            let mut reader = reader_port;
            let mut batch_buffer: Vec<u8> = Vec::with_capacity(4096);
            let mut read_buf = [0u8; 1024];
            let mut last_flush = Instant::now();

            while is_running_clone.load(Ordering::SeqCst) {
                match reader.read(&mut read_buf) {
                    Ok(n) if n > 0 => {
                        let incoming = &read_buf[..n];

                        let is_target_wf = {
                            if let Ok(wf_guard) = waveform_source_clone.lock() {
                                wf_guard.as_deref() == Some(&current_port_name) || wf_guard.is_none()
                            } else {
                                false
                            }
                        };

                        if is_target_wf {
                            let mut parsed_points = Vec::new();
                            {
                                if let Ok(mut engine_opt) = protocol_engine_clone.lock() {
                                    if let Some(engine) = engine_opt.as_mut() {
                                        parsed_points = engine.parse_chunk(incoming);
                                    }
                                }
                            }
                            if !parsed_points.is_empty() {
                                let now_ms = std::time::SystemTime::now()
                                    .duration_since(std::time::UNIX_EPOCH)
                                    .unwrap_or_default()
                                    .as_millis() as u64;
                                let points_payload = WaveformPointsPayload {
                                    port: current_port_name.clone(),
                                    points: parsed_points,
                                    timestamp_ms: now_ms,
                                };
                                let _ = app.emit("waveform-points", points_payload);
                            }
                        }

                        batch_buffer.extend_from_slice(incoming);
                    }
                    Ok(_) => {}
                    Err(ref e) if e.kind() == std::io::ErrorKind::TimedOut => {}
                    Err(_) => {
                        break;
                    }
                }

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

    pub fn close(&self, port_name: Option<&str>) -> Result<(), String> {
        let mut sessions_guard = self.sessions.lock().unwrap();
        if let Some(target) = port_name {
            if let Some(session_arc) = sessions_guard.remove(target) {
                let mut session = session_arc.lock().unwrap();
                session.close();
            }
            let mut last_active = self.last_active_port.lock().unwrap();
            if last_active.as_deref() == Some(target) {
                *last_active = sessions_guard.keys().next().cloned();
            }
            let mut wf_guard = self.waveform_source.lock().unwrap();
            if wf_guard.as_deref() == Some(target) {
                *wf_guard = sessions_guard.keys().next().cloned();
            }
        } else {
            // Close all
            for (_, session_arc) in sessions_guard.drain() {
                let mut session = session_arc.lock().unwrap();
                session.close();
            }
            let mut last_active = self.last_active_port.lock().unwrap();
            *last_active = None;
            let mut wf_guard = self.waveform_source.lock().unwrap();
            *wf_guard = None;
        }
        Ok(())
    }

    fn resolve_session(&self, port_name: Option<&str>) -> Result<Arc<Mutex<PortSession>>, String> {
        let sessions = self.sessions.lock().unwrap();
        if let Some(target) = port_name {
            sessions
                .get(target)
                .cloned()
                .ok_or_else(|| format!("端口 '{}' 未打开", target))
        } else {
            let last_active = self.last_active_port.lock().unwrap();
            if let Some(active) = last_active.as_deref() {
                sessions
                    .get(active)
                    .cloned()
                    .ok_or_else(|| "当前活跃端口已关闭".to_string())
            } else if let Some((_, first)) = sessions.iter().next() {
                Ok(Arc::clone(first))
            } else {
                Err("未打开任何串口设备".to_string())
            }
        }
    }

    pub fn write_data(&self, data: &[u8], port_name: Option<&str>) -> Result<usize, String> {
        let session_arc = self.resolve_session(port_name)?;
        let mut session = session_arc.lock().unwrap();

        if let Some(ref mut port) = session.port {
            port.write_all(data)
                .map_err(|e| format!("Write failed: {}", e))?;
            port.flush().map_err(|e| format!("Flush failed: {}", e))?;
            return Ok(data.len());
        }

        if let Some(ref mut stream) = session.rtt_stream {
            stream
                .write_all(data)
                .map_err(|e| format!("RTT Write failed: {}", e))?;
            stream.flush().map_err(|e| format!("RTT Flush failed: {}", e))?;
            return Ok(data.len());
        }

        Err("目标端口未处于连接状态".to_string())
    }

    pub fn set_dtr(&self, level: bool, port_name: Option<&str>) -> Result<(), String> {
        let session_arc = self.resolve_session(port_name)?;
        let mut session = session_arc.lock().unwrap();
        if let Some(ref mut port) = session.port {
            port.write_data_terminal_ready(level)
                .map_err(|e| format!("Set DTR failed: {}", e))?;
            session.dtr_state.store(level, Ordering::SeqCst);
            Ok(())
        } else {
            Err("目标串口未打开".to_string())
        }
    }

    pub fn set_rts(&self, level: bool, port_name: Option<&str>) -> Result<(), String> {
        let session_arc = self.resolve_session(port_name)?;
        let mut session = session_arc.lock().unwrap();
        if let Some(ref mut port) = session.port {
            port.write_request_to_send(level)
                .map_err(|e| format!("Set RTS failed: {}", e))?;
            session.rts_state.store(level, Ordering::SeqCst);
            Ok(())
        } else {
            Err("目标串口未打开".to_string())
        }
    }

    pub async fn execute_reset(&self, is_bootloader: bool, port_name: Option<&str>) -> Result<(), String> {
        let (is_open, _, _, _, is_daplink) = self.get_status(port_name);
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
            self.set_rts(true, port_name)?;
            tokio::time::sleep(Duration::from_millis(500)).await;

            self.set_dtr(true, port_name)?;
            tokio::time::sleep(Duration::from_millis(100)).await;

            self.set_dtr(false, port_name)?;
        } else {
            self.set_rts(false, port_name)?;
            tokio::time::sleep(Duration::from_millis(50)).await;

            self.set_dtr(true, port_name)?;
            tokio::time::sleep(Duration::from_millis(100)).await;

            self.set_dtr(false, port_name)?;
        }
        Ok(())
    }

    pub fn get_status(&self, port_name: Option<&str>) -> (bool, Option<String>, bool, bool, bool) {
        if let Ok(session_arc) = self.resolve_session(port_name) {
            let session = session_arc.lock().unwrap();
            let name = session.port_name.clone();
            let is_open = session.is_running.load(Ordering::SeqCst);
            let dtr = session.dtr_state.load(Ordering::SeqCst);
            let rts = session.rts_state.load(Ordering::SeqCst);
            let is_dap = session.is_daplink;
            (is_open, Some(name), dtr, rts, is_dap)
        } else {
            (false, None, false, false, false)
        }
    }
}
