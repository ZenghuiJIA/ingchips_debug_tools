use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::Duration;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use tauri::AppHandle;

use super::serial_manager::SerialManager;

static BRIDGE_RUNNING: AtomicBool = AtomicBool::new(false);

#[derive(Serialize, Deserialize)]
struct BridgeRequest {
    action: String,
    #[serde(default)]
    access_mode: Option<String>,
    #[serde(default)]
    seq_type: Option<String>,
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
            "version": "1.3.5"
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
        _app: &AppHandle,
        serial: &Arc<SerialManager>,
        cursors: &Arc<Mutex<HashMap<String, u64>>>,
    ) -> Value {
        match req.action.as_str() {
            "ping" => json!({
                "status": "ok",
                "app": "ai-hil-debugger",
                "version": "1.3.5",
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
                    "active_sessions": active_sessions,
                    "owner": "desktop-ui",
                    "access": "read_only"
                })
            }

            "get_ui_state" => json!({
                "status": "ok",
                "owner": "desktop-ui",
                "pid": std::process::id(),
                "serial_sessions": serial.session_snapshots(),
                "capabilities": {
                    "serial_read": true,
                    "serial_write": false,
                    "serial_close": false,
                    "serial_reset": false
                }
            }),

            "get_serial_snapshot" => {
                let port = match &req.port_name {
                    Some(p) => p.clone(),
                    None => match serial.list_active_sessions().first() {
                        Some(p) => p.clone(),
                        None => return json!({"status": "error", "message": "No active desktop serial session"}),
                    },
                };
                let after = req.after_cursor.unwrap_or(0);
                let limit = req.max_bytes.unwrap_or(200).clamp(1, 1000);
                match serial.capture_page(&port, after, limit) {
                    Ok(page) => json!({
                        "status": "ok",
                        "owner": "desktop-ui",
                        "port": port,
                        "read_only": true,
                        "page": page
                    }),
                    Err(e) => json!({"status": "error", "message": e}),
                }
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

                let access_mode = req.access_mode.as_deref().unwrap_or("observe");
                if access_mode != "observe" && access_mode != "control" {
                    return json!({"status": "error", "message": "access_mode must be observe or control"});
                }

                // MCP may observe an existing UI session but must not create or
                // reconfigure a desktop-owned session behind the user's back.
                if serial.list_active_sessions().contains(&port) {
                    if access_mode == "control" {
                        return json!({
                            "status": "resource_busy",
                            "resource": format!("serial:{}", port),
                            "owner": "desktop-ui",
                            "retryable": true,
                            "message": "串口由桌面 UI 持有；请在 UI 中发送/关闭，或先释放该会话"
                        });
                    }
                    return json!({
                        "status": "shared_read_only",
                        "port": port,
                        "baudrate": baud,
                        "message": "Port is shared with Vue desktop in read-only mode",
                        "shared": true,
                        "owner": "desktop-ui",
                        "read_only": true
                    });
                }
                json!({
                    "status": "resource_busy",
                    "resource": format!("serial:{}", port),
                    "owner": "desktop-ui",
                    "retryable": true,
                    "message": "桌面 bridge 不会替 MCP 创建新的串口会话；请先在 UI 打开串口"
                })
            }

            "close_port" => {
                let port = req.port_name.as_deref();
                let port_name = port.map(str::to_string).or_else(|| serial.list_active_sessions().first().cloned());
                json!({
                    "status": "resource_busy",
                    "resource": port_name.map(|p| format!("serial:{}", p)).unwrap_or_else(|| "serial:unknown".into()),
                    "owner": "desktop-ui",
                    "retryable": true,
                    "message": "串口由桌面 UI 持有；MCP 不能关闭 UI 会话"
                })
            }

            "send_serial_data" => {
                let port = match &req.port_name {
                    Some(p) => p.clone(),
                    None => match serial.list_active_sessions().first() {
                        Some(p) => p.clone(),
                        None => return json!({"status": "error", "message": "No port specified and no active desktop session"}),
                    },
                };

                return json!({
                    "status": "resource_busy",
                    "resource": format!("serial:{}", port),
                    "owner": "desktop-ui",
                    "retryable": true,
                    "message": "串口由桌面 UI 持有；MCP 默认只读，发送请通过 UI 或显式释放串口"
                });
            }

            "reset_serial" => {
                let port = req.port_name.clone().or_else(|| serial.list_active_sessions().first().cloned());
                json!({
                    "status": "resource_busy",
                    "resource": port.map(|p| format!("serial:{}", p)).unwrap_or_else(|| "serial:unknown".into()),
                    "owner": "desktop-ui",
                    "retryable": true,
                    "message": "串口 RTS/DTR 复位属于独占控制，MCP 不会抢占 UI 会话；请在 UI 执行"
                })
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
