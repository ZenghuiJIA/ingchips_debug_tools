use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use sysinfo::System;
use tauri::AppHandle;

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
            *self.stdout_reader.lock().unwrap() = None;
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
                if let Err(e) = writer.write_all(req_str.as_bytes()).and_then(|_| writer.flush()) {
                    drop(writer_guard);
                    self.stop();
                    return Err(format!("Daemon write error: {}", e));
                }
            } else {
                return Err("Daemon stdin not available".to_string());
            }
        }

        // Read line from child stdout, skipping empty lines or non-JSON diagnostic noise
        let mut resp_val: Option<Value> = None;
        let mut last_raw_line = String::new();
        {
            let mut reader_guard = self.stdout_reader.lock().unwrap();
            if let Some(ref mut reader) = *reader_guard {
                loop {
                    let mut line = String::new();
                    match reader.read_line(&mut line) {
                        Ok(0) => {
                            // EOF
                            break;
                        }
                        Ok(_) => {
                            let trimmed = line.trim();
                            if trimmed.is_empty() {
                                continue;
                            }
                            last_raw_line = line.clone();
                            // Attempt to parse as JSON-RPC object
                            if trimmed.starts_with('{') {
                                if let Ok(val) = serde_json::from_str::<Value>(trimmed) {
                                    resp_val = Some(val);
                                    break;
                                }
                            }
                            // Otherwise it might be stray diagnostic output on stdout, skip and keep reading
                            println!("[DaemonManager] Ignored non-JSON stdout line: {}", trimmed);
                        }
                        Err(e) => {
                            drop(reader_guard);
                            self.stop();
                            return Err(format!("Daemon read error: {}", e));
                        }
                    }
                }
            } else {
                return Err("Daemon stdout not available".to_string());
            }
        }

        let resp_val = match resp_val {
            Some(v) => v,
            None => {
                self.stop();
                if last_raw_line.trim().is_empty() {
                    return Err("Daemon returned empty response (process may have terminated)".to_string());
                } else {
                    return Err(format!("Invalid JSON from daemon -> raw: {}", last_raw_line));
                }
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
        let child_pid = { *self.child_pid.lock().unwrap() };
        println!("[DaemonManager] Stopping daemon (child PID: {:?})...", child_pid);

        // 1. Try sending graceful shutdown RPC and close stdin pipe to trigger immediate EOF in daemon
        {
            let mut writer_guard = self.stdin_writer.lock().unwrap();
            if let Some(mut writer) = writer_guard.take() {
                let _ = writeln!(writer, "{{\"jsonrpc\":\"2.0\",\"id\":999999,\"method\":\"shutdown\",\"params\":{{}}}}");
                let _ = writer.flush();
                drop(writer);
            }
        }
        *self.stdout_reader.lock().unwrap() = None;

        // 2. Kill the process tree on Windows via taskkill /F /T immediately
        #[cfg(target_os = "windows")]
        if let Some(pid) = child_pid {
            use std::os::windows::process::CommandExt;
            let _ = Command::new("taskkill")
                .args(["/F", "/T", "/PID", &pid.to_string()])
                .creation_flags(0x08000000)
                .output();
        }

        // 3. Kill the direct child handle and reap
        {
            let mut child_guard = self.child.lock().unwrap();
            if let Some(ref mut child) = *child_guard {
                let _ = child.kill();
                let _ = child.wait();
            }
            *child_guard = None;
        }
        *self.child_pid.lock().unwrap() = None;

        // 4. Ensure all orphaned daemon processes are cleaned up
        kill_all_daemons();
    }
}

impl Drop for DaemonManager {
    fn drop(&mut self) {
        self.stop();
    }
}
