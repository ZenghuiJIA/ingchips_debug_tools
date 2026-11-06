use crate::serial::SerialSession;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::sync::{Arc, Mutex, OnceLock};
use std::time::{Duration, Instant};
static PORTS: OnceLock<Mutex<BTreeMap<String, (Arc<SerialSession>, u64)>>> = OnceLock::new();
fn registry() -> &'static Mutex<BTreeMap<String, (Arc<SerialSession>, u64)>> {
    PORTS.get_or_init(|| Mutex::new(BTreeMap::new()))
}
fn resolve(args: &Value) -> Result<String, String> {
    let ports = registry().lock().unwrap();
    if let Some(port) = args["port_name"].as_str() {
        let port = if port.to_uppercase().starts_with("COM") {
            port.trim().to_uppercase()
        } else {
            port.trim().into()
        };
        if ports.contains_key(&port) {
            return Ok(port);
        }
        return Err("Requested serial port is not open".into());
    }
    if ports.len() != 1 {
        return Err("Select an explicit port when zero/multiple sessions exist".into());
    }
    Ok(ports.keys().next().unwrap().clone())
}
pub fn dispatch(method: &str, args: &Value) -> Result<Value, String> {
    match method {
        "list_serial_ports" => {
            let ports = registry().lock().unwrap();
            let list = serialport::available_ports().map_err(|e| e.to_string())?;
            Ok(json!(list.into_iter().map(|p|{let(description,hwid)=match p.port_type{serialport::SerialPortType::UsbPort(info)=>(info.product.unwrap_or_default(),format!("USB VID:PID={:04X}:{:04X} SER={}",info.vid,info.pid,info.serial_number.unwrap_or_default())),_=> (String::new(),String::new())};json!({"port":p.port_name,"description":description,"hwid":hwid,"is_open":ports.contains_key(&p.port_name),"is_default":ports.len()==1&&ports.contains_key(&p.port_name)})}).collect::<Vec<_>>()))
        }
        "open_serial_port" => {
            let raw = args["port_name"].as_str().ok_or("port_name required")?;
            let port = if raw.to_uppercase().starts_with("COM") {
                raw.trim().to_uppercase()
            } else {
                raw.trim().into()
            };
            let baud = crate::config::integer(
                args.get("baudrate").unwrap_or(&json!(115200)),
                "baudrate",
                300,
                4000000,
            )? as u32;
            let mut ports = registry().lock().unwrap();
            if let Some((s, _)) = ports.get(&port) {
                if s.baudrate != baud {
                    return Err("Port already open at another baud rate".into());
                }
                return Ok(json!({"status":"already_open","port":port,"baudrate":baud}));
            }
            let session = SerialSession::open_options(&port, baud, None, args)?;
            ports.insert(port.clone(), (session, 0));
            Ok(
                json!({"status":"opened","port":port,"baudrate":baud,"open_ports":ports.keys().collect::<Vec<_>>(),"total_open_ports":ports.len()}),
            )
        }
        "close_serial_port" => {
            let port = resolve(args)?;
            let (s, _) = registry()
                .lock()
                .unwrap()
                .remove(&port)
                .ok_or("Session ended")?;
            s.close()?;
            Ok(
                json!({"status":"closed","port":port,"remaining_open_ports":registry().lock().unwrap().keys().collect::<Vec<_>>()}),
            )
        }
        "send_serial_data" => {
            let port = resolve(args)?;
            let s = registry().lock().unwrap().get(&port).unwrap().0.clone();
            let data = args["data"].as_str().ok_or("data must be text/HEX")?;
            let mut bytes = if args["is_hex"] == true {
                hil_debug_core::capture::unhex(data)?
            } else {
                data.as_bytes().into()
            };
            if args["append_crlf"] == true {
                bytes.extend(b"\r\n");
            }
            let n = s.write(&bytes)?;
            Ok(json!({"status":"sent","port":port,"bytes_sent":n}))
        }
        "read_serial_data" => {
            let port = resolve(args)?;
            let (s, cursor) = {
                let ports = registry().lock().unwrap();
                let (s, c) = ports.get(&port).unwrap();
                (s.clone(), *c)
            };
            let count = crate::config::integer(
                args.get("max_bytes").unwrap_or(&json!(4096)),
                "max_bytes",
                1,
                1024 * 1024,
            )? as usize;
            let seconds = args["timeout"].as_f64().unwrap_or(0.5);
            if !seconds.is_finite() || seconds < 0. || seconds > 30. {
                return Err("timeout must be 0..30 seconds".into());
            }
            let until = Instant::now() + Duration::from_secs_f64(seconds);
            let mut bytes = vec![];
            let total = loop {
                let (chunks, end) = s.journal.lock().unwrap().read(cursor)?;
                for c in chunks {
                    bytes.extend(c.data);
                }
                if !bytes.is_empty() || Instant::now() >= until {
                    break end;
                }
                std::thread::sleep(Duration::from_millis(5));
            };
            bytes.truncate(count);
            if args["clear_buffer"] != false {
                if let Some((_, c)) = registry().lock().unwrap().get_mut(&port) {
                    *c = cursor + bytes.len() as u64;
                }
            }
            let format = args["format"].as_str().unwrap_or("text");
            if !["text", "hex"].contains(&format) {
                return Err("format must be text/hex".into());
            }
            Ok(
                json!({"port":port,"bytes_read":bytes.len(),"format":format,"data":if format=="hex"{hil_debug_core::capture::hex(&bytes).to_uppercase()}else{String::from_utf8_lossy(&bytes).into_owned()},"has_more":total>cursor+bytes.len()as u64}),
            )
        }
        _ => Err("Unknown serial operation".into()),
    }
}
pub fn close_all() {
    let sessions = std::mem::take(&mut *registry().lock().unwrap());
    for (_, (s, _)) in sessions {
        let _ = s.close();
    }
}
