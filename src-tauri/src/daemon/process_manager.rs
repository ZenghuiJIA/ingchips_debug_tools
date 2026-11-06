use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::sync::mpsc::{self, Receiver};
use std::time::Duration;
use sysinfo::System;
use tauri::AppHandle;

fn receive_response(receiver: &Receiver<Result<Value, String>>, id: u64, timeout: Duration) -> Result<Value, String> {
    let response = receiver.recv_timeout(timeout).map_err(|e| format!("RPC response timeout/disconnect: {}", e))??;
    if response.get("id").and_then(Value::as_u64) != Some(id) {
        return Err("RPC response ID mismatch".into());
    }
    if response.get("jsonrpc").and_then(Value::as_str) != Some("2.0") || (response.get("result").is_none() && response.get("error").is_none()) {
        return Err("Invalid JSON-RPC response".into());
    }
    Ok(response)
}

#[cfg(target_os = "windows")]
use crate::platform::windows::job_object::ProcessJob;

/// Clean up any orphan or lingering hil-daemon background processes that belong to this app or are orphaned
pub fn kill_all_daemons() {
    let mut sys = System::new();
    sys.refresh_processes(sysinfo::ProcessesToUpdate::All, true);
    let my_pid = std::process::id();

    for (pid, proc_) in sys.processes() {
        let raw_pid = pid.as_u32();
        if raw_pid == my_pid {
            continue;
        }
        let name = proc_.name().to_string_lossy().to_lowercase();
        if name.contains("hil-daemon") {
            // Determine whether this process is an orphan or was launched by this app
            let is_orphan_or_mine = if let Some(ppid) = proc_.parent() {
                let parent_id = ppid.as_u32();
                // Parent is this app, or parent no longer exists in system -> orphan
                parent_id == my_pid || !sys.processes().contains_key(&ppid)
            } else {
                true
            };

            if is_orphan_or_mine {
                println!("[DaemonManager] Killing lingering daemon process tree: PID {} ({})", raw_pid, name);
                #[cfg(target_os = "windows")]
                {
                    use std::os::windows::process::CommandExt;
                    let _ = Command::new("taskkill")
                        .args(["/F", "/T", "/PID", &raw_pid.to_string()])
                        .creation_flags(0x08000000)
                        .output();
                }
                let _ = proc_.kill();
            }
        }
    }
}

pub struct DaemonManager {
    child: Arc<Mutex<Option<Child>>>,
    stdin_writer: Arc<Mutex<Option<std::process::ChildStdin>>>,
    responses: Mutex<Option<Arc<Mutex<Receiver<Result<Value, String>>>>>>,
    rpc_lock: Mutex<()>,
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
            responses: Mutex::new(None),
            rpc_lock: Mutex::new(()),
            req_counter: AtomicU64::new(1),
            child_pid: Arc::new(Mutex::new(None)),
            #[cfg(target_os = "windows")]
            _job: job,
        }
    }

    pub fn ensure_started(&self, _app: &AppHandle) -> Result<(), String> {
        let mut child_guard = self.child.lock().unwrap();
        if let Some(ref mut child) = *child_guard {
            match child.try_wait() {
                Ok(None) => {
                    // Daemon process is running normally
                    return Ok(());
                }
                _ => {
                    println!("[DaemonManager] Previous daemon exited. Re-spawning clean instance...");
                }
            }
            *child_guard = None;
            *self.stdin_writer.lock().unwrap() = None;
            *self.responses.lock().unwrap() = None;
            *self.child_pid.lock().unwrap() = None;
        }

        // Determine launch target: candidate paths in order of preference
        let mut candidates = Vec::new();

        if let Ok(exe_path) = std::env::current_exe() {
            if let Some(exe_dir) = exe_path.parent() {
                // Same directory as AI-HIL-Debugger.exe
                candidates.push(exe_dir.join("hil-daemon-x86_64-pc-windows-msvc.exe"));
                candidates.push(exe_dir.join("hil-daemon.exe"));
                // bin/ subdirectory (Release structure)
                candidates.push(exe_dir.join("bin").join("hil-daemon-x86_64-pc-windows-msvc.exe"));
                candidates.push(exe_dir.join("bin").join("hil-daemon.exe"));
                // binaries/ subdirectory
                candidates.push(exe_dir.join("binaries").join("hil-daemon-x86_64-pc-windows-msvc.exe"));
                // Parent directory structures (e.g. if run from bin/ or target/release/)
                if let Some(parent) = exe_dir.parent() {
                    candidates.push(parent.join("bin").join("hil-daemon-x86_64-pc-windows-msvc.exe"));
                    candidates.push(parent.join("hil-daemon-x86_64-pc-windows-msvc.exe"));
                    candidates.push(parent.join("binaries").join("hil-daemon-x86_64-pc-windows-msvc.exe"));
                }
            }
        }

        candidates.push(PathBuf::from("bin/hil-daemon-x86_64-pc-windows-msvc.exe"));
        candidates.push(PathBuf::from("hil-daemon-x86_64-pc-windows-msvc.exe"));
        candidates.push(PathBuf::from("src-tauri/binaries/hil-daemon-x86_64-pc-windows-msvc.exe"));
        candidates.push(PathBuf::from("binaries/hil-daemon-x86_64-pc-windows-msvc.exe"));

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

        let my_pid = std::process::id();
        cmd.env("AI_HIL_PARENT_PID", my_pid.to_string());
        cmd.arg("--parent-pid").arg(my_pid.to_string());

        cmd.stdin(Stdio::piped())
            .stdout(Stdio::piped());

        #[cfg(debug_assertions)]
        cmd.stderr(Stdio::inherit());

        #[cfg(not(debug_assertions))]
        cmd.stderr(Stdio::null());

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
                match job.assign_process(child.as_raw_handle()) {
                    Ok(_) => println!("[DaemonManager] Process {} assigned to Windows Job Object", pid),
                    Err(e) => println!("[DaemonManager] Warning: JobObject assign_process failed: {}", e),
                }
            }
        }

        let stdin = child.stdin.take().ok_or("Failed to capture daemon stdin")?;
        let stdout = child.stdout.take().ok_or("Failed to capture daemon stdout")?;
        let (tx, rx) = mpsc::channel();
        // Only this thread owns stdout. RPC callers wait on a bounded-time channel;
        // shutdown never needs the lock held by a blocking pipe read.
        std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                match line {
                    Ok(line) => {
                        if let Ok(value) = serde_json::from_str::<Value>(&line) {
                            if tx.send(Ok(value)).is_err() { return; }
                        }
                    }
                    Err(err) => { let _ = tx.send(Err(err.to_string())); return; }
                }
            }
            let _ = tx.send(Err("Daemon stdout closed".to_string()));
        });

        *self.stdin_writer.lock().unwrap() = Some(stdin);
        *self.responses.lock().unwrap() = Some(Arc::new(Mutex::new(rx)));
        *child_guard = Some(child);

        println!("[DaemonManager] Python Daemon started with PID {}", pid);
        Ok(())
    }

    pub fn call_rpc(&self, method: &str, params: Value) -> Result<Value, String> {
        let _transaction = self.rpc_lock.try_lock()
            .map_err(|_| "硬件服务正在执行其他操作，请等待当前任务完成".to_string())?;
        let receiver = self.responses.lock().unwrap().clone()
            .ok_or("Daemon not started")?;
        let req_id = self.req_counter.fetch_add(1, Ordering::SeqCst);
        let req = json!({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params
        });

        let mut req_str = serde_json::to_string(&req).map_err(|e| e.to_string())?;
        req_str.push('\n');

        let writer = Arc::clone(&self.stdin_writer);
        let (sent, written) = mpsc::channel();
        std::thread::spawn(move || {
            let mut guard = writer.lock().unwrap();
            let result = match guard.as_mut() {
                Some(writer) => writer.write_all(req_str.as_bytes()).and_then(|_| writer.flush()).map_err(|e| e.to_string()),
                None => Err("Daemon stdin not available".to_string()),
            };
            let _ = sent.send(result);
        });
        if !matches!(written.recv_timeout(Duration::from_secs(5)), Ok(Ok(()))) {
            self.stop();
            return Err("Daemon request write failed/timed out; service stopped".into());
        }

        let tool = params.get("name").and_then(Value::as_str).unwrap_or(method);
        let timeout = if tool.contains("flash") || tool.contains("dump") || tool.contains("load_file") { 300 } else { 30 };
        let response = receive_response(&receiver.lock().unwrap(), req_id, Duration::from_secs(timeout));
        let resp_val = match response {
            Ok(value) => value,
            other => {
                self.stop();
                return Err(format!("Daemon RPC {} failed or timed out; service stopped, retry to restart: {:?}", method, other));
            }
        };

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
        // Serialise process replacement with ensure_started. No stdout locks here.
        let mut child_guard = self.child.lock().unwrap();
        if let Some(mut child) = child_guard.take() {
            #[cfg(target_os = "windows")]
            {
                use std::os::windows::process::CommandExt;
                let _ = Command::new("taskkill")
                    .args(["/F", "/T", "/PID", &child.id().to_string()])
                    .creation_flags(0x08000000).output();
            }
            let _ = child.kill();
            let _ = child.wait();
        }
        *self.stdin_writer.lock().unwrap() = None;
        *self.responses.lock().unwrap() = None;
        *self.child_pid.lock().unwrap() = None;
    }

}

impl Drop for DaemonManager {
    fn drop(&mut self) {
        self.stop();
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rpc_rejects_crossed_responses_and_malformed_results() {
        let (tx, rx) = mpsc::channel();
        tx.send(Ok(json!({"jsonrpc":"2.0", "id":2, "result":{"bytes":[1]}}))).unwrap();
        assert!(receive_response(&rx, 1, Duration::from_millis(20)).unwrap_err().contains("mismatch"));
        tx.send(Ok(json!({"jsonrpc":"2.0", "id":1}))).unwrap();
        assert!(receive_response(&rx, 1, Duration::from_millis(20)).is_err());
        tx.send(Ok(json!({"jsonrpc":"2.0", "id":1, "result":{"bytes":[1]}}))).unwrap();
        assert_eq!(receive_response(&rx, 1, Duration::from_millis(20)).unwrap()["result"]["bytes"][0], 1);
    }

    #[test]
    fn rpc_wait_has_a_deadline_and_handles_eof() {
        let (tx, rx) = mpsc::channel();
        assert!(receive_response(&rx, 1, Duration::from_millis(10)).is_err());
        drop(tx);
        assert!(receive_response(&rx, 1, Duration::from_secs(5)).is_err());
    }
}
