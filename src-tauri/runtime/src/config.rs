use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, BTreeSet, HashSet};
use std::path::{Path, PathBuf};

pub fn integer(v: &Value, name: &str, min: u64, max: u64) -> Result<u64, String> {
    let n = if let Some(n) = v.as_u64() {
        n
    } else if let Some(s) = v.as_str() {
        if let Some(h) = s.strip_prefix("0x").or_else(|| s.strip_prefix("0X")) {
            u64::from_str_radix(h, 16).map_err(|_| format!("Invalid {name}"))?
        } else {
            s.parse::<u64>().map_err(|_| format!("Invalid {name}"))?
        }
    } else {
        return Err(format!("{name} must be an integer"));
    };
    if n < min || n > max {
        return Err(format!("{name} must be {min}..{max}"));
    }
    Ok(n)
}
pub fn duration(v: &Value) -> Result<u64, String> {
    if let Some(s) = v.as_str() {
        for (unit, multiplier) in [("ms", 1.), ("s", 1000.), ("m", 60000.), ("h", 3600000.)] {
            if let Some(number) = s.strip_suffix(unit) {
                let n = number.parse::<f64>().map_err(|_| "Invalid duration")?;
                if !n.is_finite() || n <= 0. {
                    return Err("Invalid duration".into());
                }
                return integer(
                    &json!((n * multiplier) as u64),
                    "duration_ms",
                    1,
                    7 * 86400000,
                );
            }
        }
    }
    integer(v, "duration_ms", 1, 7 * 86400000)
}
fn keys(v: &Value, allowed: &str) -> Result<(), String> {
    let map = v.as_object().ok_or("Expected object")?;
    for k in map.keys() {
        if !allowed.split_whitespace().any(|a| a == k) {
            return Err(format!("Unknown field: {k}"));
        }
    }
    Ok(())
}
pub fn read_document(path: &Path) -> Result<Value, String> {
    if std::fs::metadata(path).map_err(|e| e.to_string())?.len() > 2 * 1024 * 1024 {
        return Err("Configuration exceeds 2 MiB".into());
    }
    let text = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
    let text = text.trim_start_matches('\u{feff}');
    if matches!(
        path.extension().and_then(|s| s.to_str()),
        Some("yaml" | "yml")
    ) {
        serde_yaml::from_str(text).map_err(|e| e.to_string())
    } else {
        serde_json::from_str(text).map_err(|e| e.to_string())
    }
}
pub fn serial_regex(pattern: &str) -> Result<regex::bytes::Regex, String> {
    regex::bytes::Regex::new(&format!("(?-u:{pattern})")).map_err(|e| {
        format!(
            "Unsupported/invalid byte regex; backreferences and look-around are not supported: {e}"
        )
    })
}
fn expand(v: &mut Value, vars: &Map<String, Value>, depth: usize) -> Result<(), String> {
    if depth > 32 {
        return Err("Configuration nesting exceeds 32".into());
    }
    match v {
        Value::String(text) => {
            let re = regex::Regex::new(r"\$\{([\w.-]+)\}").unwrap();
            let original = text.clone();
            for cap in re.captures_iter(&original) {
                let value = vars
                    .get(&cap[1])
                    .ok_or_else(|| format!("Missing parameter {}", &cap[1]))?;
                let replacement = value
                    .as_str()
                    .map(str::to_string)
                    .unwrap_or_else(|| value.to_string());
                *text = text.replace(&cap[0], &replacement);
            }
        }
        Value::Array(a) => {
            for item in a {
                expand(item, vars, depth + 1)?;
            }
        }
        Value::Object(m) => {
            for item in m.values_mut() {
                expand(item, vars, depth + 1)?;
            }
        }
        _ => {}
    }
    Ok(())
}
pub fn load_plan(args: &Value) -> Result<Value, String> {
    let base = std::env::current_dir().map_err(|e| e.to_string())?;
    let (mut doc, base) = if let Some(file) = args["file"].as_str() {
        if !args["document"].is_null() {
            return Err("Use file or document".into());
        }
        let path = base.join(file);
        (read_document(&path)?, path.parent().unwrap().to_path_buf())
    } else {
        (
            args["document"].clone(),
            args["base_dir"].as_str().map(PathBuf::from).unwrap_or(base),
        )
    };
    keys(&doc,"$schema schema_version version name description loop_count stop_on_error steps bench parameters evidence timeout_ms stop _resources _base_dir")?;
    let legacy = doc["schema_version"].is_null() || doc["schema_version"] == 1;
    let v3 = doc["schema_version"] == 3;
    if !legacy && doc["schema_version"] != 2 && !v3 {
        return Err("Supported schema_version: 1, 2, 3".into());
    }
    let mut vars = doc
        .as_object_mut()
        .unwrap()
        .remove("parameters")
        .unwrap_or(json!({}))
        .as_object()
        .ok_or("parameters must be an object")?
        .clone();
    if !args["parameters"].is_null() {
        for (k, v) in args["parameters"]
            .as_object()
            .ok_or("parameters must be an object")?
        {
            if !vars.contains_key(k) {
                return Err(format!("Unknown parameter: {k}"));
            }
            vars.insert(k.clone(), v.clone());
        }
    }
    expand(&mut doc, &vars, 0)?;
    let mut bench = doc
        .as_object_mut()
        .unwrap()
        .remove("bench")
        .unwrap_or(json!({}));
    if let Some(path) = bench.as_str() {
        let path = base.join(path);
        bench = read_document(&path)?;
        expand(&mut bench, &vars, 0)?;
        if let Some(pack) = bench["pack_path"].as_str() {
            bench["pack_path"] = json!(path.parent().unwrap().join(pack).to_string_lossy());
        }
    }
    keys(
        &bench,
        if v3 {
            "probe_id target_device frequency pack_path port_name baud_rate devices bindings instrumentation instruments exit_policy"
        } else {
            "probe_id target_device frequency pack_path port_name baud_rate"
        },
    )?;
    let mut device_id = None;
    if v3 {
        for key in [
            "devices",
            "bindings",
            "instrumentation",
            "instruments",
            "exit_policy",
        ] {
            if !bench[key].is_null() && !bench[key].is_object() {
                return Err(format!("bench.{key} must be an object"));
            }
        }
        if !bench["bindings"].is_null() {
            keys(&bench["bindings"], "target console probe")?;
            if let Some(target) = bench["bindings"]["target"].as_str() {
                let device = &bench["devices"][target];
                keys(device, "device_id board_id")?;
                device_id = Some(
                    device["device_id"]
                        .as_str()
                        .filter(|s| !s.is_empty())
                        .ok_or("Bound target device_id required")?
                        .to_string(),
                );
            }
            if let Some(console) = bench["bindings"]["console"].as_str() {
                let device = bench["devices"][console].clone();
                keys(&device, "transport port_name baud_rate")?;
                if device["transport"] != "uart" {
                    return Err("Automatic instrumentation transport supports UART only".into());
                }
                bench["port_name"] = device["port_name"].clone();
                bench["baud_rate"] = device.get("baud_rate").cloned().unwrap_or(json!(115200));
            }
        }
        if !bench["instrumentation"].is_null() {
            keys(&bench["instrumentation"], "mode control")?;
        }
    }
    // Capability preflight traverses the complete plan before any run directory or I/O.
    fn capabilities(steps: &Value, v3: bool) -> Result<(), String> {
        for step in steps.as_array().ok_or("steps must be an array")? {
            if step["enabled"] == false {
                continue;
            }
            let action = step["action"].as_str().unwrap_or("");
            if action.starts_with("power_") {
                return Err("UNSUPPORTED: no production power/measurement adapter installed; no hardware operations executed".into());
            }
            if ["crash_collect", "rtos_snapshot"].contains(&action) {
                return Err(
                    "UNSUPPORTED: target command handshake/export adapter is not configured".into(),
                );
            }
            if action.starts_with("instrumentation_") && !v3 {
                return Err("Instrumentation actions require schema_version 3".into());
            }
            if action == "loop_block" || action == "repeat" {
                capabilities(&step["steps"], v3)?;
            }
        }
        Ok(())
    }
    capabilities(&doc["steps"], v3)?;
    fn ordering(
        steps: &Value,
        active: &mut HashSet<String>,
        finished: &mut HashSet<String>,
    ) -> Result<(), String> {
        for s in steps.as_array().ok_or("steps must be an array")? {
            if s["enabled"] == false {
                continue;
            }
            let action = s["action"].as_str().unwrap_or("");
            if action == "loop_block" || action == "repeat" {
                if !active.is_empty() {
                    return Err("Instrumentation windows cannot cross loop boundaries".into());
                }
                let mut local_active = HashSet::new();
                let mut local_finished = HashSet::new();
                ordering(&s["steps"], &mut local_active, &mut local_finished)?;
                if !local_active.is_empty() {
                    return Err("Unclosed instrumentation window inside loop".into());
                }
                continue;
            }
            let port = s["params"]["port_name"]
                .as_str()
                .unwrap_or("@bench")
                .to_string();
            match action {
                "instrumentation_start" => {
                    if !active.insert(port.clone()) {
                        return Err("Duplicate instrumentation_start".into());
                    }
                    finished.remove(&port);
                }
                "instrumentation_stop" => {
                    if !active.remove(&port) {
                        return Err("instrumentation_stop requires start in the same block".into());
                    }
                    finished.insert(port);
                }
                "instrumentation_assert" => {
                    if active.remove(&port) {
                        finished.insert(port.clone());
                    }
                    if !finished.contains(&port) {
                        return Err("instrumentation_assert requires an observed window".into());
                    }
                }
                _ => {}
            }
        }
        Ok(())
    }
    let resource_config = if v3 { Some(bench.clone()) } else { None };
    let instrument_mode = bench["instrumentation"]["mode"]
        .as_str()
        .unwrap_or("binary")
        .to_string();
    let control = bench["instrumentation"]["control"]
        .as_str()
        .unwrap_or("passive");
    if !["binary", "text"].contains(&instrument_mode.as_str()) || control != "passive" {
        return Err("UNSUPPORTED: only explicit passive UART observation is available".into());
    }
    let stop = doc["stop_on_error"].as_bool().unwrap_or(true);
    if !doc["stop_on_error"].is_null() && !doc["stop_on_error"].is_boolean() {
        return Err("stop_on_error must be boolean".into());
    }
    let mut context = Context {
        base,
        bench,
        ids: HashSet::new(),
        ports: BTreeMap::new(),
        probes: BTreeSet::new(),
        count: 0,
        legacy,
        stop,
        v3,
        device_id,
        instrument_mode,
    };
    let steps = context.steps(&doc["steps"], 0)?;
    if v3 {
        let mut active = HashSet::new();
        let mut finished = HashSet::new();
        ordering(&json!(steps), &mut active, &mut finished)?;
        if !active.is_empty() {
            return Err("Plan contains unclosed instrumentation observation windows".into());
        }
    }
    let loops = integer(
        doc.get("loop_count").unwrap_or(&json!(1)),
        "loop_count",
        1,
        10000,
    )?;
    fn count(steps: &[Value]) -> Result<u64, String> {
        let mut total = 0u64;
        for s in steps {
            if s["enabled"] == false {
                continue;
            }
            let n = if s["action"] == "loop_block" {
                count(s["steps"].as_array().unwrap())?
                    .checked_mul(s["params"]["count"].as_u64().unwrap())
                    .ok_or("Loop overflow")?
            } else {
                1
            };
            total = total.checked_add(n).ok_or("Loop overflow")?;
        }
        Ok(total)
    }
    let expanded = count(&steps)?.checked_mul(loops).ok_or("Loop overflow")?;
    if expanded == 0 || expanded > 10000 {
        return Err("Plan must execute 1..10000 leaf steps".into());
    }
    let mut evidence = doc.get("evidence").cloned().unwrap_or(json!({}));
    keys(&evidence, "enabled memory_addr count timeout_ms")?;
    if !evidence["enabled"].is_null() && !evidence["enabled"].is_boolean() {
        return Err("evidence.enabled must be boolean".into());
    }
    if !evidence["memory_addr"].is_null() {
        evidence["memory_addr"] = json!(integer(
            &evidence["memory_addr"],
            "memory_addr",
            0,
            u32::MAX as u64
        )?);
        evidence["count"] = json!(integer(
            evidence.get("count").unwrap_or(&json!(256)),
            "count",
            1,
            4096
        )?);
    }
    evidence["timeout_ms"] = json!(duration(
        evidence.get("timeout_ms").unwrap_or(&json!(10000))
    )?);
    if !doc["stop"].is_null() {
        let stop = &mut doc["stop"];
        keys(stop,"port_name baud_rate send_data send_format send_ending match_type ack_pattern timeout_ms")?;
        for key in ["port_name", "baud_rate"] {
            if stop[key].is_null() {
                if let Some(value) = context.bench.get(key) {
                    stop[key] = value.clone();
                }
            }
        }
        crate::stop::request_bytes(stop)?;
        crate::stop::StopAck::new("preflight".into(), 0, stop)?;
        if stop["port_name"].as_str().unwrap_or("").is_empty() {
            return Err("stop.port_name required".into());
        }
        if stop["ack_pattern"].as_str().unwrap_or("").is_empty() {
            return Err("stop.ack_pattern required".into());
        }
        if !["contains", "regex"].contains(&stop["match_type"].as_str().unwrap_or("contains")) {
            return Err("stop.match_type invalid".into());
        }
        stop["baud_rate"] = json!(integer(
            stop.get("baud_rate").unwrap_or(&json!(115200)),
            "stop.baud_rate",
            300,
            4000000
        )?);
        if stop["send_format"].as_str().unwrap_or("string") == "hex" {
            hil_debug_core::capture::unhex(stop["send_data"].as_str().unwrap_or(""))?;
        }
        if !["string", "hex"].contains(&stop["send_format"].as_str().unwrap_or("string")) {
            return Err("stop.send_format invalid".into());
        }
        if !["none", "lf", "crlf"].contains(&stop["send_ending"].as_str().unwrap_or("none")) {
            return Err("stop.send_ending invalid".into());
        }
        if stop["match_type"].as_str().unwrap_or("contains") == "regex" {
            serial_regex(stop["ack_pattern"].as_str().unwrap())?;
        }
        stop["timeout_ms"] = json!(duration(stop.get("timeout_ms").unwrap_or(&json!(5000)))?);
        let raw = stop["port_name"].as_str().unwrap().trim();
        if raw.is_empty() {
            return Err("stop.port_name required".into());
        }
        let port = if raw.to_uppercase().starts_with("COM") {
            raw.to_uppercase()
        } else {
            raw.into()
        };
        let baud = stop["baud_rate"].as_u64().unwrap();
        if context.ports.get(&port).map_or(false, |b| *b != baud) {
            return Err("stop port has conflicting baud rate".into());
        }
        context.ports.insert(port.clone(), baud);
        stop["port_name"] = json!(port);
    }
    doc["steps"] = json!(steps);
    doc["loop_count"] = json!(loops);
    doc["schema_version"] = json!(if v3 { 3 } else { 2 });
    if let Some(resources) = resource_config {
        doc["_resource_config"] = resources;
    }
    if doc["name"].is_null() {
        doc["name"] = json!("HIL test");
    }
    doc["timeout_ms"] = json!(duration(doc.get("timeout_ms").unwrap_or(&json!(86400000)))?);
    doc["evidence"] = evidence;
    doc["_resources"] = json!({"ports":context.ports,"probes":context.probes});
    doc["_base_dir"] = json!(context.base.to_string_lossy());
    Ok(doc)
}
struct Context {
    base: PathBuf,
    bench: Value,
    ids: HashSet<String>,
    ports: BTreeMap<String, u64>,
    probes: BTreeSet<String>,
    count: usize,
    legacy: bool,
    stop: bool,
    v3: bool,
    device_id: Option<String>,
    instrument_mode: String,
}
impl Context {
    fn steps(&mut self, input: &Value, depth: usize) -> Result<Vec<Value>, String> {
        let array = input.as_array().ok_or("steps must be an array")?;
        if array.is_empty() || depth > 8 {
            return Err("Nonempty steps and nesting <= 8 required".into());
        }
        let mut output = vec![];
        for original in array {
            self.count += 1;
            if self.count > 1000 {
                return Err("Step definition limit".into());
            }
            keys(
                original,
                "id name action params enabled timeout_ms on_failure retry_count steps",
            )?;
            let mut s = original.clone();
            let a = match s["action"].as_str().ok_or("action is required")? {
                "firmware.flash" => "flash_firmware",
                "target.reset" => "reset_target",
                "serial.capture" => "serial_open",
                "serial.send" => "serial_send",
                "serial.expect" => "serial_wait_match",
                "test.observe" => "hil_observe",
                "memory.read" => "swd_read_block",
                "repeat" => "loop_block",
                a => a,
            }
            .to_string();
            s["action"] = json!(a);
            let specific=match a.as_str(){"delay"=>"delay_ms","loop_block"=>"count","serial_open"=>"port_name baud_rate","instrumentation_start"|"instrumentation_stop"|"instrumentation_assert"=>"port_name baud_rate mode timeout_ms budgets device_id control","serial_send"=>"port_name baud_rate send_data send_format send_ending character_delay_ms","serial_wait_match"=>"port_name baud_rate match_type pattern timeout_ms idle_timeout_ms","hil_observe"=>"port_name baud_rate timeout_ms boot_timeout_ms idle_timeout_ms boot_count continue_on_failure","protocol_request"=>"port_name baud_rate protocol values expected timeout_ms","flash_firmware"=>"probe_id target_device frequency pack_path flash_type file_path after_flash single_addr baud_rate port_name","reset_target"=>"probe_id target_device frequency pack_path port_name baud_rate reset_method pulse_ms pin_reset","swd_read_assert"=>"probe_id target_device frequency pack_path memory_addr read_width operator expected_value timeout_ms","swd_read_block"=>"probe_id target_device frequency pack_path memory_addr count symbol axf_path","svd_check_reg"=>"probe_id target_device frequency pack_path peripheral register field_name operator expected_reg_val timeout_ms",_=>return Err(format!("Unsupported action: {a}"))};
            let id = s["id"]
                .as_str()
                .map(str::to_string)
                .unwrap_or_else(|| format!("step_{}", self.count));
            if !regex::Regex::new(r"^[\w.-]{1,80}$").unwrap().is_match(&id)
                || !self.ids.insert(id.clone())
            {
                return Err("Invalid/duplicate step id".into());
            }
            s["id"] = json!(id);
            if s["name"].is_null() {
                s["name"] = s["id"].clone();
            }
            if s["enabled"].is_null() {
                s["enabled"] = json!(true);
            }
            if !s["enabled"].is_boolean() {
                return Err("enabled must be boolean".into());
            }
            let mut p = s.get("params").cloned().unwrap_or(json!({}));
            keys(
                &p,
                &if a == "flash_firmware" {
                    format!("{specific} pin_reset")
                } else {
                    specific.into()
                },
            )?;
            // Wrongly typed optional selectors must not silently choose a hardware operation.
            for key in ["send_format", "send_ending", "match_type", "reset_method",
                        "flash_type", "after_flash", "operator", "on_failure"] {
                if let Some(value) = p.get(key) {
                    if !value.is_string() { return Err(format!("{key} must be a string")); }
                }
            }
            if let Some(value) = s.get("on_failure") {
                if !value.is_string() { return Err("on_failure must be a string".into()); }
            }
            for (k, v) in self.bench.as_object().unwrap() {
                if specific.split_whitespace().any(|x| x == k) && (p[k].is_null() || p[k] == "") {
                    p[k] = v.clone();
                }
            }
            if self.legacy {
                for key in ["expected_value", "expected_reg_val"] {
                    if let Some(v) = p[key].as_str() {
                        if !v.is_empty() && v.bytes().all(|c| c.is_ascii_hexdigit()) {
                            p[key] = json!(format!("0x{v}"));
                        }
                    }
                }
            }
            if s["enabled"] == false {
                s["params"] = p;
                output.push(s);
                continue;
            }
            if a != "loop_block" && !s["steps"].is_null() {
                return Err("Only loop_block has child steps".into());
            }
            if a == "loop_block" {
                p["count"] = json!(integer(
                    p.get("count").unwrap_or(&json!(1)),
                    "count",
                    1,
                    10000
                )?);
                s["steps"] = json!(self.steps(&s["steps"], depth + 1)?);
            }
            if a.starts_with("instrumentation_") {
                if !self.v3 {
                    return Err("Instrumentation requires v3".into());
                }
                if p["device_id"].is_null() {
                    p["device_id"] = json!(self.device_id);
                }
                if p["device_id"].as_str().unwrap_or("").is_empty() {
                    return Err("Instrumentation needs explicit device_id".into());
                }
                if p["mode"].is_null() {
                    p["mode"] = json!(self.instrument_mode);
                }
                if !["binary", "text"].contains(&p["mode"].as_str().unwrap_or(""))
                    || p["control"].as_str().unwrap_or("passive") != "passive"
                {
                    return Err(
                        "UNSUPPORTED: active firmware control handshake is not installed".into(),
                    );
                }
                if a == "instrumentation_assert"
                    && p["budgets"].as_object().map_or(true, |b| b.is_empty())
                {
                    return Err("instrumentation_assert requires explicit budgets".into());
                }
                if let Some(budgets) = p["budgets"].as_object() {
                    for (id, budget) in budgets {
                        if id.parse::<u32>().is_err() {
                            return Err("Range budget ID must be a uint32 string".into());
                        }
                        keys(budget, "metric threshold unit min_samples")?;
                        if budget["metric"] != "elapsed"
                            || !["ns", "us", "ms"].contains(&budget["unit"].as_str().unwrap_or(""))
                        {
                            return Err("Only elapsed ns/us/ms budgets supported".into());
                        }
                        let threshold = budget["threshold"]
                            .as_f64()
                            .ok_or("Numeric budget threshold required")?;
                        if !threshold.is_finite() || threshold < 0. {
                            return Err("Nonnegative finite budget required".into());
                        }
                        integer(
                            budget.get("min_samples").unwrap_or(&json!(1)),
                            "min_samples",
                            1,
                            10000,
                        )?;
                    }
                } else if !p["budgets"].is_null() {
                    return Err("budgets must be an object".into());
                }
            }
            let serial = a.starts_with("serial_")
                || (a == "flash_firmware" && p["flash_type"] == "ing_ini")
                || a.starts_with("instrumentation_")
                || a == "hil_observe"
                || a == "protocol_request"
                || (a == "reset_target"
                    && p["reset_method"].as_str().unwrap_or("swd_soft_reset") != "swd_soft_reset");
            if serial {
                let raw = p["port_name"]
                    .as_str()
                    .filter(|s| !s.trim().is_empty())
                    .ok_or("Select explicit serial port")?;
                let port = if raw.to_uppercase().starts_with("COM") {
                    raw.trim().to_uppercase()
                } else {
                    raw.trim().into()
                };
                let baud = integer(
                    p.get("baud_rate").unwrap_or(&json!(115200)),
                    "baud_rate",
                    300,
                    4000000,
                )?;
                if self.ports.get(&port).map_or(false, |b| *b != baud) {
                    return Err("Conflicting baud rates".into());
                }
                self.ports.insert(port.clone(), baud);
                p["port_name"] = json!(port);
                p["baud_rate"] = json!(baud);
            }
            let swd = (a == "flash_firmware"
                && p["flash_type"].as_str().unwrap_or("pyocd") != "ing_ini")
                || matches!(
                    a.as_str(),
                    "swd_read_assert" | "swd_read_block" | "svd_check_reg"
                )
                || (a == "reset_target"
                    && p["reset_method"].as_str().unwrap_or("swd_soft_reset") == "swd_soft_reset");
            if swd {
                let probe = p["probe_id"]
                    .as_str()
                    .filter(|s| !s.is_empty())
                    .ok_or("probe_id is required")?;
                self.probes.insert(probe.into());
                if p["target_device"].as_str().unwrap_or("").is_empty() {
                    return Err("target_device is required".into());
                }
                p["frequency"] = json!(integer(
                    p.get("frequency").unwrap_or(&json!(1000000)),
                    "frequency",
                    1000,
                    50000000
                )?);
            }
            for k in ["file_path", "pack_path", "axf_path"] {
                if let Some(file) = p[k].as_str().filter(|s| !s.is_empty()) {
                    let file = self.base.join(file);
                    if !file.is_file() {
                        return Err(format!("{k}: file not found {}", file.display()));
                    }
                    p[k] = json!(file.to_string_lossy());
                }
            }
            if a == "flash_firmware" {
                let flash_type = p["flash_type"].as_str().unwrap_or("pyocd");
                let target = p["target_device"].as_str().unwrap_or("").trim()
                    .to_ascii_lowercase().replace(['-', '_'], "");
                if flash_type == "pyocd" && matches!(target.as_str(), "ing20" | "ing200" | "ing2000") {
                    return Err("ING20 SWD flashing is unsupported: bundled algorithm requires validation; external CLI cannot preserve cancellation, probe ownership, pack_path and after_flash".into());
                }
                let file = p["file_path"].as_str().ok_or("Firmware required")?;
                if flash_type == "ing_ini" {
                    if !file.to_lowercase().ends_with(".ini") {
                        return Err("ING HIL flashing requires an INI plan".into());
                    }
                    if p["port_name"].as_str().unwrap_or("").is_empty() {
                        return Err("ING HIL flashing requires port_name".into());
                    }
                    if !p["after_flash"].is_null() && p["after_flash"] != "halt" {
                        return Err("ING HIL keeps ISP idle after flashing; use an explicit reset_target step to start firmware".into());
                    }
                    crate::ing::prepare(&crate::ing::hil_request(&p, "preflight"))?;
                    if !p["pin_reset"].is_null() {
                        let pins: crate::reset::PinReset =
                            serde_json::from_value(p["pin_reset"].clone())
                                .map_err(|e| e.to_string())?;
                        pins.validate()?;
                    }
                } else if flash_type != "pyocd" {
                    return Err("Unsupported automated flash_type".into());
                }
                if flash_type == "pyocd"
                    && !["hex", "elf", "axf"].contains(
                        &Path::new(file)
                            .extension()
                            .and_then(|s| s.to_str())
                            .unwrap_or("")
                            .to_lowercase()
                            .as_str(),
                    )
                {
                    return Err("Addressed HEX/ELF/AXF required".into());
                }
                if !["halt", "reset", "none"].contains(&p["after_flash"].as_str().unwrap_or("halt"))
                {
                    return Err("Invalid after_flash".into());
                }
            }
            if a == "reset_target"
                && p["reset_method"].as_str().unwrap_or("swd_soft_reset") != "swd_soft_reset"
            {
                if !["pin_dtr_pulse", "bootloader_reset"]
                    .contains(&p["reset_method"].as_str().unwrap_or(""))
                {
                    return Err("Unsupported reset method".into());
                }
                let mut config = p["pin_reset"].clone();
                if !config.is_object() {
                    return Err("Verified pin_reset board profile required".into());
                }
                if let Some(pulse) = p.get("pulse_ms") {
                    config["pulse_ms"] = json!(duration(pulse)?);
                }
                let config: crate::reset::PinReset = serde_json::from_value(config)
                    .map_err(|e| format!("Board pin_reset profile required: {e}"))?;
                config.validate()?;
                p["pin_reset"] = json!(config);
            }
            if a == "swd_read_assert" || a == "swd_read_block" {
                if p["symbol"].is_null() {
                    p["memory_addr"] = json!(integer(
                        &p["memory_addr"],
                        "memory_addr",
                        0,
                        u32::MAX as u64
                    )?);
                } else if p["axf_path"].is_null() {
                    return Err("symbol requires axf_path".into());
                }
                if a == "swd_read_block" {
                    p["count"] = json!(integer(
                        p.get("count").unwrap_or(&json!(256)),
                        "count",
                        1,
                        4096
                    )?);
                } else {
                    let w = integer(p.get("read_width").unwrap_or(&json!(32)), "width", 8, 32)?;
                    if ![8, 16, 32].contains(&w) {
                        return Err("width must be 8/16/32".into());
                    }
                    p["read_width"] = json!(w);
                    p["expected_value"] = json!(integer(
                        &p["expected_value"],
                        "expected_value",
                        0,
                        (1u64 << w) - 1
                    )?);
                }
            }
            if a == "swd_read_assert" || a == "swd_read_block" {
                if let Some(address) = p["memory_addr"].as_u64() {
                    let count = if a == "swd_read_assert" { p["read_width"].as_u64().unwrap() / 8 }
                        else { p["count"].as_u64().unwrap() };
                    if address + count > u32::MAX as u64 + 1 {
                        return Err("Memory read crosses 32-bit address space".into());
                    }
                    if a == "swd_read_assert" && address % count != 0 {
                        return Err("Memory assertion address must be aligned to read_width".into());
                    }
                }
            }
            if a == "svd_check_reg" {
                if p["peripheral"].as_str().unwrap_or("").is_empty()
                    || p["register"].as_str().unwrap_or("").is_empty()
                {
                    return Err("SVD peripheral/register required".into());
                }
                p["expected_reg_val"] = json!(integer(
                    &p["expected_reg_val"],
                    "expected_reg_val",
                    0,
                    u32::MAX as u64
                )?);
            }
            if matches!(a.as_str(), "swd_read_assert" | "svd_check_reg")
                && !["==", "!=", ">", "<", ">=", "<=", "mask"]
                    .contains(&p["operator"].as_str().unwrap_or("=="))
            {
                return Err("Invalid operator".into());
            }
            if a == "serial_wait_match" {
                let pattern = p["pattern"]
                    .as_str()
                    .filter(|s| !s.is_empty() && s.len() <= 4096)
                    .ok_or("Nonempty pattern required")?;
                match p["match_type"].as_str().unwrap_or("contains") {
                    "regex" => {
                        serial_regex(pattern)?;
                    }
                    "contains" => {}
                    _ => return Err("Invalid match_type".into()),
                }
            }
            if a == "serial_send" {
                let text = p["send_data"].as_str().ok_or("send_data must be a string")?;
                if text.len() > 65536 {
                    return Err("send_data exceeds limit".into());
                }
                match p["send_format"].as_str().unwrap_or("string") {
                    "hex" => {
                        hil_debug_core::capture::unhex(text)?;
                    }
                    "string" => {}
                    _ => return Err("Invalid send_format".into()),
                }
                if !["none", "lf", "crlf"].contains(&p["send_ending"].as_str().unwrap_or("none")) {
                    return Err("Invalid send_ending".into());
                }
                if let Some(delay) = p.get("character_delay_ms") {
                    p["character_delay_ms"] = json!(integer(delay, "character_delay_ms", 0, 60000)?);
                }
            }
            if a == "protocol_request" {
                if let Some(path) = p["protocol"].as_str() {
                    p["protocol"] = read_document(&self.base.join(path))?;
                }
                let spec: hil_debug_core::protocol::Protocol =
                    serde_json::from_value(p["protocol"].clone()).map_err(|e| e.to_string())?;
                spec.encode(p["values"].as_object().ok_or("values object required")?)?;
                if p["expected"].as_object().map_or(true, |m| m.is_empty()) {
                    return Err("Nonempty expected fields required".into());
                }
            }
            for key in [
                "timeout_ms",
                "idle_timeout_ms",
                "boot_timeout_ms",
                "delay_ms",
                "pulse_ms",
            ] {
                if !p[key].is_null() {
                    p[key] = json!(duration(&p[key])?);
                }
            }
            if a == "hil_observe" {
                p["boot_count"] = json!(integer(
                    p.get("boot_count").unwrap_or(&json!(1)),
                    "boot_count",
                    1,
                    100
                )?);
                if !p["continue_on_failure"].is_null() && !p["continue_on_failure"].is_boolean() {
                    return Err("continue_on_failure must be boolean".into());
                }
            }
            let timeout = duration(
                s.get("timeout_ms")
                    .or(p.get("timeout_ms"))
                    .unwrap_or(&json!(if a == "flash_firmware" {
                        300000
                    } else if a == "hil_observe" {
                        1800000
                    } else {
                        3000
                    })),
            )?;
            s["timeout_ms"] = json!(timeout);
            if a == "reset_target" && serial {
                let pins = &p["pin_reset"];
                let required = pins["settle_ms"].as_u64().unwrap()
                    + pins["pulse_ms"].as_u64().unwrap()
                    + pins["boot_hold_ms"].as_u64().unwrap();
                if timeout <= required {
                    return Err(
                        "Reset step timeout must exceed settle + pulse + boot hold duration".into(),
                    );
                }
            }
            if a == "delay" && p["delay_ms"].as_u64().unwrap_or(500) > timeout {
                return Err("delay exceeds step timeout".into());
            }
            let failure = s["on_failure"]
                .as_str()
                .unwrap_or(if self.stop { "abort" } else { "continue" })
                .to_string();
            if !["abort", "continue", "retry"].contains(&failure.as_str()) {
                return Err("Invalid on_failure".into());
            }
            if failure == "retry"
                && !matches!(
                    a.as_str(),
                    "swd_read_assert" | "swd_read_block" | "svd_check_reg"
                )
            {
                return Err("Unsafe automatic retry".into());
            }
            s["on_failure"] = json!(failure);
            s["retry_count"] = json!(integer(
                s.get("retry_count").unwrap_or(&json!(0)),
                "retry_count",
                0,
                10
            )?);
            s["params"] = p;
            output.push(s);
        }
        Ok(output)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn reject_silent_parameter_coercion_and_invalid_memory_range() {
        for params in [json!({"send_data":23}), json!({"send_data":"x","send_format":false}),
            json!({"send_data":"x","character_delay_ms":-1}),
            json!({"send_data":"x","character_delay_ms":0.5}),
            json!({"send_data":"x","character_delay_ms":60001})] {
            let mut params = params;
            params["port_name"] = json!("COM_TEST");
            assert!(load_plan(&json!({"document":{"steps":[{"action":"serial_send","params":params}]}})).is_err());
        }
        for (action, address) in [("swd_read_assert", 1u64), ("swd_read_block", u32::MAX as u64)] {
            assert!(load_plan(&json!({"document":{"steps":[{"action":action,"params":
                if action == "swd_read_assert" { json!({"probe_id":"p","target_device":"t","memory_addr":address,"expected_value":0}) }
                else { json!({"probe_id":"p","target_device":"t","memory_addr":address,"count":2}) }}]}})).is_err());
        }
        let plan = load_plan(&json!({"document":{"steps":[{"action":"serial_send","params":
            {"port_name":"COM_TEST","send_data":"x","character_delay_ms":"5"}}]}})).unwrap();
        assert_eq!(plan["steps"][0]["params"]["character_delay_ms"], 5);
    }
    #[test]
    fn unsupported_ing20_flash_is_rejected_before_job_or_probe_access() {
        let path = std::env::temp_dir().join(format!("hil-preflight-flash-{}.hex", std::process::id()));
        std::fs::write(&path, b":00000001FF\n").unwrap();
        for name in ["ing20", "ING2000", " ing200 ", "ing-2000", "ING_200"] {
            for explicit in [false, true] {
                let mut params = json!({"probe_id":"fixture", "target_device":name, "file_path":path});
                if explicit { params["flash_type"] = json!("pyocd"); }
                let error = load_plan(&json!({"document":{"steps":[{"action":"flash_firmware","params":params}]}})).unwrap_err();
                assert!(error.contains("ING20 SWD flashing is unsupported"), "{error}");
            }
            assert!(load_plan(&json!({"document":{"steps":[{"action":"reset_target","params":
                {"probe_id":"fixture","target_device":name,"reset_method":"swd_soft_reset"}}]}})).is_ok());
        }
        assert!(load_plan(&json!({"document":{"steps":[{"action":"flash_firmware","params":
            {"probe_id":"fixture","target_device":"ing91800","file_path":path}}]}})).is_ok());
        std::fs::remove_file(path).unwrap();
    }
    #[test]
    fn defaults_aliases_and_legacy() {
        let plan = load_plan(
            &json!({"document":{"steps":[{"action":"delay","params":{"delay_ms":"20ms"}}]}}),
        )
        .unwrap();
        assert_eq!(plan["steps"][0]["params"]["delay_ms"], 20);
        assert!(load_plan(
            &json!({"document":{"steps":[{"action":"delay","on_failure":"retry"}]}})
        )
        .is_err());
    }
    #[test]
    fn reject_unsupported_regex() {
        assert!(serial_regex("(?<=A)B").is_err());
        assert!(serial_regex("(?P<value>[0-9]+)").is_ok());
    }
    #[test]
    fn pin_boot_preflight_needs_profile_not_swd_and_preserves_timings() {
        let mut doc = json!({"schema_version":2,"steps":[{"action":"reset_target","params":{"port_name":"COM_TEST","reset_method":"bootloader_reset","pulse_ms":75}}]});
        assert!(load_plan(&json!({"document":doc})).is_err());
        doc["steps"][0]["params"]["pin_reset"] = json!({"profile_id":"board-fixture","wiring_verified":true,"reset_asserted_dtr":true,"boot_asserted_rts":false,"settle_ms":100,"pulse_ms":100,"boot_hold_ms":50});
        let plan = load_plan(&json!({"document":doc})).unwrap();
        assert_eq!(plan["_resources"]["ports"]["COM_TEST"], 115200);
        assert_eq!(plan["_resources"]["probes"], json!([]));
        assert_eq!(plan["steps"][0]["params"]["pin_reset"]["pulse_ms"], 75);
        doc["steps"][0]["params"]["pin_reset"]["wiring_verified"] = json!(false);
        assert!(load_plan(&json!({"document":doc})).is_err());
    }
    #[test]
    fn ing_ini_is_serial_only_and_preflights_without_probe() {
        let root = std::env::temp_dir().join(format!("hil-ing-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        std::fs::write(root.join("app.bin"), [0xAA, 0x55]).unwrap();
        std::fs::write(root.join("flash.ini"), "[main]\nfamily=ing916\n[uart]\nbaud=115200\n[bin-0]\nname=app\nchecked=1\nfilename=app.bin\naddress=0x02004000\n").unwrap();
        let plan = load_plan(&json!({"base_dir":root,"document":{"steps":[{"action":"flash_firmware","timeout_ms":"30s","params":{"flash_type":"ing_ini","file_path":"flash.ini","port_name":"COM_TEST","after_flash":"halt"}}]}})).unwrap();
        assert_eq!(plan["_resources"]["probes"], json!([]));
        assert_eq!(plan["_resources"]["ports"]["COM_TEST"], 115200);
        let _ = std::fs::remove_dir_all(root);
    }
    #[test]
    fn v3_rejects_unavailable_power_before_run_and_accepts_passive_window() {
        let blocked = json!({"schema_version":3,"steps":[{"action":"reset_target","params":{"probe_id":"p","target_device":"t"}},{"action":"power_cycle"}]});
        assert!(load_plan(&json!({"document":blocked}))
            .unwrap_err()
            .contains("no production power"));
        let document = json!({"schema_version":3,"bench":{"devices":{"board":{"device_id":"b"},"uart":{"transport":"uart","port_name":"COM_TEST"}},"bindings":{"target":"board","console":"uart"}},"steps":[{"action":"instrumentation_start"},{"action":"instrumentation_assert","params":{"budgets":{"42":{"metric":"elapsed","threshold":10,"unit":"us","min_samples":1}}}}]});
        assert_eq!(
            load_plan(&json!({"document":document})).unwrap()["schema_version"],
            3
        );
    }
}
