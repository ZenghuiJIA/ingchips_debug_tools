use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use tauri::AppHandle;

#[cfg(target_os = "windows")]
use crate::platform::windows::job_object::ProcessJob;

pub struct DaemonManager {
    child: Arc<Mutex<Option<Child>>>,
    stdin_writer: Arc<Mutex<Option<std::process::ChildStdin>>>,
    stdout_reader: Arc<Mutex<Option<BufReader<std::process::ChildStdout>>>>,
    req_counter: AtomicU64,
    pub child_pid: Arc<Mutex<Option<u32>>>,
    #[cfg(target_os = "windows")]
    _job: Option<ProcessJob>,
}

impl DaemonManager {
    pub fn new() -> Self {
        #[cfg(target_os = "windows")]
        let job = ProcessJob::new().ok();

        Self {
            child: Arc::new(Mutex::new(None)),
            stdin_writer: Arc::new(Mutex::new(None)),
            stdout_reader: Arc::new(Mutex::new(None)),
            req_counter: AtomicU64::new(1),
            child_pid: Arc::new(Mutex::new(None)),
            #[cfg(target_os = "windows")]
            _job: job,
        }
    }

    pub fn ensure_started(&self, _app: &AppHandle) -> Result<(), String> {
        let mut child_guard = self.child.lock().unwrap();
        if child_guard.is_some() {
            return Ok(());
        }

        // Determine launch target: candidate paths in order of preference
        let mut candidates = Vec::new();

        if let Ok(exe_path) = std::env::current_exe() {
            if let Some(exe_dir) = exe_path.parent() {
                candidates.push(exe_dir.join("hil-daemon-x86_64-pc-windows-msvc.exe"));
                candidates.push(exe_dir.join("hil-daemon.exe"));
                candidates.push(exe_dir.join("binaries").join("hil-daemon-x86_64-pc-windows-msvc.exe"));
            }
        }

        candidates.push(PathBuf::from("src-tauri/binaries/hil-daemon-x86_64-pc-windows-msvc.exe"));
        candidates.push(PathBuf::from("binaries/hil-daemon-x86_64-pc-windows-msvc.exe"));
        candidates.push(PathBuf::from("hil-daemon-x86_64-pc-windows-msvc.exe"));

        let mut cmd = if let Some(found_bin) = candidates.into_iter().find(|p| p.exists()) {
            println!("[DaemonManager] Found standalone binary: {:?}", found_bin);
            Command::new(found_bin)
        } else if Path::new("src-tauri/daemon/daemon_entry.py").exists() {
            let mut c = Command::new("python");
            c.arg("src-tauri/daemon/daemon_entry.py");
            c
        } else if Path::new("daemon_entry.py").exists() {
            let mut c = Command::new("python");
            c.arg("daemon_entry.py");
            c
        } else {
            return Err("Neither standalone binary nor daemon_entry.py found".to_string());
        };

        cmd.stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit());

        #[cfg(target_os = "windows")]
        {
            // Set CREATE_NO_WINDOW flag
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x08000000);
        }

        let mut child = cmd.spawn().map_err(|e| format!("Failed to spawn daemon: {}", e))?;
        let pid = child.id();
        *self.child_pid.lock().unwrap() = Some(pid);

        #[cfg(target_os = "windows")]
        {
            if let Some(ref job) = self._job {
                use std::os::windows::io::AsRawHandle;
                let _ = job.assign_process(child.as_raw_handle());
            }
        }

        let stdin = child.stdin.take().ok_or("Failed to capture daemon stdin")?;
        let stdout = child.stdout.take().ok_or("Failed to capture daemon stdout")?;
        let reader = BufReader::new(stdout);

        *self.stdin_writer.lock().unwrap() = Some(stdin);
        *self.stdout_reader.lock().unwrap() = Some(reader);
        *child_guard = Some(child);

        println!("[DaemonManager] Python Daemon started with PID {}", pid);
        Ok(())
    }

    pub fn call_rpc(&self, method: &str, params: Value) -> Result<Value, String> {
        let req_id = self.req_counter.fetch_add(1, Ordering::SeqCst);
        let req = json!({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        });

        let mut req_str = serde_json::to_string(&req).map_err(|e| e.to_string())?;
        req_str.push('\n');

        // Write to child stdin
        {
            let mut writer_guard = self.stdin_writer.lock().unwrap();
            if let Some(ref mut writer) = *writer_guard {
                writer
                    .write_all(req_str.as_bytes())
                    .map_err(|e| format!("Daemon write error: {}", e))?;
                writer.flush().map_err(|e| format!("Daemon flush error: {}", e))?;
            } else {
                return Err("Daemon stdin not available".to_string());
            }
        }

        // Read line from child stdout
        let mut resp_line = String::new();
        {
            let mut reader_guard = self.stdout_reader.lock().unwrap();
            if let Some(ref mut reader) = *reader_guard {
                reader
                    .read_line(&mut resp_line)
                    .map_err(|e| format!("Daemon read error: {}", e))?;
            } else {
                return Err("Daemon stdout not available".to_string());
            }
        }

        if resp_line.trim().is_empty() {
            return Err("Daemon returned empty response".to_string());
        }

        let resp_val: Value = serde_json::from_str(&resp_line)
            .map_err(|e| format!("Invalid JSON from daemon: {} -> raw: {}", e, resp_line))?;

        if let Some(err) = resp_val.get("error") {
            let msg = err.get("message").and_then(|m| m.as_str()).unwrap_or("Unknown daemon error");
            return Err(msg.to_string());
        }

        Ok(resp_val.get("result").cloned().unwrap_or(Value::Null))
    }

    pub fn call_mcp_tool(&self, name: &str, arguments: Value) -> Result<Value, String> {
        self.call_rpc(
            "tools/call",
            json!({
                "name": name,
                "arguments": arguments
            }),
        )
    }

    pub fn stop(&self) {
        let mut child_guard = self.child.lock().unwrap();
        if let Some(ref mut child) = *child_guard {
            let _ = child.kill();
        }
        *child_guard = None;
        *self.stdin_writer.lock().unwrap() = None;
        *self.stdout_reader.lock().unwrap() = None;
        *self.child_pid.lock().unwrap() = None;
    }
}
