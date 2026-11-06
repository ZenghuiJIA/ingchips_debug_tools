//! Session journal: immutable raw events, independent cursors and bounded disk recording.
use serde::{Deserialize, Serialize};
use std::collections::VecDeque;
use std::fs::{self, File};
use std::io::{BufRead, BufReader, BufWriter, Write, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex, atomic::{AtomicU64, Ordering}, mpsc::{sync_channel, SyncSender, TrySendError}};
use std::thread::JoinHandle;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

static GENERATION: AtomicU64 = AtomicU64::new(1);
pub fn wall_time_ms() -> u64 { SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_millis() as u64 }

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CaptureEvent {
    pub schema_version: u8,
    pub session_id: String,
    pub seq: u64,
    pub port: String,
    pub direction: String,
    pub elapsed_ms: f64,
    pub wall_time_ms: u64,
    pub data: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}
#[derive(Clone, Debug, Serialize)]
pub struct CaptureStatus {
    pub session_id: String,
    pub recording: bool,
    pub directory: Option<String>,
    pub error: Option<String>,
    pub latest_seq: u64,
    pub first_seq: u64,
}
#[derive(Serialize)]
pub struct CapturePage { pub events: Vec<CaptureEvent>, pub cursor: u64, pub gap: bool, pub status: CaptureStatus }

struct Recording { sender: SyncSender<CaptureEvent>, worker: JoinHandle<()>, directory: PathBuf }
pub struct Capture {
    pub session_id: String,
    port: String,
    started: Instant,
    seq: u64,
    ring: VecDeque<CaptureEvent>,
    bytes: usize,
    recording: Option<Recording>,
    error: Arc<Mutex<Option<String>>>,
    last_directory: Option<PathBuf>,
}
impl Capture {
    pub fn new(port: &str) -> Self {
        Self { session_id: format!("{}-{}-{}", std::process::id(), wall_time_ms(), GENERATION.fetch_add(1, Ordering::Relaxed)),
            port: port.into(), started: Instant::now(), seq: 0, ring: VecDeque::new(), bytes: 0,
            recording: None, error: Arc::new(Mutex::new(None)), last_directory: None }
    }
    pub fn append(&mut self, direction: &str, data: &[u8], message: Option<String>) {
        for chunk in if data.is_empty() { vec![&[][..]] } else { data.chunks(4096).collect() } {
            self.seq += 1;
            let event = CaptureEvent { schema_version: 1, session_id: self.session_id.clone(), seq: self.seq,
                port: self.port.clone(), direction: direction.into(), elapsed_ms: self.started.elapsed().as_secs_f64()*1000.,
                wall_time_ms: wall_time_ms(), data: hex(chunk), message: message.clone() };
            if let Some(recording) = &self.recording {
                match recording.sender.try_send(event.clone()) {
                    Ok(()) => {},
                    Err(TrySendError::Full(_)) => { *self.error.lock().unwrap() = Some("Recording queue overflow; file is incomplete".into()); },
                    Err(TrySendError::Disconnected(_)) => {
                        let mut err = self.error.lock().unwrap();
                        if err.is_none() { *err = Some("Recording writer stopped; file is incomplete".into()); }
                    },
                }
            }
            self.bytes += event.data.len() + event.message.as_ref().map_or(0, |s| s.len()) + 256;
            self.ring.push_back(event);
            while self.bytes > 2 * 1024 * 1024 || self.ring.len() > 10000 {
                if let Some(old) = self.ring.pop_front() { self.bytes -= old.data.len() + old.message.as_ref().map_or(0, |s| s.len()) + 256; }
            }
        }
    }
    pub fn status(&self) -> CaptureStatus {
        CaptureStatus { session_id: self.session_id.clone(), recording: self.recording.is_some(),
            directory: self.recording.as_ref().map(|r| r.directory.to_string_lossy().into_owned()).or_else(||self.last_directory.as_ref().map(|p|p.to_string_lossy().into_owned())),
            error: self.error.lock().unwrap().clone(), latest_seq: self.seq,
            first_seq: self.ring.front().map_or(self.seq + 1, |e| e.seq) }
    }
    pub fn elapsed_ms(&self) -> f64 { self.started.elapsed().as_secs_f64()*1000. }
    pub fn read(&self, after: u64, limit: usize) -> CapturePage {
        let events: Vec<_> = self.ring.iter().filter(|e| e.seq > after).take(limit.clamp(1, 1000)).cloned().collect();
        CapturePage { cursor: events.last().map_or(after, |e| e.seq), gap: after.saturating_add(1) < self.status().first_seq,
            events, status: self.status() }
    }
    pub fn start(&mut self, root: &Path, rotate_bytes: u64, max_bytes: u64) -> Result<CaptureStatus, String> {
        if self.recording.is_some() { return Err("Recording is already active".into()); }
        if rotate_bytes < 4096 || rotate_bytes > max_bytes || max_bytes > 16 * 1024 * 1024 * 1024 { return Err("Invalid recording limits".into()); }
        let directory = root.join(format!("session-{}-{}", self.session_id, self.seq));
        fs::create_dir_all(root).map_err(|e| e.to_string())?;
        fs::create_dir(&directory).map_err(|e| e.to_string())?;
        let initial = File::create(directory.join("events-00000.jsonl")).map_err(|e| e.to_string())?;
        let index_file=File::create(directory.join("offsets.jsonl")).map_err(|e|e.to_string())?;
        *self.error.lock().unwrap() = None;
        let (sender, receiver) = sync_channel::<CaptureEvent>(1024);
        let output = directory.clone(); let errors = self.error.clone();
        let worker = std::thread::spawn(move || {
            let result = (|| -> Result<(), String> {
                let mut file = BufWriter::new(initial); let mut volume = 0; let mut bytes = 0; let mut total = 0u64;
                let mut index=BufWriter::new(index_file);let mut event_index=0usize;
                loop {
                    match receiver.recv_timeout(std::time::Duration::from_millis(250)) {
                        Ok(event) => {
                            if errors.lock().unwrap().is_some() { return Err("Recording interrupted; file is incomplete".into()); }
                            let mut line = serde_json::to_vec(&event).map_err(|e| e.to_string())?; line.push(b'\n');
                            if total + line.len() as u64 > max_bytes { return Err("Recording size limit reached; file is incomplete".into()); }
                            if bytes > 0 && bytes + line.len() as u64 > rotate_bytes {
                                file.flush().map_err(|e| e.to_string())?; file.get_ref().sync_data().map_err(|e| e.to_string())?;
                                volume += 1;
                                file = BufWriter::new(File::create(output.join(format!("events-{volume:05}.jsonl"))).map_err(|e| e.to_string())?); bytes = 0;
                            }
                            if event_index%256==0{writeln!(index,"{}",serde_json::json!({"event_index":event_index,"volume":volume,"offset":bytes})).map_err(|e|e.to_string())?;}
                            file.write_all(&line).map_err(|e| e.to_string())?;
                            event_index+=1;
                            bytes += line.len() as u64; total += line.len() as u64;
                        },
                        Err(std::sync::mpsc::RecvTimeoutError::Timeout) => { file.flush().map_err(|e| e.to_string())?;index.flush().map_err(|e|e.to_string())?; },
                        Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => break,
                    }
                }
                file.flush().map_err(|e| e.to_string())?; file.get_ref().sync_data().map_err(|e| e.to_string())?;
                index.flush().map_err(|e|e.to_string())?;index.get_ref().sync_data().map_err(|e|e.to_string())?;
                Ok(())
            })();
            if let Err(error) = result { *errors.lock().unwrap() = Some(error); }
            let error = errors.lock().unwrap().clone();
            let summary = serde_json::json!({"schema_version": 1, "complete": error.is_none(), "error": error});
            if let Err(error) = fs::write(output.join("manifest.json"), summary.to_string()) { *errors.lock().unwrap() = Some(error.to_string()); }
        });
        self.recording = Some(Recording { sender, worker, directory });
        self.last_directory = self.recording.as_ref().map(|r|r.directory.clone());
        self.append("INFO", &[], Some("Recording started; earlier ring data is not included".into()));
        Ok(self.status())
    }
    pub fn stop(&mut self) -> Result<CaptureStatus, String> {
        if let Some(recording) = self.recording.take() {
            drop(recording.sender);
            // Never hold a hardware I/O lock while calling this method.
            let deadline=Instant::now()+std::time::Duration::from_secs(3);
            while !recording.worker.is_finished() && Instant::now()<deadline {std::thread::sleep(std::time::Duration::from_millis(5));}
            if !recording.worker.is_finished(){*self.error.lock().unwrap()=Some("Writer flush deadline exceeded; completeness unknown".into());return Err("Writer flush deadline exceeded; completeness unknown".into());}
            recording.worker.join().map_err(|_| "Recording writer panicked".to_string())?;
        }
        Ok(self.status())
    }
}
impl Drop for Capture { fn drop(&mut self) { let _ = self.stop(); } }
pub fn hex(data: &[u8]) -> String { data.iter().map(|b| format!("{b:02x}")).collect() }
pub fn unhex(data: &str) -> Result<Vec<u8>, String> {
    let text: String = data.chars().filter(|c| !c.is_ascii_whitespace()).collect();
    if text.len() % 2 != 0 || !text.is_ascii() { return Err("HEX must contain complete byte pairs".into()); }
    text.as_bytes().chunks(2).map(|b| std::str::from_utf8(b).map_err(|e| e.to_string()).and_then(|s| u8::from_str_radix(s,16).map_err(|_| "Invalid HEX".into()))).collect()
}
pub fn read_recording(path: &Path, after: usize, limit: usize) -> Result<serde_json::Value, String> {
    let paths = if path.is_dir() {
        let mut paths: Vec<_> = fs::read_dir(path).map_err(|e| e.to_string())?.filter_map(Result::ok).map(|e| e.path())
            .filter(|p| p.file_name().unwrap_or_default().to_string_lossy().starts_with("events-") && p.extension().map_or(false, |x| x == "jsonl")).collect();
        paths.sort(); paths
    } else { vec![path.to_path_buf()] };
    if paths.is_empty() { return Err("No event files found".into()); }
    let mut events = Vec::new(); let mut count = 0usize; let mut warnings = Vec::new();
    let mut start_volume=0usize;let mut start_offset=0u64;
    let index_path=path.join("offsets.jsonl");
    if path.is_dir()&&index_path.is_file()&&after>0{
        if fs::metadata(&index_path).map_err(|e|e.to_string())?.len()<=4*1024*1024{
            for line in BufReader::new(File::open(index_path).map_err(|e|e.to_string())?).lines(){
                let Ok(line)=line else {break;};let Ok(item)=serde_json::from_str::<serde_json::Value>(&line) else {break;};
                if let (Some(n),Some(volume),Some(offset))=(item["event_index"].as_u64(),item["volume"].as_u64(),item["offset"].as_u64()){
                    if n as usize<=after && (volume as usize)<paths.len(){count=n as usize;start_volume=volume as usize;start_offset=offset;}
                    else {break;}
                }
            }
        }
    }
    for (volume,file) in paths.into_iter().enumerate().skip(start_volume) {
        let mut reader = BufReader::new(File::open(&file).map_err(|e| e.to_string())?);
        if volume==start_volume && start_offset>0 {reader.seek(SeekFrom::Start(start_offset)).map_err(|e|e.to_string())?;}
        loop {
            let mut line = Vec::new();
            use std::io::Read;
            let n = reader.by_ref().take(1024*1024 + 1).read_until(b'\n', &mut line).map_err(|e| e.to_string())?;
            if n == 0 { break; }
            if n > 1024 * 1024 { return Err("Event line exceeds 1 MiB".into()); }
            count += 1;
            if count <= after { continue; }
            match serde_json::from_slice::<serde_json::Value>(&line) {
                Ok(event) => events.push(event),
                Err(e) => warnings.push(format!("{}:{count}: {e}", file.display())),
            }
            if events.len() >= limit.clamp(1, 1000) { return Ok(serde_json::json!({"events":events,"cursor":count,"eof":false,"warnings":warnings})); }
        }
    }
    let manifest = path.join("manifest.json");
    if path.is_dir() && !manifest.exists() { warnings.push("No final manifest; recording may be incomplete".into()); }
    if manifest.exists() {
        let summary: serde_json::Value = serde_json::from_slice(&fs::read(manifest).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
        if summary["complete"] != true { warnings.push(format!("Incomplete recording: {}",summary["error"])); }
    }
    Ok(serde_json::json!({"events":events,"cursor":count,"eof":true,"warnings":warnings}))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn cursors_are_independent_and_overrun_is_explicit() {
        let mut c = Capture::new("test"); c.append("RX", b"BOOT\nDONE\n", None);
        assert_eq!(c.read(0,10).events.len(),1); assert_eq!(c.read(0,10).events.len(),1);
        assert_eq!(c.read(1,10).events.len(),0);
        for _ in 0..600 { c.append("RX", &[7;4096], None); }
        assert!(c.read(0,1).gap); assert!(c.bytes <= 2*1024*1024);
    }
    #[test] fn records_rx_tx_and_rotates_without_loss() {
        let mut c = Capture::new("test"); let root = std::env::temp_dir().join(format!("hil-capture-{}",c.session_id));
        let status = c.start(&root,4096,1024*1024).unwrap();
        for _ in 0..20 { c.append("TX", &[0x55;512], None); c.append("RX", &[0xaa;512], None); }
        c.stop().unwrap(); assert!(c.status().error.is_none());
        let page = read_recording(Path::new(status.directory.as_ref().unwrap()),0,100).unwrap();
        assert_eq!(page["events"].as_array().unwrap().len(),41); assert_eq!(page["warnings"],serde_json::json!([]));
        fs::remove_dir_all(root).unwrap();
    }
    #[test] fn invalid_hex_never_coerces() { assert!(unhex("A").is_err()); assert!(unhex("GG").is_err()); assert_eq!(unhex("AA 55").unwrap(),vec![170,85]); }
    #[test] fn disk_limit_is_not_reported_as_complete() {
        let mut c=Capture::new("test-limit");let root=std::env::temp_dir().join(format!("hil-capture-{}",c.session_id));
        let directory=c.start(&root,4096,4096).unwrap().directory.unwrap();
        c.append("RX",&[1;4096],None);c.stop().unwrap();
        assert!(c.status().error.is_some());let manifest:serde_json::Value=serde_json::from_slice(&fs::read(Path::new(&directory).join("manifest.json")).unwrap()).unwrap();
        assert_eq!(manifest["complete"],false);fs::remove_dir_all(root).unwrap();
    }
    #[test] fn indexed_pages_match_sequential_read_and_truncation_is_visible(){
        let mut c=Capture::new("indexed");let root=std::env::temp_dir().join(format!("hil-capture-{}",c.session_id));let dir=c.start(&root,4096,1024*1024).unwrap().directory.unwrap();
        for n in 0..600u16{c.append("RX",&n.to_le_bytes(),None);}c.stop().unwrap();
        let all=read_recording(Path::new(&dir),0,1000).unwrap();let page=read_recording(Path::new(&dir),257,50).unwrap();
        assert_eq!(&all["events"].as_array().unwrap()[257..307],page["events"].as_array().unwrap().as_slice());
        let broken=root.join("broken.jsonl");fs::write(&broken,b"{\"seq\":1}\n{\"seq\":").unwrap();let read=read_recording(&broken,0,10).unwrap();assert_eq!(read["events"].as_array().unwrap().len(),1);assert!(!read["warnings"].as_array().unwrap().is_empty());
        fs::remove_dir_all(root).unwrap();
    }
}
