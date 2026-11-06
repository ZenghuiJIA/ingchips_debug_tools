use crate::{
    bridge::{hide, Bridge},
    report::{atomic_json, summarize, write_reports},
    serial::SerialSession,
    stream::HilObserver,
};
use hil_debug_core::{
    capture::{hex, unhex, wall_time_ms},
    protocol::{Decoder, Protocol},
};
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashSet};
use std::io::{BufRead, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
static RUN_SEQUENCE: AtomicU64 = AtomicU64::new(1);
pub fn report_root() -> PathBuf {
    std::env::var("HIL_REPORT_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            PathBuf::from(std::env::var("LOCALAPPDATA").unwrap_or(".".into()))
                .join("AI-HIL-Debugger/reports")
        })
}
pub struct Jobs {
    pub root: PathBuf,
}
/// Validated immutable plan plus exclusive admission held through worker reaping.
pub struct PreparedRun {
    plan: Value,
    root: PathBuf,
    reservation: std::fs::File,
}
impl PreparedRun {
    pub fn plan(&self) -> &Value { &self.plan }
}
impl Jobs {
    pub fn new(root: PathBuf) -> Self {
        Self { root }
    }
    fn folder(&self, id: &str) -> Result<PathBuf, String> {
        if id.is_empty()
            || id.len() > 128
            || !id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-')
        {
            return Err("Invalid run_id".into());
        }
        Ok(self.root.join(id))
    }
    /// Reserve before handing terminals to HIL. Dropping on a handoff failure releases admission.
    pub fn prepare(&self, args: &Value) -> Result<PreparedRun, String> {
        let plan = crate::config::load_plan(args)?;
        std::fs::create_dir_all(&self.root).map_err(|e| e.to_string())?;
        let root = self.root.canonicalize().map_err(|e| e.to_string())?;
        let reservation = std::fs::OpenOptions::new().create(true).read(true).write(true)
            .open(root.join("active-run.lock")).map_err(|e| e.to_string())?;
        fs2::FileExt::try_lock_exclusive(&reservation)
            .map_err(|_| "A HIL run is active or being submitted in this report directory".to_string())?;
        // Inspect/remove markers only after admission is reserved.
        let active = root.join("active-run.json");
        if let Ok(bytes) = std::fs::read(&active) {
            if let Ok(marker) = serde_json::from_slice::<Value>(&bytes) {
                let alive = marker["worker_pid"].as_u64().and_then(|pid| marker["worker_start"].as_u64()
                    .map(|start| process_identity_alive(pid as u32, start))).unwrap_or(false);
                if alive { return Err("A previous HIL worker is still active; refusing overlap".into()); }
                let _ = std::fs::remove_file(&active);
            }
        }
        Ok(PreparedRun { plan, root, reservation })
    }
    pub fn start(&self, args: &Value) -> Result<Value, String> {
        self.start_prepared(self.prepare(args)?)
    }
    pub fn start_prepared(&self, prepared: PreparedRun) -> Result<Value, String> {
        if self.root.canonicalize().map_err(|e| e.to_string())? != prepared.root {
            return Err("Prepared HIL run belongs to a different report directory".into());
        }
        let PreparedRun { plan, reservation, .. } = prepared;
        let id = format!(
            "{}-{}-{}",
            wall_time_ms(),
            std::process::id(),
            RUN_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        );
        let folder = self.folder(&id)?;
        std::fs::create_dir(&folder).map_err(|e| e.to_string())?;
        atomic_json(&folder.join("plan.json"), &plan)?;
        atomic_json(
            &folder.join("status.json"),
            &json!({"run_id":id,"state":"QUEUED","done":false,"report_dir":folder,"backend":"rust"}),
        )?;
        let mut command = Command::new(native_executable()?);
        command
            .arg("--native-run")
            .arg(&folder)
            .arg("--supervisor-pid")
            .arg(std::process::id().to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        hide(&mut command);
        let mut child = command.spawn().map_err(|e| e.to_string())?;
        let worker_pid = child.id();
        let worker_start = process_start_time(worker_pid).ok_or_else(|| {
            crate::bridge::terminate(&mut child);
            "Unable to identify native HIL worker process".to_string()
        })?;
        if let Err(error) = atomic_json(&self.root.join("active-run.json"), &json!({
            "run_id": id, "worker_pid": worker_pid, "worker_start": worker_start
        })) {
            crate::bridge::terminate(&mut child);
            let _ = std::fs::remove_file(self.root.join("active-run.json"));
            return Err(error);
        }
        let exe = match native_executable() {
            Ok(exe) => exe,
            Err(error) => {
                crate::bridge::terminate(&mut child);
                let _ = std::fs::remove_file(self.root.join("active-run.json"));
                return Err(error);
            }
        };
        let parent_start = process_start_time(std::process::id()).ok_or_else(|| {
            crate::bridge::terminate(&mut child);
            let _ = std::fs::remove_file(self.root.join("active-run.json"));
            "Unable to identify HIL supervisor process".to_string()
        })?;
        let mut supervisor = Command::new(exe);
        supervisor.arg("--native-supervisor").arg(&folder)
            .arg(worker_pid.to_string()).arg(std::process::id().to_string())
            .arg(parent_start.to_string()).arg(worker_start.to_string())
            .stdin(Stdio::null()).stdout(Stdio::null()).stderr(Stdio::null());
        hide(&mut supervisor);
        if supervisor.spawn().is_err() {
            crate::bridge::terminate(&mut child);
            let _ = std::fs::remove_file(self.root.join("active-run.json"));
            return Err("Unable to start owned HIL lifecycle supervisor".into());
        }
        if let Err(error) = atomic_json(&folder.join("supervisor-ready"), &json!({
            "worker_pid": worker_pid, "worker_start": worker_start
        })) {
            crate::bridge::terminate(&mut child);
            let _ = std::fs::remove_file(self.root.join("active-run.json"));
            return Err(error);
        }
        let output = folder.clone();
        let active_marker = self.root.join("active-run.json");
        let ready_marker = folder.join("supervisor-ready");
        let marker_run_id = id.clone();
        std::thread::spawn(move || {
            let _reservation = reservation; // Keep exclusive admission until this owned child is reaped.
            let started = Instant::now();
            let mut cancelled = None;
            let mut observed_deadline = None;
            let mut operation_end = Instant::now() + Duration::from_secs(60);
            loop {
                if child.try_wait().ok().flatten().is_some() {
                    break;
                }
                let state = std::fs::read(output.join("status.json"))
                    .ok()
                    .and_then(|b| serde_json::from_slice::<Value>(&b).ok());
                if output.join("cancel").exists() && cancelled.is_none() {
                    cancelled = Some(Instant::now());
                }
                let deadline = state.as_ref().and_then(|s| s["deadline_ms"].as_u64());
                if deadline.is_some() && deadline != observed_deadline {
                    operation_end = Instant::now()
                        + Duration::from_millis(
                            deadline
                                .unwrap()
                                .saturating_sub(wall_time_ms())
                                .saturating_add(2000),
                        );
                    observed_deadline = deadline;
                }
                let expired = Instant::now() > operation_end
                    || (deadline.is_none() && started.elapsed() > Duration::from_secs(60));
                let flashing = state.as_ref().map_or(false, |s| {
                    s["operation_kind"] == "flash_firmware" || s["phase"] == "target_stop"
                });
                if expired
                    || (!flashing
                        && cancelled
                            .map_or(false, |t: Instant| t.elapsed() > Duration::from_secs(10)))
                {
                    crate::bridge::terminate(&mut child);
                    let _ = crate::report::interrupted(
                        &output,
                        "Worker deadline exceeded; hardware outcome unknown",
                    );
                    break;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
            let state = std::fs::read(output.join("status.json"))
                .ok()
                .and_then(|b| serde_json::from_slice::<Value>(&b).ok());
            if state.as_ref().map_or(true, |s| s["done"] != true) {
                let _ = crate::report::interrupted(
                    &output,
                    "Native worker exited before completing report",
                );
            }
            remove_active_marker(&active_marker, &marker_run_id, worker_pid, worker_start);
            let _ = std::fs::remove_file(ready_marker);
        });
        self.status(&id)
    }
    pub fn status(&self, id: &str) -> Result<Value, String> {
        let path = self.folder(id)?.join("status.json");
        for attempt in 0..20 {
            match std::fs::read(&path)
                .map_err(|e| e.to_string())
                .and_then(|data| serde_json::from_slice::<Value>(&data).map_err(|e| e.to_string()))
            {
                Ok(mut value) => {
                    let flash = self.folder(id)?.join("flash-state.json");
                    if let Ok(bytes) = std::fs::read(flash) {
                        if let Ok(state) = serde_json::from_slice::<Value>(&bytes) {
                            value["flash_state"] = state;
                        }
                    }
                    if value["done"] != true && self.folder(id)?.join("cancel").exists() {
                        value["state"] = json!("STOPPING");
                        value["cancel_detail"] = json!(if value["operation_kind"]
                            == "flash_firmware"
                        {
                            "Waiting for current erase/page algorithm boundary; subsequent writes are blocked"
                        } else if value["phase"] == "target_stop" {
                            "Waiting for firmware STOPPED acknowledgement"
                        } else {
                            "Cancellation pending cleanup"
                        });
                    }
                    return Ok(value);
                }
                Err(e) if attempt == 19 => return Err(e),
                _ => std::thread::sleep(Duration::from_millis(10)),
            }
        }
        unreachable!()
    }
    pub fn stop(&self, id: &str) -> Result<Value, String> {
        let mut status = self.status(id)?;
        if status["done"] != true {
            std::fs::write(self.folder(id)?.join("cancel"), b"").map_err(|e| e.to_string())?;
            status["state"] = json!("STOPPING");
        }
        Ok(status)
    }
    pub fn report(&self, id: &str) -> Result<Value, String> {
        if self.status(id)?["done"] != true {
            return Err("Run has not finished".into());
        }
        serde_json::from_slice(
            &std::fs::read(self.folder(id)?.join("report.json")).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())
    }
    pub fn events(&self, id: &str, after: u64, limit: usize) -> Result<Value, String> {
        let path = self.folder(id)?.join("events.jsonl");
        let mut out = vec![];
        let mut cursor = after;
        if path.exists() {
            for line in
                std::io::BufReader::new(std::fs::File::open(path).map_err(|e| e.to_string())?)
                    .lines()
            {
                let Ok(line) = line else {
                    break;
                };
                let Ok(value) = serde_json::from_str::<Value>(&line) else {
                    break;
                };
                if value["seq"].as_u64().unwrap_or(0) > after {
                    cursor = value["seq"].as_u64().unwrap();
                    out.push(value);
                    if out.len() >= limit.clamp(1, 1000) {
                        break;
                    }
                }
            }
        }
        Ok(json!({"events":out,"cursor":cursor}))
    }
}
fn remove_active_marker(path: &std::path::Path, run_id: &str, worker_pid: u32, worker_start: u64) {
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

pub fn native_executable() -> Result<PathBuf, String> {
    let current = std::env::current_exe().map_err(|e| e.to_string())?;
    if current
        .file_name()
        .unwrap_or_default()
        .to_string_lossy()
        .contains("hil-native")
        || current
            .file_name()
            .unwrap_or_default()
            .to_string_lossy()
            .contains("hil-daemon")
    {
        return Ok(current);
    }
    let here = current.parent().unwrap();
    for p in [
        here.join("hil-native.exe"),
        here.join("bin/hil-native.exe"),
        here.join("bin/hil-daemon-x86_64-pc-windows-msvc.exe"),
        here.join("hil-daemon-x86_64-pc-windows-msvc.exe"),
    ] {
        if p.is_file() {
            return Ok(p);
        }
    }
    Err("Native HIL executable missing".into())
}
struct Log {
    file: std::fs::File,
    raw: std::fs::File,
    seq: u64,
    started: Instant,
    error: Option<String>,
    size: usize,
}
impl Log {
    fn emit(&mut self, kind: &str, mut data: Value) -> Result<(), String> {
        self.seq += 1;
        data["seq"] = json!(self.seq);
        data["kind"] = json!(kind);
        data["time"] = json!(wall_time_ms() as f64 / 1000.);
        data["elapsed_ms"] = json!(self.started.elapsed().as_secs_f64() * 1000.);
        let mut line = serde_json::to_vec(&data).map_err(|e| e.to_string())?;
        line.push(b'\n');
        self.file.write_all(&line).map_err(|e| e.to_string())
    }
    fn rx(&mut self, port: &str, data: &[u8]) {
        self.size += data.len();
        let result = if self.size > 512 * 1024 * 1024 {
            Err("Serial log limit exceeded".into())
        } else {
            self.raw.write_all(data).map_err(|e|e.to_string()).and_then(|_|self.emit("serial",json!({"schema_version":1,"session_id":port,"port":port,"direction":"RX","data":hex(data),"encoding":"hex"})))
        };
        if let Err(e) = result {
            self.error = Some(e);
        }
    }
}
struct InstrumentCapture {
    decoder: hil_debug_core::instrumentation::Decoder,
    events: Vec<Value>,
    errors: Vec<Value>,
    device_id: String,
    session_id: String,
}
pub struct Worker {
    plan: Value,
    folder: PathBuf,
    started: Instant,
    wall: f64,
    status: Value,
    log: Arc<Mutex<Log>>,
    sessions: BTreeMap<String, Arc<SerialSession>>,
    cursors: BTreeMap<String, u64>,
    marks: BTreeMap<String, f64>,
    rows: Vec<Value>,
    bridge: Option<Bridge>,
    used: HashSet<String>,
    uncertain: HashSet<String>,
    leases: Vec<std::fs::File>,
    instrumentation: Arc<Mutex<BTreeMap<String, InstrumentCapture>>>,
    instrumentation_results: BTreeMap<String, Value>,
    target_may_run: bool,
}
impl Worker {
    pub fn new(plan: Value, folder: PathBuf) -> Result<Self, String> {
        let started = Instant::now();
        let wall = wall_time_ms() as f64 / 1000.;
        let log = Log {
            file: std::fs::File::create(folder.join("events.jsonl")).map_err(|e| e.to_string())?,
            raw: std::fs::File::create(folder.join("serial.log")).map_err(|e| e.to_string())?,
            seq: 0,
            started,
            error: None,
            size: 0,
        };
        let status = json!({"run_id":folder.file_name().unwrap().to_string_lossy(),"state":"RUNNING","done":false,"report_dir":folder,"backend":"rust","current_step":null,"loop":0,"deadline_ms":wall_time_ms()+60000});
        Ok(Self {
            plan,
            folder,
            started,
            wall,
            status,
            log: Arc::new(Mutex::new(log)),
            sessions: BTreeMap::new(),
            cursors: BTreeMap::new(),
            marks: BTreeMap::new(),
            rows: vec![],
            bridge: None,
            used: HashSet::new(),
            uncertain: HashSet::new(),
            leases: vec![],
            instrumentation: Arc::new(Mutex::new(BTreeMap::new())),
            instrumentation_results: BTreeMap::new(),
            target_may_run: false,
        })
    }
    fn check(&self, end: Instant) -> Result<(), String> {
        if self.folder.join("cancel").exists() {
            return Err("CANCELLED".into());
        }
        if Instant::now() >= end
            || self.started.elapsed().as_millis()
                >= self.plan["timeout_ms"].as_u64().unwrap() as u128
        {
            return Err("TIMEOUT: execution deadline exceeded".into());
        }
        if let Some(e) = self.log.lock().unwrap().error.clone() {
            return Err(e);
        }
        Ok(())
    }
    fn emit(&self, kind: &str, data: Value) -> Result<(), String> {
        self.log.lock().unwrap().emit(kind, data)
    }
    fn publish(&mut self) -> Result<(), String> {
        self.status["event_seq"] = json!(self.log.lock().unwrap().seq);
        atomic_json(&self.folder.join("status.json"), &self.status)
    }
    fn rpc(&mut self, name: &str, args: Value, end: Instant) -> Result<Value, String> {
        self.check(end)?;
        if self.bridge.is_none() {
            self.bridge = Some(Bridge::start()?);
            let probes = self.plan["_resources"]["probes"].clone();
            self.bridge.as_mut().unwrap().call(
                "begin_probe_scope",
                json!({"probe_ids":probes}),
                end.saturating_duration_since(Instant::now()),
            )?;
        }
        self.bridge.as_mut().unwrap().call(
            name,
            args,
            end.saturating_duration_since(Instant::now()),
        )
    }
    fn open_session(
        &self,
        port: &str,
        baud: u64,
        options: &Value,
    ) -> Result<Arc<SerialSession>, String> {
        let log = self.log.clone();
        let key = port.to_string();
        let collectors = self.instrumentation.clone();
        SerialSession::open_options(
            port,
            baud as u32,
            Some(Arc::new(move |data, stamp| {
                log.lock().unwrap().rx(&key, data);
                if let Some(collector) = collectors.lock().unwrap().get_mut(&key) {
                    if collector.events.len() >= 10000 || collector.errors.len() >= 1000 {
                        if collector.errors.len() <= 1000 {
                            collector.errors.push(json!({"code":"CAPTURE_LIMIT","reason":"Instrumentation window exceeds 10000 events/1000 errors"}));
                        }
                    } else {
                        match collector.decoder.feed(data, stamp) {
                            Ok(result) => {
                                collector
                                    .events
                                    .extend(result.events.into_iter().map(|e| json!(e)));
                                collector.errors.extend(result.errors);
                            }
                            Err(error) => collector
                                .errors
                                .push(json!({"code":"DECODE_ERROR","reason":error})),
                        }
                    }
                }
            })),
            options,
        )
    }
    fn reopen_session(&mut self, port: &str, baud: u64) -> Result<(), String> {
        let session = self.open_session(port, baud, &self.serial_options(port))?;
        self.cursors
            .insert(port.into(), session.journal.lock().unwrap().end);
        self.marks.insert(port.into(), session.elapsed_ms());
        self.sessions.insert(port.into(), session);
        Ok(())
    }
    fn serial_options(&self, port: &str) -> Value {
        flatten(self.plan["steps"].as_array().unwrap()).into_iter()
            .find(|s| s["enabled"] != false && s["params"]["port_name"] == port && !s["params"]["pin_reset"].is_null())
            .map(|s| { let p = &s["params"]["pin_reset"];
                json!({"initial_dtr":!p["reset_asserted_dtr"].as_bool().unwrap(),"initial_rts":!p["boot_asserted_rts"].as_bool().unwrap()})
            }).unwrap_or(json!({}))
    }
    fn prepare(&mut self) -> Result<(), String> {
        self.acquire_probe_leases()?;
        let ports = self.plan["_resources"]["ports"]
            .as_object()
            .unwrap()
            .clone();
        for (port, baud) in ports {
            self.check(self.started + Duration::from_secs(60))?;
            let options = self.serial_options(&port);
            let session = self.open_session(&port, baud.as_u64().unwrap(), &options)?;
            self.cursors
                .insert(port.clone(), session.journal.lock().unwrap().end);
            self.marks.insert(port.clone(), session.elapsed_ms());
            self.sessions.insert(port, session);
            self.target_may_run = true;
        }
        self.emit(
            "capture.ready",
            json!({"ports":self.sessions.keys().collect::<Vec<_>>()}),
        )
    }
    fn acquire_probe_leases(&mut self) -> Result<(), String> {
        let probes = self.plan["_resources"]["probes"]
            .as_array()
            .cloned()
            .unwrap_or_default();
        let folder = std::env::temp_dir().join("ai-hil-native-leases");
        std::fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
        for probe in probes {
            let id = probe.as_str().ok_or("Invalid probe id")?;
            use sha2::{Digest, Sha256};
            let digest = Sha256::digest(id.as_bytes());
            let path = folder.join(format!("{:x}.lock", digest));
            let file = std::fs::OpenOptions::new()
                .create(true)
                .read(true)
                .write(true)
                .open(path)
                .map_err(|e| e.to_string())?;
            if fs2::FileExt::try_lock_exclusive(&file).is_err() {
                return Err(format!("Probe {id} is occupied by another operation"));
            }
            self.leases.push(file);
        }
        Ok(())
    }
    fn mark(&mut self) -> Result<(), String> {
        for (port, s) in &self.sessions {
            self.cursors
                .insert(port.clone(), s.journal.lock().unwrap().end);
            self.marks.insert(port.clone(), s.elapsed_ms());
        }
        self.emit("observation.mark", json!({}))
    }
    fn run_ing_flash(&mut self, p: &Value, end: Instant) -> Result<Value, String> {
        let end = end
            .min(self.started + Duration::from_millis(self.plan["timeout_ms"].as_u64().unwrap()));
        let port = p["port_name"]
            .as_str()
            .ok_or("ING port_name required")?
            .to_string();
        let baud = p["baud_rate"].as_u64().unwrap_or(115200);
        let req = crate::ing::hil_request(p, self.status["run_id"].as_str().unwrap_or("hil"));
        if let Some(session) = self.sessions.remove(&port) {
            let _ = session.close();
        }
        let cancel_path = self.folder.join("cancel");
        let cancel_probe = cancel_path.clone();
        let options = crate::ing::FlashOptions {
            cancelled: Arc::new(move || cancel_probe.exists() || Instant::now() >= end),
            pin_reset: if p["pin_reset"].is_null() {
                None
            } else {
                Some(serde_json::from_value(p["pin_reset"].clone()).map_err(|e| e.to_string())?)
            },
            suppress_launch: true,
        };
        self.emit(
            "ing.started",
            json!({"port":port,"file":req.ini_path,"cancellation":"page_or_sector_boundary"}),
        )?;
        let result = crate::ing::run_with_options(
            &req,
            &options,
            &|stage, file, done, total, pct, speed, message| {
                let _ = self.emit("ing.progress", json!({"stage":stage,"file":file,"done":done,"total":total,"percent":pct,"speed_kbps":speed,"message":message}));
            },
        );
        let state = if result.is_ok() {
            "COMPLETED"
        } else if result
            .as_ref()
            .err()
            .map_or(false, |e| e.starts_with("CANCELLED"))
        {
            "CANCELLED"
        } else {
            "ERROR"
        };
        let stopped = state == "COMPLETED"
            || result.as_ref().err().map_or(false, |e| {
                e.contains("acknowledged page/sector boundary")
                    && !e.contains("before ISP handshake")
            });
        let value = json!({"state":state,"erase_program_stopped":stopped,"target_halted":false,"application_launched":false,"firmware_complete":state == "COMPLETED","error":result.as_ref().err()});
        self.status["flash_state"] = value.clone();
        atomic_json(&self.folder.join("flash-state.json"), &value)?;
        self.status["target_state"] = json!(if stopped { "ISP_IDLE" } else { "UNKNOWN" });
        self.target_may_run = !stopped;
        self.emit("flash.state", value.clone())?;
        if state != "ERROR" {
            self.reopen_session(&port, baud)?;
        }
        if state == "CANCELLED" {
            return Err(if self.folder.join("cancel").exists() {
                "CANCELLED"
            } else {
                "TIMEOUT: ING download deadline exceeded at command boundary"
            }
            .into());
        }
        result.map(|_| value)
    }
    fn stop_target(&mut self) -> Result<bool, String> {
        self.status["phase"] = json!("target_stop");
        let Some(cfg) = self.plan["stop"].as_object() else {
            self.status["stop_confirmed"] = json!(false);
            self.status["target_state"] = json!("UNKNOWN");
            self.status["stop_detail"] = json!("No stop contract configured");
            return Err("STOP_UNCONFIRMED: no stop contract configured".into());
        };
        let port = cfg["port_name"].as_str().ok_or("stop.port_name missing")?;
        let session = self
            .sessions
            .get(port)
            .ok_or("STOP_UNCONFIRMED: stop UART is not open")?
            .clone();
        let cursor = session.journal.lock().unwrap().end;
        let identity = session.capture.lock().unwrap().session_id.clone();
        let mut ack =
            crate::stop::StopAck::new(identity.clone(), cursor, &Value::Object(cfg.clone()))?;
        let bytes = crate::stop::request_bytes(&Value::Object(cfg.clone()))?;
        session.write(&bytes)?;
        self.emit(
            "device.stop.requested",
            json!({"port":port,"session_id":identity,"data":hex(&bytes),"cursor":cursor}),
        )?;
        let deadline =
            Instant::now() + Duration::from_millis(cfg["timeout_ms"].as_u64().unwrap_or(5000));
        crate::stop::wait_ack(deadline, || {
            ack.poll(
                &session.capture.lock().unwrap().session_id,
                &session.journal.lock().unwrap(),
                session.running.load(Ordering::SeqCst),
            )
        })?;
        self.status["stop_confirmed"] = json!(true);
        self.status["target_state"] = json!("STOPPED");
        self.status["stop_detail"] = json!("STOPPED acknowledgement received after request");
        self.emit(
            "device.stopped",
            json!({"port":port,"session_id":identity,"ack_pattern":cfg["ack_pattern"].clone()}),
        )?;
        Ok(true)
    }
    fn action(&mut self, step: &Value, end: Instant) -> Result<Value, String> {
        let p = &step["params"];
        let a = step["action"].as_str().unwrap();
        let port = p["port_name"].as_str().unwrap_or("");
        if matches!(
            a,
            "reset_target"
                | "serial_send"
                | "serial_wait_match"
                | "hil_observe"
                | "protocol_request"
                | "instrumentation_start"
        ) {
            self.target_may_run = true;
            self.status["target_state"] = json!("UNKNOWN");
        }
        match a {
            "delay" => {
                let until =
                    Instant::now() + Duration::from_millis(p["delay_ms"].as_u64().unwrap_or(500));
                while Instant::now() < until {
                    self.check(end)?;
                    std::thread::sleep(Duration::from_millis(5));
                }
                Ok(json!({}))
            }
            "serial_open" => Ok(json!({"port":port,"capturing":true})),
            "reset_target"
                if p["reset_method"].as_str().unwrap_or("swd_soft_reset") != "swd_soft_reset" =>
            {
                self.mark()?; // BOOT may arrive before the reset operation returns.
                let config: crate::reset::PinReset =
                    serde_json::from_value(p["pin_reset"].clone()).map_err(|e| e.to_string())?;
                let session = self
                    .sessions
                    .get(port)
                    .ok_or("Reset UART is not open")?
                    .clone();
                let cancel = self.folder.join("cancel");
                crate::reset::execute(
                    session.as_ref(),
                    &config,
                    p["reset_method"] == "bootloader_reset",
                    end,
                    || cancel.exists(),
                )?;
                self.emit("target.reset",json!({"port":port,"method":p["reset_method"],"profile_id":config.profile_id,"reset_released":true,"boot_entry_confirmed":false}))?;
                Ok(
                    json!({"status":"control_sequence_completed","boot_entry_confirmed":false,"next_step":"assert target bootloader/startup response"}),
                )
            }
            "instrumentation_start" => {
                let s = self.sessions.get(port).ok_or("Serial not open")?;
                let session = s.capture.lock().unwrap().session_id.clone();
                let mut collectors = self.instrumentation.lock().unwrap();
                if collectors.contains_key(port) {
                    return Err("Instrumentation window already open".into());
                }
                collectors.insert(
                    port.into(),
                    InstrumentCapture {
                        decoder: hil_debug_core::instrumentation::Decoder::new(
                            p["mode"] == "text",
                            1000.,
                        )?,
                        events: vec![],
                        errors: vec![],
                        device_id: p["device_id"].as_str().unwrap().into(),
                        session_id: session,
                    },
                );
                drop(collectors);
                self.instrumentation_results.remove(port);
                self.emit(
                    "instrumentation.started",
                    json!({"port":port,"control":"passive","firmware_state":"UNKNOWN"}),
                )?;
                Ok(
                    json!({"state":"OBSERVING","control":"passive","firmware_recording_confirmed":false}),
                )
            }
            "instrumentation_stop" => {
                let mut collected = self
                    .instrumentation
                    .lock()
                    .unwrap()
                    .remove(port)
                    .ok_or("Instrumentation window not open")?;
                if let Some(partial) = collected.decoder.finish() {
                    collected.errors.push(partial);
                }
                let data = json!({"events":collected.events,"errors":collected.errors,"device_id":collected.device_id,
                    "session_id":collected.session_id,"control":"passive","firmware_state":"UNKNOWN","source_kind":"hardware_capture"});
                let name = format!("instrumentation-{}.json", step["id"].as_str().unwrap());
                atomic_json(&self.folder.join(&name), &data)?;
                self.instrumentation_results
                    .insert(port.into(), data.clone());
                self.emit("instrumentation.finished",json!({"port":port,"artifact":name,"errors":data["errors"].as_array().unwrap().len()}))?;
                Ok(
                    json!({"state":"OBSERVATION_CLOSED","artifact":name,"firmware_recording_stopped":false}),
                )
            }
            "instrumentation_assert" => {
                if self.instrumentation.lock().unwrap().contains_key(port) {
                    let mut stop = step.clone();
                    stop["action"] = json!("instrumentation_stop");
                    self.action(&stop, end)?;
                }
                let mut data = self
                    .instrumentation_results
                    .get(port)
                    .cloned()
                    .ok_or("No collected instrumentation window")?;
                data["budgets"] = p["budgets"].clone();
                // Offline analysis receives bytes only, never acquires a probe scope.
                let mut analyzer = Bridge::start()?;
                let report = analyzer.call(
                    "analyze_instrumentation",
                    data,
                    end.saturating_duration_since(Instant::now()),
                )?;
                atomic_json(
                    &self
                        .folder
                        .join(format!("analysis-{}.json", step["id"].as_str().unwrap())),
                    &report,
                )?;
                match report["analysis_status"].as_str().unwrap_or("ERROR") {
                    "PASS" => Ok(report),
                    "FAIL" => Err(format!(
                        "FAIL: instrumentation budget exceeded; analysis_status=FAIL"
                    )),
                    status => Err(format!(
                        "analysis_status={status}: incomplete or invalid instrumentation evidence"
                    )),
                }
            }
            "serial_send" => {
                let s = self.sessions.get(port).ok_or("Serial not open")?;
                self.cursors
                    .insert(port.into(), s.journal.lock().unwrap().end);
                self.marks.insert(port.into(), s.elapsed_ms());
                let text = p["send_data"].as_str().unwrap_or("");
                let mut bytes = if p["send_format"] == "hex" {
                    unhex(text)?
                } else {
                    text.as_bytes().into()
                };
                bytes.extend_from_slice(match p["send_ending"].as_str().unwrap_or("none") {
                    "lf" => b"\n",
                    "crlf" => b"\r\n",
                    _ => b"",
                });
                let count = if let Some(ms) = p["character_delay_ms"].as_u64() {
                    if ms > 0 {
                        // Some USB-UART bridges burst a whole line faster than
                        // a small target RX FIFO can drain it. Pacing bytes from
                        // the host keeps long commands intact.
                        send_paced(&bytes, ms, |part| s.write(part), || self.check(end))?
                    } else {
                        s.write(&bytes)?
                    }
                } else {
                    s.write(&bytes)?
                };
                self.emit(
                    "serial",
                    json!({"port":port,"direction":"TX","data":hex(&bytes)}),
                )?;
                Ok(json!({"bytes_sent":count}))
            }
            "serial_wait_match" | "hil_observe" => self.observe(step, end),
            "protocol_request" => {
                let spec: Protocol =
                    serde_json::from_value(p["protocol"].clone()).map_err(|e| e.to_string())?;
                let bytes = spec.encode(p["values"].as_object().unwrap())?;
                let identity = format!("{port}:{}:{}", p["protocol"], p["expected"]);
                if self.uncertain.contains(port) || !self.used.insert(identity) {
                    return Err("Request identity already used/outcome unknown".into());
                }
                self.uncertain.insert(port.into());
                let s = self.sessions.get(port).ok_or("Serial not open")?.clone();
                let mut cursor = s.journal.lock().unwrap().end;
                let mut decoder = Decoder::new(spec)?;
                self.check(end)?;
                s.write(&bytes)?;
                self.emit(
                    "serial",
                    json!({"port":port,"direction":"TX","data":hex(&bytes)}),
                )?;
                loop {
                    self.check(end)?;
                    let (chunks, next) = s.journal.lock().unwrap().read(cursor)?;
                    cursor = next;
                    for chunk in chunks {
                        for frame in decoder.feed(&chunk.data, chunk.elapsed_ms)? {
                            self.emit("protocol.frame", json!({"port":port,"frame":frame}))?;
                            if frame.valid
                                && p["expected"].as_object().unwrap().iter().all(|(k, v)| {
                                    frame.fields.get(k).map_or(false, |actual| equal(actual, v))
                                })
                            {
                                self.uncertain.remove(port);
                                return Ok(json!(frame));
                            }
                        }
                    }
                    std::thread::sleep(Duration::from_millis(5));
                }
            }
            "flash_firmware" | "reset_target" => {
                self.mark()?;
                let mut args = p.clone();
                args["target_override"] = p["target_device"].clone();
                if a == "flash_firmware" && args["after_flash"].is_null() {
                    args["after_flash"] = json!("halt");
                }
                if a == "flash_firmware" {
                    self.status["operation_kind"] = json!("flash_firmware");
                    self.status["cancellation_policy"] = json!("completed_algorithm_boundary");
                    self.publish()?;
                    args["control"] = json!({"run_id":self.status["run_id"],"run_dir":self.folder.canonicalize().map_err(|e|e.to_string())?});
                    let result = if p["flash_type"] == "ing_ini" {
                        self.run_ing_flash(p, end)
                    } else {
                        self.rpc(a, args, end)
                    };
                    let snapshot = self.folder.join("flash-state.json");
                    if let Ok(bytes) = std::fs::read(snapshot) {
                        if let Ok(value) = serde_json::from_slice::<Value>(&bytes) {
                            self.status["flash_state"] = value.clone();
                            self.emit("flash.state", value)?;
                        }
                    }
                    self.status["operation_kind"] = Value::Null;
                    self.publish()?;
                    let result = result?;
                    if result["state"] == "CANCELLED" {
                        if result["erase_program_stopped"] != true
                            || result["target_halted"] != true
                        {
                            return Err(
                                "FLASH_STATE_UNKNOWN: cancellation was not confirmed".into()
                            );
                        }
                        self.status["flash_state"] = result.clone();
                        self.target_may_run = false;
                        self.status["target_state"] = json!("HALTED");
                        self.publish()?;
                        return Err("CANCELLED".into());
                    }
                    if p["flash_type"] != "ing_ini"
                        && p["after_flash"].as_str().unwrap_or("halt") == "halt"
                    {
                        self.target_may_run = false;
                        self.status["target_state"] = json!("HALTED");
                    }
                    Ok(result)
                } else {
                    self.rpc(a, args, end)
                }
            }
            "swd_read_assert" | "swd_read_block" => {
                let mut args = p.clone();
                args["address"] = p["memory_addr"].clone();
                args["target_override"] = p["target_device"].clone();
                args["count"] = if a == "swd_read_assert" {
                    json!(p["read_width"].as_u64().unwrap() / 8)
                } else {
                    p["count"].clone()
                };
                if !p["symbol"].is_null() {
                    self.check(end)?;
                    let result = crate::symbols::dispatch("resolve_symbol", p)?;
                    self.check(end)?;
                    args["address"] = result["address"].clone();
                }
                let value = self.rpc("read_memory", args.clone(), end)?;
                let bytes = value["bytes"].as_array().ok_or("Missing memory bytes")?;
                if bytes.len() != args["count"].as_u64().unwrap() as usize {
                    return Err("Incomplete memory read".into());
                }
                // Validate the worker boundary before accepting even a block read.
                let bytes = checked_memory_bytes(bytes)?;
                if a == "swd_read_block" {
                    return Ok(value);
                }
                let actual = bytes.iter().enumerate()
                    .fold(0u64, |n, (i, b)| n | (u64::from(*b) << (8 * i)));
                compare(
                    actual,
                    p["expected_value"].as_u64().unwrap(),
                    p["operator"].as_str().unwrap_or("=="),
                )?;
                Ok(json!({"actual":actual}))
            }
            "svd_check_reg" => self.rpc("native_svd_assert", p.clone(), end),
            _ => Err(format!("Unsupported action {a}")),
        }
    }
    fn observe(&mut self, step: &Value, end: Instant) -> Result<Value, String> {
        let p = &step["params"];
        let port = p["port_name"].as_str().unwrap();
        let s = self.sessions.get(port).ok_or("Serial not open")?.clone();
        let mut cursor = *self.cursors.get(port).unwrap();
        let base = cursor;
        let mut bytes = vec![];
        let mut monitor = if step["action"] == "hil_observe" {
            Some(HilObserver::new(p.clone(), *self.marks.get(port).unwrap()))
        } else {
            None
        };
        let regex = if p["match_type"] == "regex" {
            Some(crate::config::serial_regex(p["pattern"].as_str().unwrap())?)
        } else {
            None
        };
        let mut last = s.elapsed_ms();
        loop {
            self.check(end)?;
            let (chunks, next) = s.journal.lock().unwrap().read(cursor)?;
            for chunk in chunks {
                last = chunk.elapsed_ms;
                if let Some(h) = monitor.as_mut() {
                    h.check_time(chunk.elapsed_ms)
                        .map_err(|e| format!("FAIL: {e}"))?;
                    for event in h
                        .feed(&chunk.data, chunk.elapsed_ms)
                        .map_err(|e| format!("FAIL: {e}"))?
                    {
                        self.emit("hil", event)?;
                    }
                } else {
                    bytes.extend_from_slice(&chunk.data);
                    if bytes.len() > 1024 * 1024 {
                        return Err("Match window exceeds 1 MiB".into());
                    }
                }
            }
            if let Some(h) = monitor.as_mut() {
                if let Some(done) = &h.done {
                    self.cursors.insert(port.into(), next);
                    if !h.failures.is_empty() {
                        return Err(format!("FAIL: {}", h.failures.join("; ")));
                    }
                    return Ok(json!({"done":done,"boot_count":h.boots}));
                }
                h.check_time(s.elapsed_ms())
                    .map_err(|e| format!("FAIL: {e}"))?;
            } else {
                let matched = if let Some(re) = &regex {
                    re.find(&bytes).map(|m| (m.start(), m.end()))
                } else {
                    let pattern = p["pattern"].as_str().unwrap().as_bytes();
                    bytes
                        .windows(pattern.len())
                        .position(|w| w == pattern)
                        .map(|start| (start, start + pattern.len()))
                };
                if let Some((start, finish)) = matched {
                    if finish == start {
                        return Err("Zero-length regex match rejected".into());
                    }
                    let mut groups = serde_json::Map::new();
                    if let Some(re) = &regex {
                        if let Some(caps) = re.captures(&bytes) {
                            for name in re.capture_names().flatten() {
                                groups.insert(
                                    name.into(),
                                    caps.name(name)
                                        .map(|v| json!(String::from_utf8_lossy(v.as_bytes())))
                                        .unwrap_or(Value::Null),
                                );
                            }
                        }
                    }
                    self.cursors.insert(port.into(), base + finish as u64);
                    return Ok(
                        json!({"matched":String::from_utf8_lossy(&bytes[start..finish]),"captures":groups}),
                    );
                }
                if let Some(idle) = p["idle_timeout_ms"].as_f64() {
                    if s.elapsed_ms() - last >= idle {
                        return Err("TIMEOUT: Serial idle timeout".into());
                    }
                }
            }
            cursor = next;
            std::thread::sleep(Duration::from_millis(5));
        }
    }
    fn evidence(&mut self, error: &str, p: &Value) {
        let settings = self.plan["evidence"].clone();
        self.status["deadline_ms"] =
            json!(wall_time_ms() + settings["timeout_ms"].as_u64().unwrap_or(10000));
        let _ = self.publish();
        let _ = self.emit("evidence.started", json!({"reason":error}));
        let bytes = std::fs::read(self.folder.join("serial.log")).unwrap_or_default();
        let _ = std::fs::write(
            self.folder.join("serial-tail.bin"),
            &bytes[bytes.len().saturating_sub(8192)..],
        );
        let mut record = json!({"reason":error,"errors":[]});
        if settings["enabled"] != false && !p["probe_id"].is_null() {
            let mut args = p.clone();
            args["evidence"] = settings.clone();
            match self.rpc(
                "capture_hil_evidence",
                args,
                Instant::now()
                    + Duration::from_millis(settings["timeout_ms"].as_u64().unwrap_or(10000)),
            ) {
                Ok(value) => record["snapshot"] = value,
                Err(error) => record["errors"] = json!([error]),
            }
        }
        let _ = atomic_json(
            &self
                .folder
                .join(format!("evidence-{}.json", self.rows.len())),
            &record,
        );
    }
    fn execute(&mut self, steps: &[Value], iteration: &str) -> Result<(), String> {
        for s in steps {
            if s["enabled"] == false {
                self.rows.push(json!({"step_id":s["id"],"step_name":s["name"],"iteration":iteration,"status":"skipped"}));
                continue;
            }
            self.check(
                self.started + Duration::from_millis(self.plan["timeout_ms"].as_u64().unwrap()),
            )?;
            if s["action"] == "loop_block" {
                for n in 0..s["params"]["count"].as_u64().unwrap() {
                    self.execute(
                        s["steps"].as_array().unwrap(),
                        &format!("{iteration}.{}", n + 1),
                    )?;
                }
                continue;
            }
            let attempts = 1 + if s["on_failure"] == "retry" {
                s["retry_count"].as_u64().unwrap()
            } else {
                0
            };
            for attempt in 1..=attempts {
                let start = Instant::now();
                self.status["current_step"] = s["id"].clone();
                self.status["phase"] = json!("step");
                let end = (start + Duration::from_millis(s["timeout_ms"].as_u64().unwrap()))
                    .min(self.started + Duration::from_millis(self.plan["timeout_ms"].as_u64().unwrap()));
                self.status["deadline_ms"] = json!(wall_time_ms()
                    + end.saturating_duration_since(Instant::now()).as_millis() as u64);
                self.publish()?;
                self.emit(
                    "step.started",
                    json!({"step_id":s["id"],"iteration":iteration,"attempt":attempt}),
                )?;
                let result = self.action(s, end).and_then(|v| {
                    self.check(end)?;
                    Ok(v)
                });
                let (status, error, actual) = match &result {
                    Ok(value) => ("pass", None, Some(value.to_string())),
                    Err(e) if e == "CANCELLED" => ("cancelled", Some(e.clone()), None),
                    Err(e) if e.starts_with("FAIL:") || e.starts_with("TIMEOUT:") => {
                        ("fail", Some(e.clone()), None)
                    }
                    Err(e) => ("error", Some(e.clone()), None),
                };
                let row = json!({"step_id":s["id"],"step_name":s["name"],"iteration":iteration,"attempt":attempt,"status":status,"message":error,"actual_output":actual,"duration_ms":start.elapsed().as_millis(),"timestamp":wall_time_ms().to_string()});
                self.rows.push(row.clone());
                self.emit("step.finished", json!({"result":row}))?;
                match result {
                    Ok(_) => break,
                    Err(e) if e == "CANCELLED" => return Err(e),
                    Err(e) if s["action"] == "flash_firmware" => {
                        // Never continue to a reset/power/write step after an unconfirmed flash.
                        self.emit(
                            "flash.aborted",
                            json!({"reason":e,"continuation_blocked":true}),
                        )?;
                        return Err(e);
                    }
                    Err(_) if attempt < attempts => continue,
                    Err(e) => {
                        let p = if !s["params"]["probe_id"].is_null() {
                            s["params"].clone()
                        } else {
                            flatten(self.plan["steps"].as_array().unwrap())
                                .into_iter()
                                .find(|x| !x["params"]["probe_id"].is_null())
                                .map(|x| x["params"].clone())
                                .unwrap_or(json!({}))
                        };
                        self.evidence(&e, &p);
                        if s["on_failure"] != "continue" {
                            return Err(e);
                        }
                    }
                }
            }
        }
        Ok(())
    }
    pub fn run(&mut self) -> Result<String, String> {
        self.publish()?;
        let result = (|| {
            self.check(self.started + Duration::from_secs(60))?;
            self.prepare()?;
            let steps = self.plan["steps"].as_array().unwrap().clone();
            for n in 0..self.plan["loop_count"].as_u64().unwrap() {
                self.status["loop"] = json!(n + 1);
                self.execute(&steps, &(n + 1).to_string())?;
            }
            self.check(
                self.started + Duration::from_millis(self.plan["timeout_ms"].as_u64().unwrap()),
            )?;
            Ok::<_, String>(())
        })();
        let cancelled = result.as_ref().err().map_or(false, |e| e == "CANCELLED");
        if cancelled && self.target_may_run {
            self.status["phase"] = json!("target_stop");
            self.status["deadline_ms"] = json!(
                wall_time_ms() + self.plan["stop"]["timeout_ms"].as_u64().unwrap_or(5000) + 1000
            );
            self.status["stop_confirmed"] = json!(false);
            self.status["target_state"] = json!("UNKNOWN");
            self.publish()?;
            let stop_result = self.stop_target();
            self.rows.push(json!({"step_id":"target_stop","step_name":"Firmware stop confirmation","iteration":"cleanup","status":if stop_result.is_ok(){"pass"}else{"error"},"message":stop_result.as_ref().err()}));
            if let Err(error) = stop_result {
                self.status["stop_detail"] = json!(error.clone());
                self.status["error"] = json!(error);
                self.status["state"] = json!("ERROR");
                self.evidence(&error, &json!({}));
            }
        }
        self.status["deadline_ms"] = json!(wall_time_ms() + 10000);
        let _ = self.publish();
        for s in self.sessions.values() {
            let _ = s.close();
        }
        self.sessions.clear();
        self.bridge.take();
        let mut outcome = match &result {
            Err(e)
                if e == "CANCELLED"
                    && (self.status["stop_confirmed"] == true || !self.target_may_run) =>
            {
                "CANCELLED"
            }
            Err(e) if e == "CANCELLED" => "ERROR",
            Err(e) if e.starts_with("FAIL:") || e.starts_with("TIMEOUT:") => "FAIL",
            Err(_) => "ERROR",
            Ok(_) => "PASS",
        };
        if outcome == "PASS" {
            if self.rows.iter().any(|r| r["status"] == "error") {
                outcome = "ERROR";
            } else if self.rows.iter().any(|r| r["status"] == "fail") {
                outcome = "FAIL";
            }
        }
        let visited: HashSet<_> = self
            .rows
            .iter()
            .map(|r| format!("{}:{}", r["iteration"], r["step_id"]))
            .collect();
        fn remaining(
            steps: &[Value],
            iter: &str,
            visited: &HashSet<String>,
            rows: &mut Vec<Value>,
        ) {
            for s in steps {
                if s["action"] == "loop_block" && s["enabled"] != false {
                    for n in 0..s["params"]["count"].as_u64().unwrap() {
                        remaining(
                            s["steps"].as_array().unwrap(),
                            &format!("{iter}.{}", n + 1),
                            visited,
                            rows,
                        )
                    }
                } else if !visited.contains(&format!("{}:{}", json!(iter), s["id"])) {
                    rows.push(json!({"step_id":s["id"],"step_name":s["name"],"iteration":iter,"status":"skipped","message":"Not executed"}));
                }
            }
        }
        for n in 0..self.plan["loop_count"].as_u64().unwrap() {
            remaining(
                self.plan["steps"].as_array().unwrap(),
                &(n + 1).to_string(),
                &visited,
                &mut self.rows,
            );
        }
        if self.folder.join("supervisor-lost").is_file() {
            outcome = "INTERRUPTED";
            self.status["error"] = json!("HIL service exited; execution interrupted and hardware outcome may be unknown");
        }
        self.status["state"] = json!(outcome);
        if self.status["error"].is_null() {
            self.status["error"] = json!(result.err());
        }
        self.status["done"] = json!(true);
        self.status["phase"] = json!("complete");
        let mut report = self.status.clone();
        report["pipeline_name"] = self.plan["name"].clone();
        report["results"] = json!(self.rows);
        report["start_time"] = json!(self.wall);
        report["end_time"] = json!(wall_time_ms() as f64 / 1000.);
        report["duration_ms"] = json!(self.started.elapsed().as_millis());
        report["total_loops"] = self.plan["loop_count"].clone();
        report["total_steps"] = json!(self.rows.len());
        report["pass_count"] = json!(self.rows.iter().filter(|r| r["status"] == "pass").count());
        report["fail_count"] = json!(self
            .rows
            .iter()
            .filter(|r| r["status"] == "fail" || r["status"] == "error")
            .count());
        summarize(&self.plan, &mut report);
        write_reports(&self.folder, &report)?;
        self.emit("run.finished", json!({"state":outcome}))?;
        self.publish()?;
        Ok(outcome.into())
    }
}
fn checked_memory_bytes(bytes: &[Value]) -> Result<Vec<u8>, String> {
    bytes.iter().map(|v| v.as_u64().and_then(|n| u8::try_from(n).ok())
        .ok_or_else(|| "Invalid memory byte: expected integer 0..255".into())).collect()
}

fn send_paced(
    bytes: &[u8], delay_ms: u64,
    mut write: impl FnMut(&[u8]) -> Result<usize, String>,
    mut check: impl FnMut() -> Result<(), String>,
) -> Result<usize, String> {
    for (index, byte) in bytes.iter().enumerate() {
        check()?;
        write(std::slice::from_ref(byte))?;
        if index + 1 < bytes.len() {
            let until = Instant::now() + Duration::from_millis(delay_ms);
            while Instant::now() < until {
                check()?;
                std::thread::sleep(until.saturating_duration_since(Instant::now())
                    .min(Duration::from_millis(5)));
            }
        }
    }
    check()?;
    Ok(bytes.len())
}

pub fn equal(a: &Value, b: &Value) -> bool {
    match (a.as_f64(), b.as_f64()) {
        (Some(a), Some(b)) => a == b,
        _ => a == b,
    }
}
fn compare(a: u64, b: u64, op: &str) -> Result<(), String> {
    if match op {
        "==" => a == b,
        "!=" => a != b,
        ">" => a > b,
        "<" => a < b,
        ">=" => a >= b,
        "<=" => a <= b,
        "mask" => a & b == b,
        _ => false,
    } {
        Ok(())
    } else {
        Err(format!("FAIL: {a:#x} does not satisfy {op} {b:#x}"))
    }
}
pub fn flatten(steps: &[Value]) -> Vec<&Value> {
    let mut out = vec![];
    for s in steps {
        out.push(s);
        if s["action"] == "loop_block" && s["enabled"] != false {
            out.extend(flatten(s["steps"].as_array().unwrap()));
        }
    }
    out
}

#[cfg(test)]
mod cancel_tests {
    use super::*;
    #[test]
    fn reservation_blocks_duplicate_submission_and_keeps_snapshot() {
        let folder = std::env::temp_dir().join(format!("hil-admission-{}", std::process::id()));
        let jobs = Jobs::new(folder.clone());
        let mut args = json!({"document":{"steps":[{"action":"delay","params":{"delay_ms":1}}]}});
        let prepared = jobs.prepare(&args).unwrap();
        assert!(jobs.prepare(&args).is_err());
        args["document"]["steps"][0]["params"]["delay_ms"] = json!(2);
        assert_eq!(prepared.plan()["steps"][0]["params"]["delay_ms"], 1);
        drop(prepared);
        let next = jobs.prepare(&args).unwrap();
        assert_eq!(next.plan()["steps"][0]["params"]["delay_ms"], 2);
        drop(next);
        std::fs::remove_dir_all(folder).unwrap();
    }
    #[test]
    fn invalid_memory_bytes_cannot_become_zero_or_overflow() {
        for bad in [Value::Null, json!(true), json!(-1), json!(256), json!(0.5), json!("0")] {
            assert!(checked_memory_bytes(&[bad]).is_err());
        }
        assert_eq!(checked_memory_bytes(&[json!(0), json!(255)]).unwrap(), vec![0, 255]);
    }
    #[test]
    fn paced_send_cancellation_blocks_subsequent_bytes() {
        let sent = std::cell::Cell::new(0);
        let result = send_paced(b"ABC", 1000,
            |bytes| { sent.set(sent.get() + bytes.len()); Ok(bytes.len()) },
            || if sent.get() > 0 { Err("CANCELLED".into()) } else { Ok(()) });
        assert_eq!(result.unwrap_err(), "CANCELLED");
        assert_eq!(sent.get(), 1);
        let result = send_paced(b"ABC", 0, |_| panic!("must not write"),
            || Err("TIMEOUT: test deadline".into()));
        assert!(result.unwrap_err().starts_with("TIMEOUT:"));
    }
    #[test]
    fn supervisor_loss_is_interrupted_in_first_final_report() {
        let folder = std::env::temp_dir().join(format!("hil-parent-lost-{}", std::process::id()));
        std::fs::create_dir_all(&folder).unwrap();
        let plan = crate::config::load_plan(&json!({"document":{"steps":[{"action":"delay","params":{"delay_ms":1}}]}})).unwrap();
        std::fs::write(folder.join("supervisor-lost"), b"service exited").unwrap();
        std::fs::write(folder.join("cancel"), b"service exited").unwrap();
        let mut worker = Worker::new(plan, folder.clone()).unwrap();
        assert_eq!(worker.run().unwrap(), "INTERRUPTED");
        let report: Value = serde_json::from_slice(&std::fs::read(folder.join("report.json")).unwrap()).unwrap();
        assert_eq!(report["state"], "INTERRUPTED");
        assert_eq!(report["hardware_verified"], false);
        drop(worker);
        std::fs::remove_dir_all(folder).unwrap();
    }
    #[test]
    fn cancellation_cannot_claim_running_firmware_stopped_without_contract() {
        for active in [false, true] {
            let folder =
                std::env::temp_dir().join(format!("hil-cancel-{}-{active}", std::process::id()));
            std::fs::create_dir_all(&folder).unwrap();
            let plan = crate::config::load_plan(
                &json!({"document":{"steps":[{"action":"delay","params":{"delay_ms":1}}]}}),
            )
            .unwrap();
            let mut worker = Worker::new(plan, folder.clone()).unwrap();
            worker.target_may_run = active;
            std::fs::write(folder.join("cancel"), b"").unwrap();
            assert_eq!(
                worker.run().unwrap(),
                if active { "ERROR" } else { "CANCELLED" }
            );
            let report: Value =
                serde_json::from_slice(&std::fs::read(folder.join("report.json")).unwrap())
                    .unwrap();
            if active {
                assert_eq!(report["target_state"], "UNKNOWN");
                assert_eq!(report["stop_confirmed"], false);
                assert!(report["error"]
                    .as_str()
                    .unwrap()
                    .contains("STOP_UNCONFIRMED"));
                assert!(std::fs::read_to_string(folder.join("junit.xml"))
                    .unwrap()
                    .contains("STOP_UNCONFIRMED"));
            }
            drop(worker);
            std::fs::remove_dir_all(folder).unwrap();
        }
    }
}
