use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};

use super::serial_manager::SerialManager;

static BRIDGE_RUNNING: AtomicBool = AtomicBool::new(false);

#[derive(Serialize, Deserialize)]
struct BridgeRequest {
    action: String,
    port_name: Option<String>,
    baudrate: Option<u32>,
    data: Option<String>,
    is_hex: Option<bool>,
    append_crlf: Option<bool>,
    format: Option<String>,
    max_bytes: Option<usize>,
    clear_buffer: Option<bool>,
    after_cursor: Option<u64>,
}

fn decode_hex_str(s: &str) -> Vec<u8> {
    let clean: String = s.chars().filter(|c| c.is_ascii_hexdigit()).collect();
    let mut b = Vec::new();
    for i in (0..clean.len()).step_by(2) {
        if i + 2 <= clean.len() {
            if let Ok(val) = u8::from_str_radix(&clean[i..i+2], 16) {
                b.push(val);
            }
        }
    }
    b
}

fn get_timestamp_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

pub struct DesktopBridgeServer;

impl DesktopBridgeServer {
    pub fn get_bridge_file_path() -> PathBuf {
        std::env::temp_dir().join("ai-hil-serial-bridge.json")
    }

    pub fn start(app: AppHandle, serial_mgr: Arc<SerialManager>) -> Result<u16, String> {
        let listener = TcpListener::bind("127.0.0.1:0")
            .map_err(|e| format!("Failed to bind local loopback bridge: {}", e))?;
        let port = listener
            .local_addr()
            .map_err(|e| format!("Failed to get local port: {}", e))?
            .port();

        let bridge_info = json!({
            "pid": std::process::id(),
            "port": port,
            "version": "1.3.3"
        });

        let bridge_file = Self::get_bridge_file_path();
        let _ = std::fs::write(&bridge_file, bridge_info.to_string());
        println!("[DesktopBridge] Serial IPC Bridge listening on 127.0.0.1:{}, registered to {:?}", port, bridge_file);

        BRIDGE_RUNNING.store(true, Ordering::SeqCst);

        let app_clone = app.clone();
        let serial_clone = Arc::clone(&serial_mgr);
        let cursors: Arc<Mutex<HashMap<String, u64>>> = Arc::new(Mutex::new(HashMap::new()));

        thread::spawn(move || {
            for stream in listener.incoming() {
                if !BRIDGE_RUNNING.load(Ordering::SeqCst) {
                    break;
                }
                match stream {
                    Ok(s) => {
                        let app_h = app_clone.clone();
                        let sm = Arc::clone(&serial_clone);
                        let cur_map = Arc::clone(&cursors);
                        thread::spawn(move || {
                            Self::handle_client(s, app_h, sm, cur_map);
                        });
                    }
                    Err(e) => {
                        eprintln!("[DesktopBridge] accept error: {}", e);
                    }
                }
            }
            let _ = std::fs::remove_file(Self::get_bridge_file_path());
        });

        Ok(port)
    }

    pub fn stop() {
        BRIDGE_RUNNING.store(false, Ordering::SeqCst);
        let _ = std::fs::remove_file(Self::get_bridge_file_path());
    }

    fn handle_client(
        mut stream: TcpStream,
        app: AppHandle,
        serial: Arc<SerialManager>,
        cursors: Arc<Mutex<HashMap<String, u64>>>,
    ) {
        let _ = stream.set_read_timeout(Some(Duration::from_secs(10)));
        let _ = stream.set_write_timeout(Some(Duration::from_secs(10)));
        let reader = match stream.try_clone() {
            Ok(s) => BufReader::new(s),
            Err(_) => return,
        };

        for line in reader.lines() {
            let line = match line {
                Ok(l) => l,
                Err(_) => break,
            };
            if line.trim().is_empty() {
                continue;
            }

            let req: BridgeRequest = match serde_json::from_str(&line) {
                Ok(r) => r,
                Err(e) => {
                    let err_resp = json!({"status": "error", "message": format!("Invalid JSON: {}", e)});
                    let _ = writeln!(stream, "{}", err_resp);
                    let _ = stream.flush();
                    continue;
                }
            };

            let resp = Self::dispatch_action(&req, &app, &serial, &cursors);
            let _ = writeln!(stream, "{}", resp);
            let _ = stream.flush();
        }
    }

    fn dispatch_action(
        req: &BridgeRequest,
        app: &AppHandle,
        serial: &Arc<SerialManager>,
        cursors: &Arc<Mutex<HashMap<String, u64>>>,
    ) -> Value {
        match req.action.as_str() {
            "ping" => json!({
                "status": "ok",
                "app": "ai-hil-debugger",
                "version": "1.3.3",
                "pid": std::process::id()
            }),

            "list_ports" => {
                let physical_ports = SerialManager::list_ports();
                let active_sessions = serial.list_active_sessions();
                let mut ports_out = Vec::new();

                for p in physical_ports {
                    let is_active = active_sessions.contains(&p.port_name);
                    ports_out.push(json!({
                        "port": p.port_name,
                        "description": p.description,
                        "is_open": is_active,
                        "shared_with_vue": is_active,
                        "is_default": active_sessions.first().map_or(false, |first| first == &p.port_name)
                    }));
                }
                json!({
                    "status": "ok",
                    "ports": ports_out,
                    "active_sessions": active_sessions
                })
            }

            "open_port" => {
                let port = match &req.port_name {
                    Some(p) => p.clone(),
                    None => match serial.list_active_sessions().first() {
                        Some(p) => p.clone(),
                        None => return json!({"status": "error", "message": "No port specified and no active desktop session"}),
                    },
                };
                let baud = req.baudrate.unwrap_or(115200);

                // If already open in desktop, return success immediately with shared state
                if serial.list_active_sessions().contains(&port) {
                    return json!({
                        "status": "ok",
                        "port": port,
                        "baudrate": baud,
                        "message": "Port already opened and shared with Vue desktop",
                        "shared": true
                    });
                }

                // If not open, let SerialManager open it so Vue & MCP share it
                match serial.open(app.clone(), &port, baud) {
                    Ok(_) => json!({
                        "status": "ok",
                        "port": port,
                        "baudrate": baud,
                        "message": "Port opened in desktop and shared with MCP",
                        "shared": true
                    }),
                    Err(e) => json!({"status": "error", "message": e}),
                }
            }

            "close_port" => {
                let port = req.port_name.as_deref();
                match serial.close(port) {
                    Ok(_) => json!({"status": "ok", "message": "Port closed"}),
                    Err(e) => json!({"status": "error", "message": e}),
                }
            }

            "send_serial_data" => {
                let port = match &req.port_name {
                    Some(p) => p.clone(),
                    None => match serial.list_active_sessions().first() {
                        Some(p) => p.clone(),
                        None => return json!({"status": "error", "message": "No port specified and no active desktop session"}),
                    },
                };

                let raw_str = match &req.data {
                    Some(d) => d,
                    None => return json!({"status": "error", "message": "No data provided"}),
                };

                let mut bytes: Vec<u8> = if req.is_hex.unwrap_or(false) {
                    let cleaned = raw_str.replace(|c: char| c.is_whitespace() || c == ',' || c == ':', "");
                    if cleaned.len() % 2 != 0 {
                        return json!({"status": "error", "message": "HEX data must have even number of characters"});
                    }
                    let mut b = Vec::new();
                    for i in (0..cleaned.len()).step_by(2) {
                        match u8::from_str_radix(&cleaned[i..i+2], 16) {
                            Ok(v) => b.push(v),
                            Err(e) => return json!({"status": "error", "message": format!("Invalid hex byte: {}", e)}),
                        }
                    }
                    b
                } else {
                    raw_str.as_bytes().to_vec()
                };

                if req.append_crlf.unwrap_or(false) && !req.is_hex.unwrap_or(false) {
                    bytes.extend_from_slice(b"\r\n");
                }

                match serial.write_data(&bytes, Some(&port)) {
                    Ok(sent) => {
                        // Notify Vue terminal about the AI-originated TX
                        let _ = app.emit("serial-rx", json!({
                            "port": port,
                            "data": bytes,
                            "timestamp_ms": get_timestamp_ms(),
                            "source": "mcp-agent"
                        }));
                        json!({
                            "status": "ok",
                            "port": port,
                            "bytes_sent": sent
                        })
                    }
                    Err(e) => json!({"status": "error", "message": e}),
                }
            }

            "read_serial_data" => {
                let port = match &req.port_name {
                    Some(p) => p.clone(),
                    None => match serial.list_active_sessions().first() {
                        Some(p) => p.clone(),
                        None => return json!({"status": "error", "message": "No port specified and no active desktop session"}),
                    },
                };

                let format_type = req.format.as_deref().unwrap_or("text");
                let max_bytes = req.max_bytes.unwrap_or(4096);
                let clear_buf = req.clear_buffer.unwrap_or(true);

                let mut cur_guard = cursors.lock().unwrap();
                let last_cursor = if let Some(c) = req.after_cursor {
                    c
                } else {
                    *cur_guard.get(&port).unwrap_or(&0)
                };

                match serial.capture_page(&port, last_cursor, 500) {
                    Ok(page) => {
                        let mut gathered_bytes = Vec::new();
                        let mut latest_seq = last_cursor;

                        for ev in &page.events {
                            if ev.direction == "RX" {
                                let mut b = decode_hex_str(&ev.data);
                                gathered_bytes.append(&mut b);
                            }
                            if ev.seq > latest_seq {
                                latest_seq = ev.seq;
                            }
                        }

                        if clear_buf || req.after_cursor.is_none() {
                            cur_guard.insert(port.clone(), latest_seq);
                        }

                        if gathered_bytes.len() > max_bytes {
                            gathered_bytes = gathered_bytes[gathered_bytes.len() - max_bytes..].to_vec();
                        }

                        let data_str = if format_type == "hex" {
                            gathered_bytes.iter().map(|b| format!("{:02X}", b)).collect::<Vec<_>>().join(" ")
                        } else {
                            String::from_utf8_lossy(&gathered_bytes).to_string()
                        };

                        json!({
                            "status": "ok",
                            "port": port,
                            "data": data_str,
                            "bytes_len": gathered_bytes.len(),
                            "cursor": latest_seq,
                            "gap": page.gap
                        })
                    }
                    Err(e) => json!({"status": "error", "message": e}),
                }
            }

            other => json!({"status": "error", "message": format!("Unknown action: {}", other)}),
        }
    }
}
