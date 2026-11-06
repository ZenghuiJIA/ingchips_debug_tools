//! Device owner shared by desktop adapters and native HIL. No Tauri dependency.
use crate::stream::Journal;
use hil_debug_core::capture::Capture;
use std::io::{Read, Write};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::time::{Duration, Instant};
pub type Observer = Arc<dyn Fn(&[u8], f64) + Send + Sync>;
pub struct SerialSession {
    pub port_name: String,
    pub baudrate: u32,
    pub capture: Arc<Mutex<Capture>>,
    pub journal: Arc<Mutex<Journal>>,
    pub running: Arc<AtomicBool>,
    writer: Mutex<Box<dyn serialport::SerialPort>>,
    reader: Mutex<Option<std::thread::JoinHandle<()>>>,
    started: Instant,
}
impl SerialSession {
    pub fn open(port: &str, baud: u32, observer: Option<Observer>) -> Result<Arc<Self>, String> {
        Self::open_options(port, baud, observer, &serde_json::json!({}))
    }
    pub fn open_options(
        port: &str,
        baud: u32,
        observer: Option<Observer>,
        options: &serde_json::Value,
    ) -> Result<Arc<Self>, String> {
        if port.is_empty() || baud < 300 || baud > 4_000_000 {
            return Err("Invalid serial configuration".into());
        }
        let bits = match options["data_bits"].as_u64().unwrap_or(8) {
            5 => serialport::DataBits::Five,
            6 => serialport::DataBits::Six,
            7 => serialport::DataBits::Seven,
            8 => serialport::DataBits::Eight,
            _ => return Err("data_bits must be 5..8".into()),
        };
        let parity = match options["parity"]
            .as_str()
            .unwrap_or("N")
            .to_uppercase()
            .as_str()
        {
            "N" => serialport::Parity::None,
            "E" => serialport::Parity::Even,
            "O" => serialport::Parity::Odd,
            _ => return Err("Native serial parity supports N/E/O; mark/space unsupported".into()),
        };
        let stop = match options["stop_bits"].as_f64().unwrap_or(1.) {
            1. => serialport::StopBits::One,
            2. => serialport::StopBits::Two,
            _ => return Err("Native serial stop_bits supports 1/2".into()),
        };
        let mut writer = serialport::new(port, baud)
            .data_bits(bits)
            .parity(parity)
            .stop_bits(stop)
            .timeout(Duration::from_millis(20))
            .open()
            .map_err(|e| e.to_string())?;
        writer
            .write_data_terminal_ready(options["initial_dtr"].as_bool().unwrap_or(false))
            .map_err(|e| e.to_string())?;
        writer
            .write_request_to_send(options["initial_rts"].as_bool().unwrap_or(false))
            .map_err(|e| e.to_string())?;
        let mut reader = writer.try_clone().map_err(|e| e.to_string())?;
        let capture = Arc::new(Mutex::new(Capture::new(port)));
        let journal = Arc::new(Mutex::new(Journal::default()));
        let running = Arc::new(AtomicBool::new(true));
        let started = Instant::now();
        let session = Arc::new(Self {
            port_name: port.into(),
            baudrate: baud,
            capture: capture.clone(),
            journal: journal.clone(),
            running: running.clone(),
            writer: Mutex::new(writer),
            reader: Mutex::new(None),
            started,
        });
        let handle = std::thread::spawn(move || {
            let mut buffer = [0; 4096];
            while running.load(Ordering::SeqCst) {
                match reader.read(&mut buffer) {
                    Ok(0) => {}
                    Ok(n) => {
                        let stamp = started.elapsed().as_secs_f64() * 1000.;
                        capture.lock().unwrap().append("RX", &buffer[..n], None);
                        journal.lock().unwrap().append(&buffer[..n], stamp);
                        if let Some(callback) = &observer {
                            callback(&buffer[..n], stamp);
                        }
                    }
                    Err(e) if e.kind() == std::io::ErrorKind::TimedOut => {}
                    Err(e) => {
                        journal.lock().unwrap().error = Some(e.to_string());
                        break;
                    }
                }
            }
            running.store(false, Ordering::SeqCst);
            capture
                .lock()
                .unwrap()
                .append("INFO", &[], Some("Connection closed".into()));
            let _ = capture.lock().unwrap().stop();
        });
        *session.reader.lock().unwrap() = Some(handle);
        Ok(session)
    }
    pub fn elapsed_ms(&self) -> f64 {
        self.started.elapsed().as_secs_f64() * 1000.
    }
    pub fn write(&self, data: &[u8]) -> Result<usize, String> {
        if !self.running.load(Ordering::SeqCst) {
            return Err("Serial disconnected".into());
        }
        let mut port = self.writer.lock().unwrap();
        let result = port.write_all(data).and_then(|_| port.flush());
        match result {
            Ok(()) => {
                self.capture.lock().unwrap().append("TX", data, None);
                Ok(data.len())
            }
            Err(e) => {
                self.capture.lock().unwrap().append(
                    "ERROR",
                    data,
                    Some(format!("TX outcome unknown: {e}")),
                );
                Err(e.to_string())
            }
        }
    }
    pub fn set_dtr(&self, level: bool) -> Result<(), String> {
        self.writer
            .lock()
            .unwrap()
            .write_data_terminal_ready(level)
            .map_err(|e| e.to_string())
    }
    pub fn set_rts(&self, level: bool) -> Result<(), String> {
        self.writer
            .lock()
            .unwrap()
            .write_request_to_send(level)
            .map_err(|e| e.to_string())
    }
    pub fn close(&self) -> Result<(), String> {
        self.running.store(false, Ordering::SeqCst);
        if let Some(reader) = self.reader.lock().unwrap().take() {
            reader.join().map_err(|_| "Serial reader panicked")?;
        }
        Ok(())
    }
}
impl Drop for SerialSession {
    fn drop(&mut self) {
        let _ = self.close();
    }
}
impl crate::reset::ResetLines for SerialSession {
    fn dtr(&self, level: bool) -> Result<(), String> {
        self.set_dtr(level)
    }
    fn rts(&self, level: bool) -> Result<(), String> {
        self.set_rts(level)
    }
}
