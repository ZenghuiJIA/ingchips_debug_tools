use hil_runtime::{
    bridge::Bridge,
    config,
    runner::{report_root, Jobs, Worker},
};
use serde_json::{json, Value};
use std::io::{BufRead, Write};
use std::path::PathBuf;
use std::time::{Duration, Instant};
fn dispatch(
    jobs: &Jobs,
    bridge: &mut Option<Bridge>,
    method: &str,
    args: &Value,
) -> Result<Value, String> {
    match method {
        "list_serial_ports" | "open_serial_port" | "close_serial_port" | "send_serial_data"
        | "read_serial_data" => hil_runtime::serial_api::dispatch(method, args),
        "read_memory_image" | "inspect_firmware_file" | "merge_hex_files" | "merge_bin_files" => {
            hil_runtime::image::dispatch(method, args)
        }
        "parse_axf_symbols"
        | "parse_firmware_functions"
        | "detect_rtos_kernel"
        | "resolve_symbol"
        | "elf_sections" => hil_runtime::symbols::dispatch(method, args),
        "render_framebuffer" => hil_runtime::pixels::render(args),
        "parse_svd_metadata" => {
            let path = PathBuf::from(
                args["custom_svd_path"]
                    .as_str()
                    .ok_or("custom_svd_path required")?,
            );
            if std::fs::metadata(&path).map_err(|e| e.to_string())?.len() > 32 * 1024 * 1024 {
                return Err("SVD exceeds 32 MiB".into());
            }
            let xml = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
            hil_runtime::svd::parse(&xml, args["peripheral_name"].as_str())
        }
        "get_debug_capabilities" => Ok(
            json!({"schema_version":1,"hili":{"major":1,"max_payload":1024,"dictionary":1,"modes":["binary","text"]},"offline_analysis":["analyze_instrumentation","analyze_crash_bundle","analyze_power_capture"],"production_instruments":{"power_supply":[],"power_measurement":[]},"instrumentation_control":false,"uart_passive_observation":true,"hardware_verified":false,"limitations":["No power drivers installed","Target ports require board validation"]}),
        ),
        "capture_lcd_framebuffer" => {
            if bridge.is_none() {
                *bridge = Some(Bridge::start()?);
            }
            let raw = bridge.as_mut().unwrap().call(
                "read_framebuffer_raw",
                args.clone(),
                Duration::from_secs(30),
            )?;
            hil_runtime::pixels::render(&raw)
        }
        "validate_hiltest" => Ok(json!({"valid":true,"plan":config::load_plan(args)?})),
        "run_hiltest" => jobs.start(args),
        "get_hiltest_status" => jobs.status(args["run_id"].as_str().ok_or("run_id required")?),
        "get_hiltest_events" => jobs.events(
            args["run_id"].as_str().ok_or("run_id required")?,
            args["after"].as_u64().unwrap_or(0),
            args["limit"].as_u64().unwrap_or(200) as usize,
        ),
        "get_hiltest_report" => jobs.report(args["run_id"].as_str().ok_or("run_id required")?),
        "stop_hiltest" => jobs.stop(args["run_id"].as_str().ok_or("run_id required")?),
        _ => {
            if bridge.is_none() {
                *bridge = Some(Bridge::start()?);
            }
            bridge.as_mut().unwrap().call(
                method,
                args.clone(),
                Duration::from_secs(if method.contains("flash") || method.contains("dump") {
                    300
                } else {
                    30
                }),
            )
        }
    }
}
fn remove_active_marker(path: &std::path::Path, run_id: &str, worker_pid: u32, worker_start: u64) {
    let Some(root) = path.parent() else { return; };
    let Ok(lock) = std::fs::OpenOptions::new().create(true).read(true).write(true)
        .open(root.join("active-run.lock")) else { return; };
    if fs2::FileExt::try_lock_exclusive(&lock).is_err() { return; }
    let Ok(bytes) = std::fs::read(path) else { return; };
    let Ok(marker) = serde_json::from_slice::<Value>(&bytes) else { return; };
    if marker["run_id"] == run_id && marker["worker_pid"] == worker_pid && marker["worker_start"] == worker_start {
        let _ = std::fs::remove_file(path);
    }
}
fn process_start_time(pid: u32) -> Option<u64> {
    let mut system = sysinfo::System::new();
    let pids = [sysinfo::Pid::from_u32(pid)];
    system.refresh_processes(sysinfo::ProcessesToUpdate::Some(&pids), true);
    system.process(sysinfo::Pid::from_u32(pid)).map(|p| p.start_time())
}
fn process_identity_alive(pid: u32, start: u64) -> bool { process_start_time(pid) == Some(start) }
fn terminate_owned_process(pid: u32, start: u64) {
    if !process_identity_alive(pid, start) { return; }
    #[cfg(windows)] {
        let mut command = std::process::Command::new("taskkill");
        command.args(["/F", "/T", "/PID", &pid.to_string()]);
        let _ = command.status();
    }
    #[cfg(not(windows))] {
        let _ = std::process::Command::new("kill").args(["-TERM", &pid.to_string()]).status();
    }
}
fn main() {
    if let Err(error) = run() {
        eprintln!("{error}");
        println!("{}", json!({"state":"ERROR","error":error}));
        std::process::exit(2);
    }
}
fn run() -> Result<(), String> {
    let arguments: Vec<_> = std::env::args().collect();
    if let Some(at) = arguments.iter().position(|a| a == "--native-supervisor") {
        let folder = PathBuf::from(arguments.get(at + 1).ok_or("Supervisor folder required")?);
        let worker_pid = arguments.get(at + 2).ok_or("Worker PID required")?.parse::<u32>().map_err(|_| "Invalid worker PID")?;
        let parent_pid = arguments.get(at + 3).ok_or("Parent PID required")?.parse::<u32>().map_err(|_| "Invalid parent PID")?;
        let parent_start = arguments.get(at + 4).ok_or("Parent start time required")?.parse::<u64>().map_err(|_| "Invalid parent start time")?;
        let worker_start = arguments.get(at + 5).ok_or("Worker start time required")?.parse::<u64>().map_err(|_| "Invalid worker start time")?;
        let mut orphaned = false;
        let mut cancel_deadline = None;
        loop {
            if !process_identity_alive(worker_pid, worker_start) { break; }
            if !process_identity_alive(parent_pid, parent_start) {
                orphaned = true;
                cancel_deadline.get_or_insert_with(|| Instant::now() + Duration::from_secs(10));
                // Publish the interruption reason before cancellation so the worker's
                // first final report cannot be mistaken for an ordinary user cancel.
                let _ = std::fs::write(folder.join("supervisor-lost"), b"service exited");
                let _ = std::fs::write(folder.join("cancel"), b"supervisor exited");
                if cancel_deadline.map_or(false, |deadline| Instant::now() >= deadline) { break; }
            }
            // status.done is not process reaping; keep the marker until the exact worker exits.
            std::thread::sleep(Duration::from_millis(100));
        }
        let mut reaped = !process_identity_alive(worker_pid, worker_start);
        if orphaned && !reaped {
            terminate_owned_process(worker_pid, worker_start);
            let reap_deadline = Instant::now() + Duration::from_secs(10);
            while process_identity_alive(worker_pid, worker_start) && Instant::now() < reap_deadline {
                std::thread::sleep(Duration::from_millis(100));
            }
            reaped = !process_identity_alive(worker_pid, worker_start);
        }
        if orphaned {
            let completed_pass = std::fs::read(folder.join("status.json")).ok()
                .and_then(|b| serde_json::from_slice::<Value>(&b).ok())
                .map_or(false, |s| s["done"] == true && (s["state"] == "PASS" || s["state"] == "INTERRUPTED"));
            if !completed_pass {
                let _ = hil_runtime::report::interrupted(&folder, if reaped {
                    "HIL service exited; worker reaped, hardware outcome is unknown"
                } else {
                    "HIL service exited; worker did not terminate before deadline; hardware outcome is unknown"
                });
            }
        }
        if reaped {
            remove_active_marker(&folder.parent().unwrap_or(&folder).join("active-run.json"),
                folder.file_name().and_then(|n| n.to_str()).unwrap_or(""), worker_pid, worker_start);
        }
        return Ok(());
    }
    if let Some(at) = arguments.iter().position(|a| a == "--native-run") {
        let folder = PathBuf::from(arguments.get(at + 1).ok_or("Worker folder required")?);
        let ready = folder.join("supervisor-ready");
        let ready_deadline = Instant::now() + Duration::from_secs(5);
        while !ready.is_file() && Instant::now() < ready_deadline {
            std::thread::sleep(Duration::from_millis(20));
        }
        if !ready.is_file() {
            let _ = hil_runtime::report::interrupted(&folder, "Lifecycle supervisor did not become ready before worker start");
            std::process::exit(2);
        }
        let plan: Value = serde_json::from_slice(
            &std::fs::read(folder.join("plan.json")).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        let result = Worker::new(plan, folder)?.run()?;
        std::process::exit(match result.as_str() {
            "PASS" => 0,
            "FAIL" => 1,
            "CANCELLED" => 3,
            _ => 2,
        });
    }
    if arguments
        .iter()
        .any(|a| ["--file", "--mode", "--validate", "--help"].contains(&a.as_str()))
    {
        if arguments.contains(&"--help".into()) {
            println!("hil-daemon --mode hiltest --file TEST --report-dir DIR [--validate] [--set NAME=VALUE]");
            return Ok(());
        }
        let mut args = json!({});
        let mut root = PathBuf::from("reports");
        let mut validate = false;
        let mut i = 1;
        let mut replay = None;
        while i < arguments.len() {
            let key = &arguments[i];
            if key == "--validate" {
                validate = true;
                i += 1;
                continue;
            }
            let value = arguments.get(i + 1).ok_or("Missing argument value")?;
            match key.as_str() {
                "--file" => args["file"] = json!(value),
                "--report-dir" => root = PathBuf::from(value),
                "--mode" if value == "hiltest" => {}
                "--set" => {
                    let (k, v) = value.split_once('=').ok_or("--set requires NAME=VALUE")?;
                    if args["parameters"].is_null() {
                        args["parameters"] = json!({});
                    }
                    args["parameters"][k] = json!(v);
                }
                "--replay-events" => replay = Some(value.clone()),
                _ => return Err(format!("Unknown CLI argument: {key}")),
            }
            i += 2;
        }
        if validate {
            println!("{}", json!({"valid":true,"plan":config::load_plan(&args)?}));
            return Ok(());
        }
        if let Some(path) = replay {
            let report =
                hil_runtime::replay::run(&config::load_plan(&args)?, &PathBuf::from(path), &root)?;
            println!("{report}");
            std::process::exit(if report["state"] == "PASS" { 0 } else { 1 });
        }
        let jobs = Jobs::new(root);
        let mut state = jobs.start(&args)?;
        println!("{state}");
        let _ = std::io::stdout().flush();
        let id = state["run_id"].as_str().unwrap().to_string();
        while state["done"] != true {
            std::thread::sleep(Duration::from_millis(100));
            state = jobs.status(&id)?;
        }
        println!("{state}");
        std::process::exit(match state["state"].as_str().unwrap_or("ERROR") {
            "PASS" => 0,
            "FAIL" => 1,
            "CANCELLED" => 3,
            _ => 2,
        });
    }
    let jobs = Jobs::new(report_root());
    let mut bridge = None;
    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout();
    for line in stdin.lock().lines() {
        let line = line.map_err(|e| e.to_string())?;
        if line.len() > 4 * 1024 * 1024 {
            return Err("RPC request limit".into());
        }
        let request: Value = match serde_json::from_str(&line) {
            Ok(v) => v,
            Err(e) => {
                writeln!(stdout,"{}",json!({"jsonrpc":"2.0","id":null,"error":{"code":-32700,"message":e.to_string()}})).map_err(|e|e.to_string())?;
                stdout.flush().map_err(|e| e.to_string())?;
                continue;
            }
        };
        if request["id"].is_null() {
            continue;
        }
        let id = request["id"].clone();
        let method = request["method"].as_str().unwrap_or("");
        let params = request.get("params").cloned().unwrap_or(json!({}));
        let result = match method {
            "initialize" => Ok(
                json!({"protocolVersion":params["protocolVersion"].as_str().unwrap_or("2024-11-05"),"capabilities":{"tools":{"listChanged":false}},"serverInfo":{"name":"embedded-hil-debugger","version":env!("CARGO_PKG_VERSION")}}),
            ),
            "ping" => Ok(json!({})),
            "shutdown" | "exit" => Ok(json!("ok")),
            "tools/list" | "list_tools" => {
                let here = std::env::current_exe().map_err(|e| e.to_string())?;
                let candidates = [
                    here.parent().unwrap().join("mcp-tools.json"),
                    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
                        .parent()
                        .unwrap()
                        .join("daemon/mcp-tools.json"),
                ];
                if let Some(path) = candidates.iter().find(|p| p.is_file()) {
                    serde_json::from_slice(&std::fs::read(path).map_err(|e| e.to_string())?)
                        .map_err(|e| e.to_string())
                } else {
                    dispatch(&jobs, &mut bridge, method, &params)
                }
            }
            "tools/call" | "call_tool" => {
                let name = params["name"].as_str().unwrap_or("");
                let args = params.get("arguments").cloned().unwrap_or(json!({}));
                Ok(match dispatch(&jobs, &mut bridge, name, &args) {
                    Ok(value) => {
                        json!({"content":[{"type":"text","text":value.to_string()}],"isError":false})
                    }
                    Err(error) => json!({"content":[{"type":"text","text":error}],"isError":true}),
                })
            }
            _ => dispatch(&jobs, &mut bridge, method, &params),
        };
        let response = match result {
            Ok(result) => json!({"jsonrpc":"2.0","id":id,"result":result}),
            Err(message) => {
                json!({"jsonrpc":"2.0","id":id,"error":{"code":-32603,"message":message}})
            }
        };
        writeln!(stdout, "{response}").map_err(|e| e.to_string())?;
        stdout.flush().map_err(|e| e.to_string())?;
        if method == "shutdown" || method == "exit" {
            break;
        }
    }
    hil_runtime::serial_api::close_all();
    Ok(())
}
