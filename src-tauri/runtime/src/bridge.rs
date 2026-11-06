use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{
    mpsc::{sync_channel, Receiver},
    Arc, Mutex,
};
use std::time::{Duration, Instant};
pub fn hide(command: &mut Command) {
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x08000000);
    }
}
pub fn terminate(child: &mut Child) {
    #[cfg(windows)]
    {
        let mut command = Command::new("taskkill");
        command.args(["/F", "/T", "/PID", &child.id().to_string()]);
        hide(&mut command);
        let _ = command.stdout(Stdio::null()).stderr(Stdio::null()).status();
    }
    let _ = child.kill();
    let _ = child.wait();
}
pub struct Bridge {
    child: Child,
    input: Arc<Mutex<ChildStdin>>,
    output: Receiver<Result<Value, String>>,
    seq: u64,
}
impl Bridge {
    pub fn start() -> Result<Self, String> {
        let here = std::env::current_exe()
            .map_err(|e| e.to_string())?
            .parent()
            .unwrap()
            .to_path_buf();
        let worker = here.join("hil-python-worker.exe");
        let mut command = if worker.is_file() {
            Command::new(worker)
        } else {
            let script = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                .parent()
                .unwrap()
                .join("daemon/daemon_entry.py");
            if !script.is_file() {
                return Err("Python probe worker is not installed".into());
            }
            let mut command = Command::new(std::env::var("HIL_PYTHON").unwrap_or("python".into()));
            command.arg(script);
            command
        };
        command
            .env("HIL_NATIVE_WORKER", "1")
            .env("PYINSTALLER_RESET_ENVIRONMENT", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        hide(&mut command);
        let mut child = command.spawn().map_err(|e| e.to_string())?;
        let input = Arc::new(Mutex::new(child.stdin.take().unwrap()));
        let output = child.stdout.take().unwrap();
        let (tx, rx) = sync_channel(4);
        std::thread::spawn(move || {
            let mut reader = BufReader::new(output);
            loop {
                let mut line = String::new();
                match reader.read_line(&mut line) {
                    Ok(0) => {
                        let _ = tx.send(Err("Python worker exited".into()));
                        break;
                    }
                    Ok(_) => {
                        if line.len() > 32 * 1024 * 1024 {
                            let _ = tx.send(Err("Worker response limit exceeded".into()));
                            break;
                        }
                        if tx
                            .send(serde_json::from_str(&line).map_err(|e| e.to_string()))
                            .is_err()
                        {
                            break;
                        }
                    }
                    Err(e) => {
                        let _ = tx.send(Err(e.to_string()));
                        break;
                    }
                }
            }
        });
        Ok(Self {
            child,
            input,
            output: rx,
            seq: 0,
        })
    }
    pub fn call(&mut self, method: &str, args: Value, timeout: Duration) -> Result<Value, String> {
        self.seq += 1;
        let request = format!(
            "{}\n",
            json!({"jsonrpc":"2.0","id":self.seq,"method":method,"params":args})
        );
        let input = self.input.clone();
        let (tx, rx) = sync_channel(1);
        let start = Instant::now();
        std::thread::spawn(move || {
            let result = input
                .lock()
                .unwrap()
                .write_all(request.as_bytes())
                .map_err(|e| e.to_string());
            let _ = tx.send(result);
        });
        if let Err(error) = rx
            .recv_timeout(timeout.min(Duration::from_secs(5)))
            .map_err(|e| e.to_string())
            .and_then(|x| x)
        {
            terminate(&mut self.child);
            return Err(format!("Python worker write failed: {error}"));
        }
        let response = self
            .output
            .recv_timeout(timeout.saturating_sub(start.elapsed()));
        let response = match response {
            Ok(Ok(value)) => value,
            other => {
                terminate(&mut self.child);
                return Err(format!(
                    "Python worker timeout/disconnect; hardware outcome unknown: {other:?}"
                ));
            }
        };
        validate_response(&response, self.seq)
    }
}
fn validate_response(response: &Value, expected_id: u64) -> Result<Value, String> {
    if response["jsonrpc"] != "2.0" { return Err("Python worker returned invalid JSON-RPC version".into()); }
    if response["id"] != expected_id { return Err("Python response ID mismatch".into()); }
    let has_result = response.get("result").is_some();
    let has_error = response.get("error").is_some();
    if has_result == has_error { return Err("Python worker returned invalid JSON-RPC result/error envelope".into()); }
    if has_error {
        if !response["error"].is_object() { return Err("Python worker returned malformed error".into()); }
        return Err(response["error"]["message"].as_str().unwrap_or("Python worker failed").into());
    }
    if response["result"].is_null() { return Err("Python worker returned null result".into()); }
    Ok(response["result"].clone())
}
#[cfg(test)]
mod response_tests {
    use super::*;
    #[test]
    fn rejects_malformed_worker_envelopes() {
        assert!(validate_response(&json!({"id":1,"result":{}}),1).is_err());
        assert!(validate_response(&json!({"jsonrpc":"2.0","id":1}),1).is_err());
        assert!(validate_response(&json!({"jsonrpc":"2.0","id":1,"result":{},"error":{}}),1).is_err());
        assert!(validate_response(&json!({"jsonrpc":"2.0","id":1,"result":null}),1).is_err());
        assert!(validate_response(&json!({"jsonrpc":"2.0","id":1,"error":null}),1).is_err());
    }
}
impl Drop for Bridge {
    fn drop(&mut self) {
        terminate(&mut self.child);
    }
}
