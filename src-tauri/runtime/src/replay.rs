use crate::stream::HilObserver;
use serde_json::{json, Value};
use std::io::BufRead;
use std::path::Path;
pub fn run(plan: &Value, events: &Path, root: &Path) -> Result<Value, String> {
    let steps = crate::runner::flatten(plan["steps"].as_array().ok_or("steps required")?);
    let observers: Vec<_> = steps
        .into_iter()
        .filter(|s| s["action"] == "hil_observe" && s["enabled"] != false)
        .collect();
    if observers.len() != 1 {
        return Err("Replay requires exactly one HIL observer".into());
    }
    let step = observers[0];
    let p = &step["params"];
    let mut observer = None;
    let mut start = None;
    let mut error = None;
    let result = (|| {
        for line in
            std::io::BufReader::new(std::fs::File::open(events).map_err(|e| e.to_string())?).lines()
        {
            let event: Value = serde_json::from_str(&line.map_err(|e| e.to_string())?)
                .map_err(|e| e.to_string())?;
            let stamp = event["elapsed_ms"]
                .as_f64()
                .unwrap_or(event["time"].as_f64().unwrap_or(0.) * 1000.);
            if event["kind"] == "observation.mark" {
                start = Some(stamp);
                observer = Some(HilObserver::new(p.clone(), 0.));
            }
            if event["kind"] != "serial"
                || event["direction"].as_str().unwrap_or("RX") != "RX"
                || event["port"] != p["port_name"]
            {
                continue;
            }
            if start.is_none() {
                start = Some(stamp);
                observer = Some(HilObserver::new(p.clone(), 0.));
            }
            let elapsed = stamp - start.unwrap();
            if elapsed < 0. || elapsed > step["timeout_ms"].as_f64().unwrap() {
                return Err("Replay timestamp/deadline invalid".into());
            }
            let h = observer.as_mut().unwrap();
            h.check_time(elapsed)?;
            h.feed(
                &hil_debug_core::capture::unhex(event["data"].as_str().ok_or("data required")?)?,
                elapsed,
            )?;
            if h.done.is_some() {
                break;
            }
        }
        let h = observer.as_ref().ok_or("Replay ended without BOOT")?;
        if h.done.is_none() {
            return Err("Replay ended without DONE".into());
        }
        if !h.failures.is_empty() {
            return Err(h.failures.join("; "));
        }
        Ok::<_, String>(())
    })();
    if let Err(e) = result {
        error = Some(e);
    }
    let folder = root.join(format!(
        "replay-{}",
        hil_debug_core::capture::wall_time_ms()
    ));
    std::fs::create_dir_all(&folder).map_err(|e| e.to_string())?;
    let report = json!({"state":if error.is_some(){"FAIL"}else{"PASS"},"mode":"REPLAY_ONLY","hardware_verified":false,"pipeline_name":format!("{} [REPLAY — NO HARDWARE]",plan["name"].as_str().unwrap_or("HIL")),"error":error,"report_dir":folder,"results":[]});
    crate::report::write_reports(&folder, &report)?;
    Ok(report)
}
