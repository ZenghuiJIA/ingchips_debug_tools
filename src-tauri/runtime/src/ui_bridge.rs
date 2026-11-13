//! Small client for the desktop UI loopback bridge.

use serde_json::{json, Map, Value};
use std::io::{BufRead, BufReader, Write};
use std::net::{SocketAddr, TcpStream};
use std::time::Duration;

const BRIDGE_FILE: &str = "ai-hil-serial-bridge.json";

fn bridge_file() -> std::path::PathBuf {
    std::env::temp_dir().join(BRIDGE_FILE)
}

fn process_alive(pid: u32) -> bool {
    let mut system = sysinfo::System::new();
    let pids = [sysinfo::Pid::from_u32(pid)];
    system.refresh_processes(sysinfo::ProcessesToUpdate::Some(&pids), true);
    system.process(sysinfo::Pid::from_u32(pid)).is_some()
}

/// Send one request to the desktop UI bridge.
///
/// `Ok(None)` means that no desktop bridge is registered. A registered but
/// unavailable bridge is returned as an error to avoid opening the same
/// physical port while the UI is still alive.
pub fn call(action: &str, args: &Value) -> Result<Option<Value>, String> {
    let path = bridge_file();
    if !path.is_file() {
        return Ok(None);
    }

    let info: Value = serde_json::from_slice(
        &std::fs::read(&path).map_err(|e| format!("Read desktop bridge registration: {e}"))?,
    )
    .map_err(|e| format!("Invalid desktop bridge registration: {e}"))?;
    let pid = info["pid"].as_u64().and_then(|value| u32::try_from(value).ok()).unwrap_or_default();
    let port = info["port"]
        .as_u64()
        .and_then(|value| u16::try_from(value).ok())
        .ok_or("Desktop bridge port is missing or invalid")?;
    let address: SocketAddr = format!("127.0.0.1:{port}")
        .parse()
        .map_err(|e| format!("Invalid desktop bridge address: {e}"))?;

    let mut stream = match TcpStream::connect_timeout(&address, Duration::from_millis(400)) {
        Ok(stream) => stream,
        Err(error) => {
            if pid == 0 || !process_alive(pid) {
                let _ = std::fs::remove_file(&path);
                return Ok(None);
            }
            return Err(format!("Desktop UI bridge is unavailable: {error}"));
        }
    };
    stream
        .set_read_timeout(Some(Duration::from_secs(3)))
        .map_err(|e| format!("Configure desktop bridge read timeout: {e}"))?;
    stream
        .set_write_timeout(Some(Duration::from_secs(3)))
        .map_err(|e| format!("Configure desktop bridge write timeout: {e}"))?;

    let mut request = Map::new();
    request.insert("action".into(), json!(action));
    if let Some(fields) = args.as_object() {
        for (key, value) in fields {
            request.insert(key.clone(), value.clone());
        }
    }
    writeln!(stream, "{}", Value::Object(request))
        .map_err(|e| format!("Write desktop bridge request: {e}"))?;
    stream
        .flush()
        .map_err(|e| format!("Flush desktop bridge request: {e}"))?;

    let mut line = String::new();
    BufReader::new(stream)
        .read_line(&mut line)
        .map_err(|e| format!("Read desktop bridge response: {e}"))?;
    if line.trim().is_empty() {
        return Err("Desktop bridge returned an empty response".into());
    }
    serde_json::from_str(line.trim())
        .map(Some)
        .map_err(|e| format!("Invalid desktop bridge response: {e}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn registration_path_is_in_temp_directory() {
        assert_eq!(bridge_file().file_name().and_then(|v| v.to_str()), Some(BRIDGE_FILE));
    }
}
