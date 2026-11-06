use serde_json::{json, Value};
use std::io::Write;
use std::path::Path;
pub fn atomic_json(path: &Path, value: &Value) -> Result<(), String> {
    let temp = path.with_extension("tmp");
    let mut f = std::fs::File::create(&temp).map_err(|e| e.to_string())?;
    f.write_all(&serde_json::to_vec_pretty(value).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())?;
    f.sync_all().map_err(|e| e.to_string())?;
    drop(f);
    for _ in 0..20 {
        match std::fs::rename(&temp, path) {
            Ok(()) => return Ok(()),
            Err(_) if cfg!(windows) => {
                let _ = std::fs::remove_file(path);
                std::thread::sleep(std::time::Duration::from_millis(10));
            }
            Err(e) => return Err(e.to_string()),
        }
    }
    Err("Unable to publish JSON report".into())
}
fn escape(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}
pub fn write_reports(folder: &Path, report: &Value) -> Result<(), String> {
    atomic_json(&folder.join("report.json"), report)?;
    let rows = report["results"].as_array().cloned().unwrap_or_default();
    let mut cases = String::new();
    let mut failures = 0;
    let mut errors = 0;
    for row in &rows {
        let status = row["status"].as_str().unwrap_or("error");
        let mut content = String::new();
        match status {
            "pass" => {}
            "skipped" => content.push_str("<skipped/>"),
            "fail" => {
                failures += 1;
                content = format!(
                    "<failure message=\"{}\"/>",
                    escape(row["message"].as_str().unwrap_or("Assertion failed"))
                );
            }
            _ => {
                errors += 1;
                content = format!(
                    "<error message=\"{}\"/>",
                    escape(row["message"].as_str().unwrap_or(status))
                );
            }
        }
        cases.push_str(&format!(
            "<testcase name=\"{}\" classname=\"{}\" time=\"{}\">{content}</testcase>",
            escape(row["step_name"].as_str().unwrap_or("step")),
            escape(row["iteration"].as_str().unwrap_or("run")),
            row["duration_ms"].as_f64().unwrap_or(0.) / 1000.
        ));
    }
    let extra = if report["state"] != "PASS" && failures + errors == 0 {
        errors += 1;
        cases.push_str(&format!(
            "<testcase name=\"run completion\"><error message=\"{}\"/></testcase>",
            escape(report["error"].as_str().unwrap_or("Incomplete run"))
        ));
        1
    } else {
        0
    };
    let xml=format!("<?xml version=\"1.0\" encoding=\"UTF-8\"?><testsuite name=\"{}\" tests=\"{}\" failures=\"{failures}\" errors=\"{errors}\">{cases}</testsuite>",escape(report["pipeline_name"].as_str().unwrap_or("HIL")),rows.len()+extra);
    std::fs::write(folder.join("junit.xml"), xml).map_err(|e| e.to_string())?;
    std::fs::write(
        folder.join("report.html"),
        format!(
            "<!doctype html><meta charset=\"utf-8\"><title>HIL report</title><pre>{}</pre>",
            escape(&serde_json::to_string_pretty(report).unwrap())
        ),
    )
    .map_err(|e| e.to_string())?;
    Ok(())
}
/// Count enabled expanded leaves, never retries, disabled definitions, or cleanup.
pub fn summarize(plan: &Value, report: &mut Value) {
    use std::collections::BTreeMap;
    fn leaves(steps: &[Value], iteration: &str, out: &mut BTreeMap<(String, String), bool>) {
        for step in steps {
            if step["enabled"] == false { continue; }
            if step["action"] == "loop_block" {
                for n in 0..step["params"]["count"].as_u64().unwrap_or(0) {
                    leaves(step["steps"].as_array().map(Vec::as_slice).unwrap_or(&[]),
                        &format!("{iteration}.{}", n + 1), out);
                }
            } else if let Some(id) = step["id"].as_str() {
                let assertion = matches!(step["action"].as_str(), Some("serial_wait_match" | "hil_observe" |
                    "protocol_request" | "swd_read_assert" | "svd_check_reg" | "instrumentation_assert"));
                out.insert((iteration.into(), id.into()), assertion);
            }
        }
    }
    let mut planned = BTreeMap::new();
    for n in 0..plan["loop_count"].as_u64().unwrap_or(1) {
        leaves(plan["steps"].as_array().map(Vec::as_slice).unwrap_or(&[]), &(n + 1).to_string(), &mut planned);
    }
    let mut outcomes: BTreeMap<(String, String), Vec<String>> = BTreeMap::new();
    for row in report["results"].as_array().map(Vec::as_slice).unwrap_or(&[]) {
        let key = (row["iteration"].as_str().unwrap_or("").to_string(), row["step_id"].as_str().unwrap_or("").to_string());
        let status = row["status"].as_str().unwrap_or("error");
        if planned.contains_key(&key) && status != "skipped" {
            outcomes.entry(key).or_default().push(status.into());
        }
    }
    let passed = outcomes.values().filter(|v| v.iter().all(|s| s == "pass")).count();
    let failed = outcomes.values().filter(|v| v.iter().any(|s| s == "fail" || s == "error")).count();
    let cancelled = outcomes.values().filter(|v| v.iter().any(|s| s == "cancelled")).count();
    let verified = report["state"] == "PASS" && passed == planned.len() && !planned.is_empty()
        && outcomes.iter().any(|(key, values)| planned[key] && values.iter().all(|s| s == "pass"));
    report["planned_steps"] = json!(planned.len());
    report["executed_steps"] = json!(outcomes.len());
    report["skipped_steps"] = json!(planned.len() - outcomes.len());
    report["attempt_count"] = json!(outcomes.values().map(Vec::len).sum::<usize>());
    report["passed_steps"] = json!(passed);
    report["failed_steps"] = json!(failed);
    report["cancelled_steps"] = json!(cancelled);
    report["hardware_verified"] = json!(verified);
}

pub fn interrupted(folder: &Path, error: &str) -> Result<(), String> {
    let state = std::fs::read(folder.join("status.json"))
        .ok()
        .and_then(|b| serde_json::from_slice::<Value>(&b).ok())
        .unwrap_or(json!({}));
    let mut report = state;
    report["state"] = json!("INTERRUPTED");
    report["done"] = json!(true);
    report["error"] = json!(error);
    report["target_state"] = json!("UNKNOWN");
    report["stop_confirmed"] = json!(false);
    report["stop_detail"] = json!("Worker interrupted; target stop could not be confirmed");
    if let Ok(bytes) = std::fs::read(folder.join("flash-state.json")) {
        if let Ok(mut state) = serde_json::from_slice::<Value>(&bytes) {
            if state["state"] != "CANCELLED" && state["state"] != "COMPLETED" {
                state["state"] = json!("UNKNOWN");
                state["erase_program_stopped"] = json!(false);
            }
            report["flash_state"] = state;
        }
    }
    // A killed worker has not written its final rows. Recover durable completed attempts.
    let mut results = Vec::new();
    let mut pending: Option<Value> = None;
    if let Ok(file) = std::fs::File::open(folder.join("events.jsonl")) {
        use std::io::BufRead;
        for line in std::io::BufReader::new(file).lines() {
            let Ok(line) = line else { break; };
            let Ok(event) = serde_json::from_str::<Value>(&line) else { break; };
            if event["kind"] == "step.started" {
                pending = Some(json!({"step_id":event["step_id"],"step_name":event["step_id"],
                    "iteration":event["iteration"],"attempt":event["attempt"],"status":"error",
                    "message":"Worker interrupted before step completion; hardware outcome unknown"}));
            } else if event["kind"] == "step.finished" && event["result"].is_object() {
                results.push(event["result"].clone());
                pending = None;
            }
        }
    }
    if let Some(row) = pending { results.push(row); }
    report["results"] = json!(results);
    report["hardware_verified"] = json!(false);
    if let Ok(bytes) = std::fs::read(folder.join("plan.json")) {
        if let Ok(plan) = serde_json::from_slice::<Value>(&bytes) {
            report["pipeline_name"] = plan["name"].clone();
            summarize(&plan, &mut report);
        }
    }
    write_reports(folder, &report)?;
    atomic_json(&folder.join("status.json"), &report)
}

#[cfg(test)]
mod summary_tests {
    use super::*;
    #[test]
    fn retries_disabled_cleanup_and_unexecuted_have_separate_denominators() {
        let plan = json!({"loop_count":2,"steps":[
            {"id":"group","action":"loop_block","params":{"count":2},"steps":[{"id":"assert","action":"serial_wait_match"}]},
            {"id":"disabled","action":"delay","enabled":false}]});
        let mut report = json!({"state":"FAIL","results":[
            {"step_id":"assert","iteration":"1.1","status":"fail"},
            {"step_id":"assert","iteration":"1.1","status":"pass"},
            {"step_id":"assert","iteration":"1.2","status":"pass"},
            {"step_id":"disabled","iteration":"1","status":"skipped"},
            {"step_id":"target_stop","iteration":"cleanup","status":"pass"}]});
        summarize(&plan, &mut report);
        assert_eq!(report["planned_steps"], 4);
        assert_eq!(report["executed_steps"], 2);
        assert_eq!(report["skipped_steps"], 2);
        assert_eq!(report["attempt_count"], 3);
        assert_eq!(report["passed_steps"], 1);
        assert_eq!(report["failed_steps"], 1);
        assert_eq!(report["hardware_verified"], false);
    }
    #[test]
    fn delay_success_is_not_hardware_verification() {
        let plan = json!({"steps":[{"id":"wait","action":"delay"}]});
        let mut report = json!({"state":"PASS","results":[{"step_id":"wait","iteration":"1","status":"pass"}]});
        summarize(&plan, &mut report);
        assert_eq!(report["passed_steps"], 1);
        assert_eq!(report["hardware_verified"], false);
    }
}
