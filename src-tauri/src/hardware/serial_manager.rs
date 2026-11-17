use serde::{Deserialize, Serialize};
use serialport::{SerialPort, SerialPortType, UsbPortInfo};
use std::collections::{HashMap, VecDeque};

const RETAINED_CAPTURES: usize = 8;
use std::io::{Read, Write};
use std::net::TcpStream;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter};
use hil_debug_core::capture::{Capture, CapturePage, CaptureStatus};
use hil_debug_core::protocol::{Protocol, Decoder};
fn values_equal(a:&serde_json::Value,b:&serde_json::Value)->bool { match (a.as_f64(),b.as_f64()){(Some(a),Some(b))=>a==b,_=>a==b} }

#[cfg(test)]mod transaction_tests{
    use super::*;
    fn fixture()->(Arc<SerialManager>,String,std::net::TcpListener){
        let listener=std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let stream=TcpStream::connect(listener.local_addr().unwrap()).unwrap();
        let manager=Arc::new(SerialManager::new());let capture=manager.new_capture("TEST");let id=capture.lock().unwrap().session_id.clone();
        manager.sessions.lock().unwrap().insert("TEST".into(),Arc::new(Mutex::new(PortSession{
            native:None,capture,decoder:Arc::new(Mutex::new(None)),legacy:Arc::new(Mutex::new(None)),transaction:Arc::new(Mutex::new(())),uncertain:false,used_requests:std::collections::HashSet::new(),request_cancel:Arc::new(AtomicBool::new(false)),request_id:None,
            port_name:"TEST".into(),baud_rate:115200,port:None,rtt_stream:Some(stream),is_daplink:false,is_running:Arc::new(AtomicBool::new(true)),dtr_state:Arc::new(AtomicBool::new(false)),rts_state:Arc::new(AtomicBool::new(false)),
        })));
        (manager,id,listener)
    }
    #[derive(Clone)]
    struct Lines(Arc<Mutex<Vec<(char, bool)>>>);
    impl Read for Lines { fn read(&mut self, _: &mut [u8]) -> std::io::Result<usize> { Ok(0) } }
    impl Write for Lines {
        fn write(&mut self, data: &[u8]) -> std::io::Result<usize> { Ok(data.len()) }
        fn flush(&mut self) -> std::io::Result<()> { Ok(()) }
    }
    impl SerialPort for Lines {
        fn name(&self) -> Option<String> { Some("TEST".into()) }
        fn baud_rate(&self) -> serialport::Result<u32> { Ok(115200) }
        fn data_bits(&self) -> serialport::Result<serialport::DataBits> { Ok(serialport::DataBits::Eight) }
        fn flow_control(&self) -> serialport::Result<serialport::FlowControl> { Ok(serialport::FlowControl::None) }
        fn parity(&self) -> serialport::Result<serialport::Parity> { Ok(serialport::Parity::None) }
        fn stop_bits(&self) -> serialport::Result<serialport::StopBits> { Ok(serialport::StopBits::One) }
        fn timeout(&self) -> Duration { Duration::from_millis(20) }
        fn set_baud_rate(&mut self, _: u32) -> serialport::Result<()> { Ok(()) }
        fn set_data_bits(&mut self, _: serialport::DataBits) -> serialport::Result<()> { Ok(()) }
        fn set_flow_control(&mut self, _: serialport::FlowControl) -> serialport::Result<()> { Ok(()) }
        fn set_parity(&mut self, _: serialport::Parity) -> serialport::Result<()> { Ok(()) }
        fn set_stop_bits(&mut self, _: serialport::StopBits) -> serialport::Result<()> { Ok(()) }
        fn set_timeout(&mut self, _: Duration) -> serialport::Result<()> { Ok(()) }
        fn write_request_to_send(&mut self, level: bool) -> serialport::Result<()> { self.0.lock().unwrap().push(('R', level)); Ok(()) }
        fn write_data_terminal_ready(&mut self, level: bool) -> serialport::Result<()> { self.0.lock().unwrap().push(('D', level)); Ok(()) }
        fn read_clear_to_send(&mut self) -> serialport::Result<bool> { Ok(false) }
        fn read_data_set_ready(&mut self) -> serialport::Result<bool> { Ok(false) }
        fn read_ring_indicator(&mut self) -> serialport::Result<bool> { Ok(false) }
        fn read_carrier_detect(&mut self) -> serialport::Result<bool> { Ok(false) }
        fn bytes_to_read(&self) -> serialport::Result<u32> { Ok(0) }
        fn bytes_to_write(&self) -> serialport::Result<u32> { Ok(0) }
        fn clear(&self, _: serialport::ClearBuffer) -> serialport::Result<()> { Ok(()) }
        fn try_clone(&self) -> serialport::Result<Box<dyn SerialPort>> { Ok(Box::new(self.clone())) }
        fn set_break(&self) -> serialport::Result<()> { Ok(()) }
        fn clear_break(&self) -> serialport::Result<()> { Ok(()) }
    }
    fn install_lines(manager: &SerialManager) -> Arc<Mutex<Vec<(char, bool)>>> {
        let lines = Arc::new(Mutex::new(vec![]));
        let session = manager.resolve_session(Some("TEST")).unwrap();
        let mut session = session.lock().unwrap();
        session.port = Some(Box::new(Lines(lines.clone())));
        session.is_daplink = true;
        lines
    }
    #[test]
    fn reset_keeps_adapter_sequence_and_excludes_other_operations() {
        for boot in [false, true] {
            let (manager, _, _listener) = fixture();
            let lines = install_lines(&manager);
            let mut waits = vec![];
            manager.execute_reset_with_wait(boot, Some("TEST"), |duration| {
                waits.push(duration.as_millis());
                assert!(manager.set_dtr(false, Some("TEST")).unwrap_err().contains("transaction"));
                assert!(manager.set_rts(false, Some("TEST")).unwrap_err().contains("transaction"));
                assert!(manager.write_data(b"x", Some("TEST")).unwrap_err().contains("transaction"));
                assert!(manager.execute_reset(false, Some("TEST")).unwrap_err().contains("transaction"));
            }).unwrap();
            assert_eq!(*lines.lock().unwrap(), vec![('R', boot), ('D', true), ('D', false)]);
            assert_eq!(waits, vec![if boot { 500 } else { 50 }, 100]);
        }
    }
    #[test]
    fn reset_close_reopen_never_pulses_replacement() {
        let (manager, _, _listener) = fixture();
        let original = install_lines(&manager);
        let (replacement, _, _peer) = fixture();
        let replacement_lines = install_lines(&replacement);
        let next = replacement.resolve_session(Some("TEST")).unwrap();
        let error = manager.execute_reset_with_wait(true, Some("TEST"), |_| {
            manager.close(Some("TEST")).unwrap();
            manager.sessions.lock().unwrap().insert("TEST".into(), next.clone());
        }).unwrap_err();
        assert!(error.contains("disconnected"));
        assert_eq!(*original.lock().unwrap(), vec![('R', true)]);
        assert!(replacement_lines.lock().unwrap().is_empty());
    }
    #[test]
    fn duplicate_rtt_is_rejected_without_changing_session() {
        let (manager, id, _listener) = fixture();
        assert!(manager.ensure_rtt_closed("TEST").is_err());
        assert_eq!(manager.capture("TEST").unwrap().lock().unwrap().session_id, id);
        manager.close(Some("TEST")).unwrap();
        assert!(manager.ensure_rtt_closed("TEST").is_ok());
    }
    #[test]
    fn capture_cache_is_bounded_and_live_sessions_survive_eviction() {
        let (manager, id, _listener) = fixture();
        let oldest = manager.new_capture("oldest");
        let weak = Arc::downgrade(&oldest);
        drop(oldest);
        for index in 0..100 {
            manager.register_capture(&format!("PORT-{index}"), Arc::new(Mutex::new(Capture::new("test"))));
            assert!(manager.captures.lock().unwrap().len() <= RETAINED_CAPTURES);
        }
        assert!(weak.upgrade().is_none());
        assert!(manager.capture("oldest").is_err());
        assert!(manager.capture("PORT-99").is_ok());
        assert_eq!(manager.capture("TEST").unwrap().lock().unwrap().session_id, id);
        let latest = manager.new_capture("PORT-99");
        assert!(Arc::ptr_eq(&latest, &manager.capture("PORT-99").unwrap()));
        assert_eq!(manager.captures.lock().unwrap().len(), RETAINED_CAPTURES);
    }
    #[test]
    fn old_worker_never_notifies_or_removes_replacement() {
        let (manager, _, _listener) = fixture();
        let old = manager.resolve_session(Some("TEST")).unwrap().lock().unwrap().is_running.clone();
        let (replacement, id, _listener2) = fixture();
        let next = replacement.resolve_session(Some("TEST")).unwrap();
        let running = next.lock().unwrap().is_running.clone();
        manager.sessions.lock().unwrap().insert("TEST".into(), next);
        assert!(!SerialManager::finish_session(&manager.sessions, "TEST", &old, "old", |_| panic!("stale event")));
        let mut called = false;
        assert!(SerialManager::finish_session(&manager.sessions, "TEST", &running, "current", |event| {
            assert!(manager.sessions.try_lock().is_err(), "enqueue must precede replacement insertion");
            assert_eq!(event.session_id.as_deref(), Some(id.as_str()));
            called = true;
        }));
        assert!(called);
        assert!(!SerialManager::finish_session(&manager.sessions, "TEST", &running, "duplicate", |_| panic!("duplicate event")));
    }
    #[test]
    fn explicit_close_emits_identity_once_and_legacy_events_deserialize() {
        let (manager, id, _listener) = fixture();
        let mut events = vec![];
        manager.close_inner_with_notify(None, "closed", |event| {
            assert!(manager.sessions.try_lock().is_err());
            events.push(event);
        }).unwrap();
        manager.close_inner_with_notify(None, "closed", |event| events.push(event)).unwrap();
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].session_id.as_deref(), Some(id.as_str()));
        let old: SerialDisconnectPayload = serde_json::from_value(serde_json::json!({"port":"TEST","reason":"old"})).unwrap();
        assert!(old.session_id.is_none());
    }
    #[test]
    fn failed_restore_never_emits_success() {
        let mut notified = false;
        assert!(SerialManager::finish_restore(Err("open failed".into()), || notified = true).is_err());
        assert!(!notified);
        SerialManager::finish_restore(Ok(()), || notified = true).unwrap();
        assert!(notified);
    }
    fn protocol()->Protocol{serde_json::from_value(serde_json::json!({"schema_version":1,"name":"echo","fixed_length":1,"fields":[{"name":"seq","offset":0,"type":"uint8"}]})).unwrap()}
    #[test]fn instant_response_and_stale_session_guard(){
        let(manager,id,listener)=fixture();let capture=manager.capture("TEST").unwrap();
        let peer=std::thread::spawn(move||{let(mut stream,_)=listener.accept().unwrap();stream.set_read_timeout(Some(Duration::from_secs(2))).unwrap();let mut byte=[0];stream.read_exact(&mut byte).unwrap();capture.lock().unwrap().append("RX",&byte,None);});
        let fields=serde_json::json!({"seq":3}).as_object().unwrap().clone();
        assert!(manager.protocol_request("TEST","stale","old",protocol(),fields.clone(),fields.clone(),100).unwrap_err().contains("stale"));
        let response=manager.protocol_request("TEST",&id,"one",protocol(),fields.clone(),fields.clone(),1000).unwrap();
        assert_eq!(response["frame"]["fields"]["seq"],3.);peer.join().unwrap();
        assert!(manager.write_guarded(&[1],Some("TEST"),Some("old-id")).is_err());
        assert!(manager.protocol_request("TEST",&id,"two",protocol(),fields.clone(),fields,100).unwrap_err().contains("already used"));
    }
    #[test]fn cancellation_has_request_identity_and_excludes_other_writes(){
        let(manager,id,listener)=fixture();let(_peer,_)=listener.accept().unwrap();
        let other=manager.clone();let session_id=id.clone();
        let task=std::thread::spawn(move||{let fields=serde_json::json!({"seq":1}).as_object().unwrap().clone();other.protocol_request("TEST",&session_id,"active",protocol(),fields.clone(),fields,1000)});
        let deadline=Instant::now()+Duration::from_secs(1);
        loop{if manager.resolve_session(Some("TEST")).unwrap().lock().unwrap().request_id.is_some(){break;}assert!(Instant::now()<deadline);std::thread::sleep(Duration::from_millis(1));}
        assert!(manager.write_guarded(&[2],Some("TEST"),Some(&id)).unwrap_err().contains("transaction"));
        assert!(manager.protocol_cancel("TEST",&id,"wrong-request").is_err());
        manager.protocol_cancel("TEST",&id,"active").unwrap();assert!(task.join().unwrap().unwrap_err().contains("cancelled"));
        assert!(manager.protocol_cancel("TEST",&id,"active").is_err());
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PortInfo {
    pub port_name: String,
    pub description: String,
    pub vid: Option<u16>,
    pub pid: Option<u16>,
    pub manufacturer: Option<String>,
    pub product: Option<String>,
    pub serial_number: Option<String>,
    pub is_daplink: bool,
    pub device_type: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerialRxPayload {
    #[serde(default)]
    pub session_id: Option<String>,
    pub port: String,
    pub data: Vec<u8>,
    pub timestamp_ms: u64,
}

use super::protocol_engine::{ProtocolConfig, ProtocolEngine};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WaveformPointsPayload {
    pub port: String,
    pub points: Vec<HashMap<String, f64>>,
    pub timestamp_ms: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerialDisconnectPayload {
    #[serde(default)]
    pub session_id: Option<String>,
    pub port: String,
    pub reason: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SerialFlashEventPayload {
    pub port: String,
    pub original_baud: Option<u32>,
    pub message: String,
}

/// A dedicated session for a single opened COM port or RTT TCP bridge
pub struct PortSession {
    pub native: Option<Arc<hil_runtime::serial::SerialSession>>,
    pub capture: Arc<Mutex<Capture>>,
    pub decoder: Arc<Mutex<Option<Decoder>>>,
    pub legacy: Arc<Mutex<Option<ProtocolEngine>>>,
    pub transaction: Arc<Mutex<()>>,
    pub uncertain: bool,
    pub used_requests: std::collections::HashSet<String>,
    pub request_cancel: Arc<AtomicBool>,
    pub request_id: Option<String>,
    pub port_name: String,
    pub baud_rate: u32,
    pub port: Option<Box<dyn SerialPort>>,
    pub rtt_stream: Option<TcpStream>,
    pub is_daplink: bool,
    pub is_running: Arc<AtomicBool>,
    pub dtr_state: Arc<AtomicBool>,
    pub rts_state: Arc<AtomicBool>,
}

impl PortSession {
    pub fn close(&mut self) {
        self.is_running.store(false, Ordering::SeqCst);
        if let Some(native)=self.native.take(){let _=native.close();}
        self.port = None;
        self.rtt_stream = None;
    }
}
struct RequestCleanup(Arc<Mutex<PortSession>>);
impl Drop for RequestCleanup { fn drop(&mut self){self.0.lock().unwrap().request_id=None;} }

pub struct SerialManager {
    pub protocol_engine: Arc<Mutex<Option<ProtocolEngine>>>, // Legacy network waveform adapter only.
    captures: Mutex<VecDeque<(String, Arc<Mutex<Capture>>)>>,
    lifecycle: Mutex<()>,
    sessions: Arc<Mutex<HashMap<String, Arc<Mutex<PortSession>>>>>,
    last_active_port: Arc<Mutex<Option<String>>>,
    pub waveform_source: Arc<Mutex<Option<String>>>,
}

impl SerialManager {
    pub fn new() -> Self {
        Self {
            protocol_engine: Arc::new(Mutex::new(None)),
            captures: Mutex::new(VecDeque::new()),
            lifecycle: Mutex::new(()),
            sessions: Arc::new(Mutex::new(HashMap::new())),
            last_active_port: Arc::new(Mutex::new(None)),
            waveform_source: Arc::new(Mutex::new(None)),
        }
    }

    pub fn set_protocol_config(&self, config_json: &str) -> Result<(), String> {
        let config: ProtocolConfig = serde_json::from_str(config_json)
            .map_err(|e| format!("Invalid protocol JSON config: {}", e))?;
        ProtocolEngine::validate(&config)?;
        let source=self.waveform_source.lock().unwrap().clone().ok_or("Select a waveform session first")?;
        if source.starts_with("TCP") || source.starts_with("UDP") {
            *self.protocol_engine.lock().unwrap()=Some(ProtocolEngine::new(config));return Ok(());
        }
        let session=self.resolve_session(Some(&source))?;
        let engine=session.lock().unwrap().legacy.clone();
        let mut engine_guard = engine.lock().unwrap();
        if let Some(engine) = engine_guard.as_mut() {
            engine.update_config(config);
        } else {
            *engine_guard = Some(ProtocolEngine::new(config));
        }
        Ok(())
    }

    fn register_capture(&self, port: &str, capture: Arc<Mutex<Capture>>) {
        // Live sessions own their capture independently. Only the most recent
        // eight captures are retained for post-disconnect inspection (<=16 MiB
        // of ring data); recording files are unaffected by cache eviction.
        let retired = {
            let mut captures = self.captures.lock().unwrap();
            let mut retired = Vec::new();
            if let Some(index) = captures.iter().position(|(name, _)| name == port) {
                retired.push(captures.remove(index).unwrap());
            }
            captures.push_back((port.into(), capture));
            while captures.len() > RETAINED_CAPTURES {
                retired.push(captures.pop_front().unwrap());
            }
            retired
        };
        // A last Capture reference may flush a recording in Drop; never do so
        // while holding the registry lock.
        drop(retired);
    }
    fn new_capture(&self, port: &str) -> Arc<Mutex<Capture>> {
        let capture = Arc::new(Mutex::new(Capture::new(port)));
        self.register_capture(port, capture.clone());
        capture
    }
    pub fn capture(&self, port: &str) -> Result<Arc<Mutex<Capture>>, String> {
        if let Ok(session) = self.resolve_session(Some(port)) {
            return Ok(session.lock().unwrap().capture.clone());
        }
        self.captures.lock().unwrap().iter().find(|(name, _)| name == port)
            .map(|(_, capture)| capture.clone()).ok_or_else(|| "No retained capture for this port".into())
    }
    pub fn capture_page(&self, port: &str, after: u64, limit: usize) -> Result<CapturePage, String> {
        Ok(self.capture(port)?.lock().unwrap().read(after, limit))
    }
    pub fn capture_record(&self, port: &str, start: bool, root: &std::path::Path) -> Result<CaptureStatus, String> {
        if start { self.resolve_session(Some(port))?; }
        let capture = self.capture(port)?;
        let mut capture = capture.lock().unwrap();
        if start { capture.start(root, 16 * 1024 * 1024, 1024 * 1024 * 1024) } else { capture.stop() }
    }
    pub fn configure_protocol(&self, port: &str, protocol: Protocol) -> Result<(), String> {
        let decoder = Decoder::new(protocol)?;
        let session = self.resolve_session(Some(port))?;
        let session = session.lock().unwrap();
        let _transaction = session.transaction.try_lock().map_err(|_|"A command transaction is active")?;
        *session.decoder.lock().unwrap() = Some(decoder);
        Ok(())
    }
    fn parse_frames(app: &AppHandle, port: &str, decoder: &Arc<Mutex<Option<Decoder>>>, capture: &Arc<Mutex<Capture>>, data: &[u8]) {
        let (capture_state,stamp) = {let capture=capture.lock().unwrap();(capture.status(),capture.elapsed_ms())};
        let mut lock = decoder.lock().unwrap();
        if let Some(decoder) = lock.as_mut() {
            match decoder.feed(data, stamp) {
                Ok(frames) if !frames.is_empty() => { let _=app.emit("protocol-frames", serde_json::json!({"port":port,"session_id":capture_state.session_id,"frames":frames,"timestamp_ms":hil_debug_core::capture::wall_time_ms()})); },
                Err(error) => { capture.lock().unwrap().append("ERROR",&[],Some(error)); },
                _=>{}
            }
        }
    }
    pub fn protocol_cancel(&self,port:&str,session_id:&str,request_id:&str)->Result<(),String>{
        let session=self.resolve_session(Some(port))?;let session=session.lock().unwrap();
        if session.capture.lock().unwrap().session_id!=session_id || session.request_id.as_deref()!=Some(request_id){return Err("Request has ended or belongs to another session".into());}
        session.request_cancel.store(true,Ordering::SeqCst);Ok(())
    }
    pub fn protocol_request(&self, port: &str, expected_session: &str, request_id:&str, protocol: Protocol, values: serde_json::Map<String,serde_json::Value>, expected: serde_json::Map<String,serde_json::Value>, timeout_ms:u64) -> Result<serde_json::Value,String> {
        if request_id.is_empty()||request_id.len()>128{return Err("Invalid request ID".into());}
        if timeout_ms==0||timeout_ms>30000||expected.is_empty(){return Err("Expected fields and timeout 1..30000 ms are required".into());}
        let mut decoder=Decoder::new(protocol.clone())?; let bytes=protocol.encode(&values)?;
        let fingerprint=serde_json::to_string(&serde_json::json!({"protocol":protocol,"expected":expected})).map_err(|e|e.to_string())?;
        let session=self.resolve_session(Some(port))?;
        let (transaction,capture)={let session=session.lock().unwrap();(session.transaction.clone(),session.capture.clone())};
        let _permit=transaction.try_lock().map_err(|_|"A command transaction is already active")?;
        {let mut session=session.lock().unwrap();if session.capture.lock().unwrap().session_id!=expected_session{return Err("Session changed; stale request rejected".into());}if session.uncertain{return Err("Previous transaction outcome is unknown; reconnect before another request".into());}
         if session.used_requests.contains(&fingerprint){return Err("Response identity already used; use a new sequence field to prevent delayed duplicate matches".into());}
         if session.used_requests.len()>=1024{return Err("Request identity limit reached; reconnect".into());}
         session.used_requests.insert(fingerprint);session.uncertain=true;
         session.request_cancel.store(false,Ordering::SeqCst);session.request_id=Some(request_id.into());}
        let _cleanup=RequestCleanup(session.clone());
        let mut cursor=capture.lock().unwrap().status().latest_seq;
        let start=Instant::now();
        self.write_core(&bytes,Some(port),Some(expected_session),true)?;
        loop {
            {let session=session.lock().unwrap();if session.request_cancel.load(Ordering::SeqCst){return Err("Request cancelled; outcome unknown, reconnect before another request".into());}if !session.is_running.load(Ordering::SeqCst){return Err("Disconnected during request".into());}}
            let page=capture.lock().unwrap().read(cursor,1000);
            if page.status.session_id!=expected_session||page.gap{return Err("Session changed or response data lost".into());}
            cursor=page.cursor;
            for event in page.events {
                if event.direction!="RX"{continue;}
                for frame in decoder.feed(&hil_debug_core::capture::unhex(&event.data)?,event.elapsed_ms)? {
                    if frame.valid && expected.iter().all(|(key,want)|frame.fields.get(key).map_or(false,|got|values_equal(got,want))) {
                        {let mut session=session.lock().unwrap();session.uncertain=false;session.request_id=None;}
                        return Ok(serde_json::json!({"status":"completed","session_id":expected_session,"duration_ms":start.elapsed().as_millis(),"tx":hil_debug_core::capture::hex(&bytes),"frame":frame}));
                    }
                }
            }
            if start.elapsed().as_millis()>=timeout_ms as u128 {session.lock().unwrap().uncertain=true;return Err("Response timeout; outcome unknown, no automatic resend".into());}
            std::thread::sleep(Duration::from_millis(5));
        }
    }
    pub fn clear_protocol(&self) {
        let source=self.waveform_source.lock().unwrap().clone();
        if let Some(source)=source{
            if source.starts_with("TCP")||source.starts_with("UDP"){*self.protocol_engine.lock().unwrap()=None;return;}
            if let Ok(session)=self.resolve_session(Some(&source)){*session.lock().unwrap().legacy.lock().unwrap()=None;}
        }
    }

    pub fn set_waveform_source(&self, port_name: Option<String>) {
        let mut source_guard = self.waveform_source.lock().unwrap();
        *source_guard = port_name;
    }

    pub fn get_waveform_source(&self) -> Option<String> {
        self.waveform_source.lock().unwrap().clone()
    }

    pub fn list_ports() -> Vec<PortInfo> {
        let ports = serialport::available_ports().unwrap_or_default();
        let mut result: Vec<PortInfo> = ports
            .into_iter()
            .map(|p| {
                let mut vid = None;
                let mut pid = None;
                let mut manufacturer = None;
                let mut product = None;
                let mut serial_number = None;
                let mut is_daplink = false;
                let mut device_type = "generic".to_string();

                if let SerialPortType::UsbPort(UsbPortInfo {
                    vid: v,
                    pid: pi,
                    serial_number: ref s,
                    manufacturer: ref m,
                    product: ref pr,
                }) = p.port_type
                {
                    vid = Some(v);
                    pid = Some(pi);
                    serial_number = s.clone();
                    manufacturer = m.clone();
                    product = pr.clone();

                    let pr_lower = pr.as_deref().unwrap_or("").to_lowercase();
                    let m_lower = m.as_deref().unwrap_or("").to_lowercase();

                    if v == 0x0D28
                        || pr_lower.contains("cmsis")
                        || pr_lower.contains("daplink")
                        || pr_lower.contains("dap")
                        || m_lower.contains("cmsis")
                        || m_lower.contains("dap")
                    {
                        is_daplink = true;
                        device_type = "daplink".to_string();
                    } else if v == 0x1366 || pr_lower.contains("j-link") || pr_lower.contains("jlink") {
                        device_type = "jlink".to_string();
                    } else {
                        device_type = "usb_serial".to_string();
                    }
                }

                PortInfo {
                    port_name: p.port_name.clone(),
                    description: match &p.port_type {
                        SerialPortType::UsbPort(usb) => {
                            let mut desc_parts = Vec::new();
                            if let Some(mfg) = &usb.manufacturer {
                                desc_parts.push(mfg.as_str());
                            }
                            if let Some(prod) = &usb.product {
                                desc_parts.push(prod.as_str());
                            }
                            if desc_parts.is_empty() {
                                "USB 虚拟串口设备".to_string()
                            } else {
                                desc_parts.join(" ")
                            }
                        }
                        SerialPortType::PciPort => "PCI 板载硬件串口".to_string(),
                        SerialPortType::BluetoothPort => "蓝牙无线串口 (SPP)".to_string(),
                        SerialPortType::Unknown => "系统通信端口 (COM)".to_string(),
                    },
                    vid,
                    pid,
                    manufacturer,
                    product,
                    serial_number,
                    is_daplink,
                    device_type,
                }
            })
            .collect();

        // Virtual SEGGER RTT options
        result.push(PortInfo {
            port_name: "RTT (J-Link 实时传输)".to_string(),
            description: "SEGGER J-Link 高速 RTT 虚拟串口通道".to_string(),
            vid: Some(0x1366),
            pid: None,
            manufacturer: Some("SEGGER".to_string()),
            product: Some("J-Link RTT Stream".to_string()),
            serial_number: None,
            is_daplink: false,
            device_type: "rtt_jlink".to_string(),
        });

        result.push(PortInfo {
            port_name: "RTT (DAPLink 实时传输)".to_string(),
            description: "DAPLink / CMSIS-DAP SWD 内存轮询 RTT 通道".to_string(),
            vid: Some(0x0D28),
            pid: None,
            manufacturer: Some("ARM".to_string()),
            product: Some("DAPLink RTT Stream".to_string()),
            serial_number: None,
            is_daplink: false,
            device_type: "rtt_daplink".to_string(),
        });

        result
    }

    pub fn list_active_sessions(&self) -> Vec<String> {
        let sessions = self.sessions.lock().unwrap();
        sessions.keys().cloned().collect()
    }

    /// Return a read-only snapshot for the desktop bridge.  MCP and other
    /// agents may inspect this state without acquiring the session transaction
    /// or changing the UI-owned connection.
    pub fn session_snapshots(&self) -> Vec<serde_json::Value> {
        let sessions = self.sessions.lock().unwrap();
        sessions.iter().map(|(port, session_arc)| {
            let session = session_arc.lock().unwrap();
            let status = session.capture.lock().unwrap().status();
            serde_json::json!({
                "port": port,
                "owner": "desktop-ui",
                "session_id": status.session_id,
                "baudrate": session.baud_rate,
                "is_running": session.is_running.load(Ordering::SeqCst),
                "dtr": session.dtr_state.load(Ordering::SeqCst),
                "rts": session.rts_state.load(Ordering::SeqCst),
                "is_daplink": session.is_daplink,
                "latest_seq": status.latest_seq,
                "first_seq": status.first_seq,
                "recording": status.recording,
                "capture_error": status.error
            })
        }).collect()
    }

    fn ensure_rtt_closed(&self, port_name: &str) -> Result<(), String> {
        if self.sessions.lock().unwrap().get(port_name).map_or(false, |s| s.lock().unwrap().is_running.load(Ordering::SeqCst)) {
            return Err("RTT session is already open; disconnect before reconnecting".into());
        }
        Ok(())
    }

    pub fn open_rtt(
        &self,
        app: AppHandle,
        port_name: &str,
        tcp_port: u16,
    ) -> Result<(), String> {
        self.open_rtt_prepared(app, port_name, || Ok(tcp_port))
    }

    pub fn open_rtt_prepared(&self, app: AppHandle, port_name: &str, prepare: impl FnOnce() -> Result<u16, String>) -> Result<(), String> {
        let _lifecycle = self.lifecycle.lock().unwrap();
        self.ensure_rtt_closed(port_name)?;
        let tcp_port = prepare()?;
        if tcp_port == 0 { return Err("Invalid RTT TCP bridge port".into()); }
        self.close_inner(Some(port_name))?;

        let address = std::net::SocketAddr::from(([127, 0, 0, 1], tcp_port));
        let stream = TcpStream::connect_timeout(&address, Duration::from_secs(3))
            .map_err(|e| format!("Failed to connect to RTT TCP bridge (port {}): {}", tcp_port, e))?;
        stream.set_read_timeout(Some(Duration::from_millis(50))).map_err(|e| e.to_string())?;
        stream.set_write_timeout(Some(Duration::from_secs(1))).map_err(|e| e.to_string())?;

        let reader_stream = stream.try_clone().map_err(|e| e.to_string())?;

        let is_running = Arc::new(AtomicBool::new(true));
        let capture = self.new_capture(port_name);
        let decoder = Arc::new(Mutex::new(None));
        let legacy = Arc::new(Mutex::new(None));
        let session = Arc::new(Mutex::new(PortSession {
            native: None,
            legacy: legacy.clone(),
            decoder: decoder.clone(), transaction: Arc::new(Mutex::new(())), uncertain: false, used_requests: std::collections::HashSet::new(), request_cancel: Arc::new(AtomicBool::new(false)), request_id:None,
            capture: capture.clone(),
            port_name: port_name.to_string(),
            baud_rate: 115200,
            port: None,
            rtt_stream: Some(stream),
            is_daplink: false,
            is_running: Arc::clone(&is_running),
            dtr_state: Arc::new(AtomicBool::new(false)),
            rts_state: Arc::new(AtomicBool::new(false)),
        }));

        {
            let mut sessions_guard = self.sessions.lock().unwrap();
            sessions_guard.insert(port_name.to_string(), Arc::clone(&session));
            let mut last_active = self.last_active_port.lock().unwrap();
            *last_active = Some(port_name.to_string());
            // If waveform source not set, bind default
            let mut wf_guard = self.waveform_source.lock().unwrap();
            if wf_guard.is_none() {
                *wf_guard = Some(port_name.to_string());
            }
        }

        let is_running_clone = Arc::clone(&is_running);
        let current_port_name = port_name.to_string();
        let protocol_engine_clone = legacy;
        let waveform_source_clone = Arc::clone(&self.waveform_source);
        let sessions_clone = Arc::clone(&self.sessions);

        // Background reader thread for RTT TCP stream
        std::thread::spawn(move || {
            let mut reader = reader_stream;
            let mut batch_buffer: Vec<u8> = Vec::with_capacity(4096);
            let mut read_buf = [0u8; 1024];
            let mut last_flush = Instant::now();

            while is_running_clone.load(Ordering::SeqCst) {
                match reader.read(&mut read_buf) {
                    Ok(n) if n > 0 => {
                        let incoming = &read_buf[..n];
                        capture.lock().unwrap().append("RX", incoming, None);
                        Self::parse_frames(&app, &current_port_name, &decoder, &capture, incoming);

                        // If waveform is bound to this port, feed to protocol engine
                        let is_target_wf = {
                            if let Ok(wf_guard) = waveform_source_clone.lock() {
                                wf_guard.as_deref() == Some(&current_port_name) || wf_guard.is_none()
                            } else {
                                false
                            }
                        };

                        if is_target_wf {
                            let mut parsed_points = Vec::new();
                            {
                                if let Ok(mut engine_opt) = protocol_engine_clone.lock() {
                                    if let Some(engine) = engine_opt.as_mut() {
                                        parsed_points = engine.parse_chunk(incoming);
                                    }
                                }
                            }
                            if !parsed_points.is_empty() {
                                let now_ms = std::time::SystemTime::now()
                                    .duration_since(std::time::UNIX_EPOCH)
                                    .unwrap_or_default()
                                    .as_millis() as u64;
                                let points_payload = WaveformPointsPayload {
                                    port: current_port_name.clone(),
                                    points: parsed_points,
                                    timestamp_ms: now_ms,
                                };
                                let _ = app.emit("waveform-points", points_payload);
                            }
                        }

                        batch_buffer.extend_from_slice(incoming);
                    }
                    Ok(_) => { break; }
                    Err(ref e) if e.kind() == std::io::ErrorKind::TimedOut || e.kind() == std::io::ErrorKind::WouldBlock => {}
                    Err(_) => {
                        break;
                    }
                }

                let should_flush = !batch_buffer.is_empty()
                    && (batch_buffer.len() >= 2048 || last_flush.elapsed() >= Duration::from_millis(30));

                if should_flush {
                    let now_ms = std::time::SystemTime::now()
                        .duration_since(std::time::UNIX_EPOCH)
                        .unwrap_or_default()
                        .as_millis() as u64;

                    let payload = SerialRxPayload {
                        session_id: Some(capture.lock().unwrap().session_id.clone()),
                        port: current_port_name.clone(),
                        data: std::mem::take(&mut batch_buffer),
                        timestamp_ms: now_ms,
                    };

                    let _ = app.emit("serial-rx", payload);
                    last_flush = Instant::now();
                }

                std::thread::sleep(Duration::from_millis(2));
            }
            is_running_clone.store(false, Ordering::SeqCst);
            capture.lock().unwrap().append("INFO", &[], Some("Connection closed".into()));
            let _ = capture.lock().unwrap().stop();
            Self::finish_session(&sessions_clone, &current_port_name, &is_running_clone, "采样/RTT 连接已结束", |payload| {
                if !batch_buffer.is_empty() {
                    let _ = app.emit("serial-rx", SerialRxPayload { session_id: payload.session_id.clone(), port: current_port_name.clone(), data: batch_buffer,
                        timestamp_ms: hil_debug_core::capture::wall_time_ms() });
                }
                let _ = app.emit("serial-disconnected", payload);
            });
        });

        Ok(())
    }

    pub fn open(&self, app: AppHandle, port_name: &str, baud_rate: u32) -> Result<(), String> {
        let _lifecycle = self.lifecycle.lock().unwrap();
        if super::ing_flasher::FLASH_PORT.lock().unwrap().as_deref() == Some(port_name) { return Err("串口正在用于烧录".into()); }
        if let Some(existing)=self.sessions.lock().unwrap().get(port_name) {
            let s=existing.lock().unwrap();
            if s.is_running.load(Ordering::SeqCst) {
                return if s.baud_rate==baud_rate { Ok(()) } else { Err("串口以不同波特率使用，请先断开".into()) };
            }
        }
        let _=self.close_inner(Some(port_name));
        let decoder:Arc<Mutex<Option<Decoder>>>=Arc::new(Mutex::new(None));
        let legacy:Arc<Mutex<Option<ProtocolEngine>>>=Arc::new(Mutex::new(None));
        let capture_slot:Arc<Mutex<Option<Arc<Mutex<Capture>>>>> = Arc::new(Mutex::new(None));
        let slot=capture_slot.clone();let d=decoder.clone();let l=legacy.clone();let source=self.waveform_source.clone();
        let target=port_name.to_string();let app_rx=app.clone();
        let native=hil_runtime::serial::SerialSession::open(port_name,baud_rate,Some(Arc::new(move|bytes,_|{
            let capture=slot.lock().unwrap().clone();
            if let Some(capture)=capture {
                Self::parse_frames(&app_rx,&target,&d,&capture,bytes);
                let selected=source.lock().unwrap().clone();
                if selected.as_deref()==Some(target.as_str()) {
                    if let Some(engine)=l.lock().unwrap().as_mut() {
                        let points=engine.parse_chunk(bytes);
                        if !points.is_empty(){let _=app_rx.emit("waveform-points",WaveformPointsPayload{port:target.clone(),points,timestamp_ms:hil_debug_core::capture::wall_time_ms()});}
                    }
                }
                let _=app_rx.emit("serial-rx",SerialRxPayload{session_id:Some(capture.lock().unwrap().session_id.clone()),port:target.clone(),data:bytes.into(),timestamp_ms:hil_debug_core::capture::wall_time_ms()});
            }
        })))?;
        let capture=native.capture.clone();*capture_slot.lock().unwrap()=Some(capture.clone());
        self.register_capture(port_name, capture.clone());
        let running=native.running.clone();
        let is_daplink=Self::list_ports().iter().find(|p|p.port_name.eq_ignore_ascii_case(port_name)).map_or(false,|p|p.is_daplink);
        let session=Arc::new(Mutex::new(PortSession{
            native:Some(native),capture,decoder,legacy,transaction:Arc::new(Mutex::new(())),uncertain:false,
            used_requests:std::collections::HashSet::new(),request_cancel:Arc::new(AtomicBool::new(false)),request_id:None,
            port_name:port_name.into(),baud_rate,port:None,rtt_stream:None,is_daplink,is_running:running.clone(),
            dtr_state:Arc::new(AtomicBool::new(false)),rts_state:Arc::new(AtomicBool::new(false)),
        }));
        self.sessions.lock().unwrap().insert(port_name.into(),session);
        *self.last_active_port.lock().unwrap()=Some(port_name.into());
        if self.waveform_source.lock().unwrap().is_none(){*self.waveform_source.lock().unwrap()=Some(port_name.into());}
        let sessions=self.sessions.clone();let name=port_name.to_string();
        std::thread::spawn(move||{
            while running.load(Ordering::SeqCst){std::thread::sleep(Duration::from_millis(100));}
            Self::finish_session(&sessions, &name, &running, "串口连接已断开", |payload| {
                let _ = app.emit("serial-disconnected", payload);
            });
        });
        Ok(())
    }

    // Identity check, map removal and event enqueue form one critical section.
    // Otherwise a replacement may open between removal and the old notification.
    fn finish_session(
        sessions: &Mutex<HashMap<String, Arc<Mutex<PortSession>>>>,
        port: &str, running: &Arc<AtomicBool>, reason: &str,
        notify: impl FnOnce(SerialDisconnectPayload),
    ) -> bool {
        let mut map = sessions.lock().unwrap();
        let Some(current) = map.get(port) else { return false; };
        let session_id = {
            let session = current.lock().unwrap();
            if !Arc::ptr_eq(&session.is_running, running) { return false; }
            let id = session.capture.lock().unwrap().session_id.clone();
            id
        };
        map.remove(port);
        notify(SerialDisconnectPayload { session_id: Some(session_id), port: port.into(), reason: reason.into() });
        true
    }

    pub fn close(&self, port_name: Option<&str>) -> Result<(), String> {
        let _lifecycle = self.lifecycle.lock().unwrap();
        self.close_inner(port_name)
    }

    pub fn close_and_notify(&self, app: &AppHandle, port_name: Option<&str>, reason: &str) -> Result<(), String> {
        let _lifecycle = self.lifecycle.lock().unwrap();
        self.close_inner_with_notify(port_name, reason, |payload| { let _ = app.emit("serial-disconnected", payload); })
    }

    fn close_inner(&self, port_name: Option<&str>) -> Result<(), String> {
        self.close_inner_with_notify(port_name, "连接已关闭", |_| {})
    }

    fn close_inner_with_notify(&self, port_name: Option<&str>, reason: &str, mut notify: impl FnMut(SerialDisconnectPayload)) -> Result<(), String> {
        let mut sessions = self.sessions.lock().unwrap();
        let targets: Vec<String> = match port_name {
            Some(port) => vec![port.into()],
            None => sessions.keys().cloned().collect(),
        };
        for target in &targets {
            if let Some(session) = sessions.remove(target) {
                let mut session = session.lock().unwrap();
                let session_id = session.capture.lock().unwrap().session_id.clone();
                session.close();
                notify(SerialDisconnectPayload { session_id: Some(session_id), port: target.clone(), reason: reason.into() });
            }
        }
        let mut active = self.last_active_port.lock().unwrap();
        if port_name.is_none() || active.as_ref().map_or(false, |name| targets.contains(name)) {
            *active = sessions.keys().next().cloned();
        }
        let mut source = self.waveform_source.lock().unwrap();
        if port_name.is_none() || source.as_ref().map_or(false, |name| targets.contains(name)) {
            *source = sessions.keys().next().cloned();
        }
        Ok(())
    }

    fn resolve_session(&self, port_name: Option<&str>) -> Result<Arc<Mutex<PortSession>>, String> {
        let sessions = self.sessions.lock().unwrap();
        if let Some(target) = port_name {
            sessions
                .get(target)
                .cloned()
                .ok_or_else(|| format!("端口 '{}' 未打开", target))
        } else {
            let last_active = self.last_active_port.lock().unwrap();
            if let Some(active) = last_active.as_deref() {
                sessions
                    .get(active)
                    .cloned()
                    .ok_or_else(|| "当前活跃端口已关闭".to_string())
            } else if let Some((_, first)) = sessions.iter().next() {
                Ok(Arc::clone(first))
            } else {
                Err("未打开任何串口设备".to_string())
            }
        }
    }

    pub fn write_data(&self, data: &[u8], port_name: Option<&str>) -> Result<usize, String> {
        self.write_guarded(data, port_name, None)
    }
    pub fn write_guarded(&self, data: &[u8], port_name: Option<&str>, session_id: Option<&str>) -> Result<usize, String> {
        self.write_core(data,port_name,session_id,false)
    }
    fn write_core(&self, data: &[u8], port_name: Option<&str>, session_id: Option<&str>, in_transaction:bool) -> Result<usize, String> {
        let session_arc = self.resolve_session(port_name)?;
        let transaction=session_arc.lock().unwrap().transaction.clone();
        let _permit=if in_transaction{None}else{Some(transaction.try_lock().map_err(|_|"Port is owned by a command transaction")?)};
        let mut session = session_arc.lock().unwrap();
        if let Some(expected) = session_id {
            if session.capture.lock().unwrap().session_id != expected { return Err("Session changed; stale send rejected".into()); }
        }
        if !session.is_running.load(Ordering::SeqCst) { return Err("Session disconnected".into()); }
        if let Some(native)=&session.native{return native.write(data);}

        if let Some(ref mut port) = session.port {
            port.write_all(data)
                .map_err(|e| format!("Write failed: {}", e))?;
            port.flush().map_err(|e| format!("Flush failed: {}", e))?;
            session.capture.lock().unwrap().append("TX", data, None);
            return Ok(data.len());
        }

        if let Some(ref mut stream) = session.rtt_stream {
            stream
                .write_all(data)
                .map_err(|e| format!("RTT Write failed: {}", e))?;
            stream.flush().map_err(|e| format!("RTT Flush failed: {}", e))?;
            session.capture.lock().unwrap().append("TX", data, None);
            return Ok(data.len());
        }

        Err("目标端口未处于连接状态".to_string())
    }

    // The caller owns the transaction permit. Never resolve a port name again
    // between reset stages: a close/reopen must not redirect a pulse.
    fn set_session_line(session: &Arc<Mutex<PortSession>>, dtr: bool, level: bool) -> Result<(), String> {
        let mut session = session.lock().unwrap();
        if !session.is_running.load(Ordering::SeqCst) { return Err("Session disconnected; pin state unknown".into()); }
        if let Some(native) = &session.native {
            if dtr { native.set_dtr(level)?; } else { native.set_rts(level)?; }
        } else if let Some(port) = session.port.as_mut() {
            let result = if dtr { port.write_data_terminal_ready(level) } else { port.write_request_to_send(level) };
            result.map_err(|e| format!("Set {} failed: {e}", if dtr { "DTR" } else { "RTS" }))?;
        } else {
            return Err("目标串口未打开".into());
        }
        if dtr { session.dtr_state.store(level, Ordering::SeqCst); }
        else { session.rts_state.store(level, Ordering::SeqCst); }
        Ok(())
    }

    fn set_line(&self, dtr: bool, level: bool, port_name: Option<&str>) -> Result<(), String> {
        let session = self.resolve_session(port_name)?;
        let transaction = session.lock().unwrap().transaction.clone();
        let _permit = transaction.try_lock().map_err(|_| "Port is owned by a command transaction or reset")?;
        Self::set_session_line(&session, dtr, level)
    }

    pub fn set_dtr(&self, level: bool, port_name: Option<&str>) -> Result<(), String> {
        self.set_line(true, level, port_name)
    }

    pub fn set_rts(&self, level: bool, port_name: Option<&str>) -> Result<(), String> {
        self.set_line(false, level, port_name)
    }

    pub fn execute_reset(&self, is_bootloader: bool, port_name: Option<&str>) -> Result<(), String> {
        self.execute_reset_with_wait(is_bootloader, port_name, std::thread::sleep)
    }

    fn execute_reset_with_wait(&self, is_bootloader: bool, port_name: Option<&str>, mut wait: impl FnMut(Duration)) -> Result<(), String> {
        let session = self.resolve_session(port_name)?;
        let transaction = session.lock().unwrap().transaction.clone();
        let _permit = transaction.try_lock().map_err(|_| "Port is owned by a command transaction or reset")?;
        {
            let state = session.lock().unwrap();
            if !state.is_running.load(Ordering::SeqCst) { return Err("串口未打开，无法执行硬件复位。".into()); }
            if !state.is_daplink { return Err("当前串口不支持已有 DAPLink RTS/DTR 复位适配；必须核对板级接线与极性。".into()); }
        }
        // Preserve the existing adapter's line polarity and timing, not a
        // claim that every DAPLink board is wired this way.
        let result = (|| {
            Self::set_session_line(&session, false, is_bootloader)?;
            wait(Duration::from_millis(if is_bootloader { 500 } else { 50 }));
            Self::set_session_line(&session, true, true)?;
            wait(Duration::from_millis(100));
            Self::set_session_line(&session, true, false)
        })();
        if let Err(error) = result {
            // Best-effort release only on the original session, never a new
            // connection with the same name. Preserve unknown cleanup outcomes.
            let dtr = Self::set_session_line(&session, true, false);
            let rts = Self::set_session_line(&session, false, false);
            return Err(format!("Reset failed: {error}; cleanup DTR={dtr:?}, RTS={rts:?}"));
        }
        Ok(())
    }

    pub fn get_status(&self, port_name: Option<&str>) -> (bool, Option<String>, bool, bool, bool) {
        if let Ok(session_arc) = self.resolve_session(port_name) {
            let session = session_arc.lock().unwrap();
            let name = session.port_name.clone();
            let is_open = session.is_running.load(Ordering::SeqCst);
            let dtr = session.dtr_state.load(Ordering::SeqCst);
            let rts = session.rts_state.load(Ordering::SeqCst);
            let is_dap = session.is_daplink;
            (is_open, Some(name), dtr, rts, is_dap)
        } else {
            (false, None, false, false, false)
        }
    }

    /// Pause the port session for firmware flashing, returning the original baud rate if it was active
    pub fn pause_for_flashing(&self, app: &AppHandle, port_name: &str) -> Option<u32> {
        let mut original_baud = None;
        {
            let mut sessions_guard = self.sessions.lock().unwrap();
            if let Some(session_arc) = sessions_guard.remove(port_name) {
                let mut session = session_arc.lock().unwrap();
                original_baud = Some(session.baud_rate);
                session.close();
            }
        }
        if let Some(baud) = original_baud {
            let _ = app.emit("serial-flash-active", SerialFlashEventPayload {
                port: port_name.to_string(),
                original_baud: Some(baud),
                message: format!("串口 {} 正在被固件烧录任务临时接管，终端数据监听已暂时挂起...", port_name),
            });
        }
        // Give Windows OS kernel sufficient time to release the COM file handle
        std::thread::sleep(Duration::from_millis(150));
        original_baud
    }

    /// Resume the port session after firmware flashing finishes
    pub fn resume_after_flashing(&self, app: &AppHandle, port_name: &str, baud_rate: u32) -> Result<(), String> {
        // Sleep briefly to ensure flashing handle is completely closed
        std::thread::sleep(Duration::from_millis(150));
        Self::finish_restore(self.open(app.clone(), port_name, baud_rate), || {
            let _ = app.emit("serial-flash-done", SerialFlashEventPayload {
                port: port_name.to_string(),
                original_baud: Some(baud_rate),
                message: format!("固件烧录任务已结束，串口 {} 控制权已归还给终端（恢复波特率: {}）", port_name, baud_rate),
            });
        })
    }

    fn finish_restore(result: Result<(), String>, notify_restored: impl FnOnce()) -> Result<(), String> {
        result.map_err(|error| format!("串口恢复失败，控制权未归还终端: {error}"))?;
        notify_restored();
        Ok(())
    }
}
