use serde_json::{json, Map, Value};
use std::collections::{BTreeMap, VecDeque};

#[derive(Clone)]
pub struct Chunk {
    pub start: u64,
    pub data: Vec<u8>,
    pub elapsed_ms: f64,
}
pub struct Journal {
    chunks: VecDeque<Chunk>,
    pub end: u64,
    bytes: usize,
    pub error: Option<String>,
}
impl Default for Journal {
    fn default() -> Self {
        Self {
            chunks: VecDeque::new(),
            end: 0,
            bytes: 0,
            error: None,
        }
    }
}
impl Journal {
    pub fn append(&mut self, data: &[u8], elapsed_ms: f64) {
        for data in data.chunks(4096) {
            self.chunks.push_back(Chunk {
                start: self.end,
                data: data.into(),
                elapsed_ms,
            });
            self.end += data.len() as u64;
            self.bytes += data.len();
        }
        while self.bytes > 1024 * 1024 || self.chunks.len() > 16384 {
            if let Some(c) = self.chunks.pop_front() {
                self.bytes -= c.data.len();
            }
        }
    }
    pub fn read(&self, cursor: u64) -> Result<(Vec<Chunk>, u64), String> {
        if let Some(e) = &self.error {
            return Err(e.clone());
        }
        if cursor < self.chunks.front().map_or(self.end, |c| c.start) {
            return Err("Serial journal overrun".into());
        }
        Ok((
            self.chunks
                .iter()
                .filter(|c| c.start + c.data.len() as u64 > cursor)
                .map(|c| {
                    let mut c = c.clone();
                    let skip = cursor.saturating_sub(c.start) as usize;
                    c.data = c.data[skip..].into();
                    c.start += skip as u64;
                    c
                })
                .collect(),
            self.end,
        ))
    }
}
pub struct HilObserver {
    pub boots: u64,
    pub last_hb: f64,
    pub done: Option<Value>,
    pub failures: Vec<String>,
    pending: Vec<u8>,
    started: f64,
    last_boot: Option<u64>,
    plan: Option<u64>,
    results: BTreeMap<String, String>,
    params: Value,
}
fn number(v: &Value, k: &str) -> Result<u64, String> {
    let text = v[k].as_str().ok_or_else(|| format!("Missing {k}"))?;
    if text.is_empty() || !text.bytes().all(|c| c.is_ascii_digit()) {
        return Err(format!("Invalid {k}"));
    }
    text.parse().map_err(|_| format!("Invalid {k}"))
}
impl HilObserver {
    pub fn new(params: Value, started: f64) -> Self {
        Self {
            boots: 0,
            last_hb: started,
            done: None,
            failures: vec![],
            pending: vec![],
            started,
            last_boot: None,
            plan: None,
            results: BTreeMap::new(),
            params,
        }
    }
    pub fn check_time(&self, now: f64) -> Result<(), String> {
        if self.boots == 0
            && now - self.started >= self.params["boot_timeout_ms"].as_f64().unwrap_or(10000.)
        {
            return Err("BOOT timeout".into());
        }
        if self.boots > 0
            && now - self.last_hb >= self.params["idle_timeout_ms"].as_f64().unwrap_or(15000.)
        {
            return Err("HB timeout: ordinary logs are not heartbeats".into());
        }
        Ok(())
    }
    pub fn feed(&mut self, data: &[u8], now: f64) -> Result<Vec<Value>, String> {
        self.pending.extend_from_slice(data);
        let mut events = vec![];
        while let Some(end) = self.pending.iter().position(|b| *b == b'\n') {
            if end > 65536 {
                return Err("Serial line exceeds 64 KiB".into());
            }
            let bytes: Vec<_> = self.pending.drain(..=end).collect();
            let line = String::from_utf8_lossy(&bytes)
                .trim_end_matches(['\r', '\n'])
                .to_string();
            if !line.starts_with("HILv1 ") {
                continue;
            }
            let mut words = line.split_whitespace();
            words.next();
            let event = words.next().ok_or("Malformed HIL event")?;
            let mut fields = Map::new();
            for word in words {
                let (k, v) = word.split_once('=').ok_or("Malformed HIL field")?;
                if k.is_empty() || v.is_empty() || fields.insert(k.into(), json!(v)).is_some() {
                    return Err("Invalid/duplicate HIL field".into());
                }
            }
            let f = Value::Object(fields);
            events.push(json!({"event":event,"fields":f,"line":line}));
            if self.done.is_some() {
                return Err("HIL event after DONE".into());
            }
            if event == "BOOT" {
                self.boots += 1;
                let n = number(&f, "boot")?;
                if self.last_boot.map_or(false, |last| n != last + 1) {
                    return Err("BOOT counter did not increment by one".into());
                }
                self.last_boot = Some(n);
                if self.boots > self.params["boot_count"].as_u64().unwrap_or(1) {
                    return Err("Unexpected device reset (extra BOOT)".into());
                }
                self.last_hb = now;
                continue;
            }
            if self.boots == 0 {
                return Err(format!("{event} arrived before BOOT"));
            }
            match event {
                "PLAN" => {
                    let n = number(&f, "total")?;
                    if n == 0 || self.plan.map_or(false, |old| old != n) {
                        return Err("Invalid/inconsistent PLAN".into());
                    }
                    self.plan = Some(n);
                }
                "HB" => self.last_hb = now,
                "RESULT" => {
                    let id = f["id"].as_str().ok_or("RESULT needs id")?;
                    let status = f["status"].as_str().ok_or("RESULT needs status")?;
                    if !["PASS", "FAIL"].contains(&status)
                        || self.results.insert(id.into(), status.into()).is_some()
                    {
                        return Err("Invalid/duplicate RESULT".into());
                    }
                    if status == "FAIL" {
                        self.failures.push(line);
                    }
                }
                "CRASH" => self.failures.push(line),
                "DONE" => {
                    let total = number(&f, "total")?;
                    let pass = number(&f, "pass")?;
                    let fail = number(&f, "fail")?;
                    let fault = number(&f, "fault")?;
                    if total == 0
                        || pass.checked_add(fail).and_then(|n| n.checked_add(fault)) != Some(total)
                        || self.plan.map_or(false, |p| p != total)
                    {
                        return Err("DONE counts inconsistent".into());
                    }
                    if !self.results.is_empty()
                        && (self
                            .results
                            .values()
                            .filter(|s| s.as_str() == "PASS")
                            .count() as u64
                            != pass
                            || self
                                .results
                                .values()
                                .filter(|s| s.as_str() == "FAIL")
                                .count() as u64
                                != fail)
                    {
                        return Err("RESULT counts differ from DONE".into());
                    }
                    if self.boots != self.params["boot_count"].as_u64().unwrap_or(1) {
                        return Err("BOOT count differs from expected".into());
                    }
                    if fail > 0 || fault > 0 {
                        self.failures.push(line);
                    }
                    self.done = Some(f);
                }
                _ => {}
            }
        }
        if self.pending.len() > 65536 {
            return Err("Serial line exceeds 64 KiB".into());
        }
        if !self.failures.is_empty() && self.params["continue_on_failure"] == false {
            return Err(self.failures[0].clone());
        }
        Ok(events)
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn split_and_counts() {
        let wire=b"HILv1 BOOT boot=7\nHILv1 PLAN total=1\nHILv1 RESULT id=1 status=PASS\nHILv1 DONE total=1 pass=1 fail=0 fault=0\n";
        for n in 0..=wire.len() {
            let mut h = HilObserver::new(json!({}), 0.);
            h.feed(&wire[..n], 0.).unwrap();
            h.feed(&wire[n..], 1.).unwrap();
            assert!(h.done.is_some());
        }
    }
    #[test]
    fn noise_and_crash_never_pass() {
        let mut h = HilObserver::new(json!({"idle_timeout_ms":10}), 0.);
        h.feed(b"HILv1 BOOT boot=1\nnoise\nHILv1 CRASH id=1\n", 1.)
            .unwrap();
        assert!(h.check_time(20.).is_err());
        h.feed(b"HILv1 DONE total=1 pass=1 fail=0 fault=0\n", 21.)
            .unwrap();
        assert_eq!(h.failures.len(), 1);
    }
    #[test]
    fn journal_independent_cursors() {
        let mut j = Journal::default();
        j.append(b"BOOTDONE", 1.);
        assert_eq!(j.read(4).unwrap().0[0].data, b"DONE");
        assert_eq!(j.read(0).unwrap().0[0].data, b"BOOTDONE");
        j.append(&vec![0; 1024 * 1024], 2.);
        assert!(j.read(0).is_err());
    }
}
