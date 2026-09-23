//! Network Stream Manager: TCP Client, TCP Server, and UDP Socket Stream Support.
//! Bridges network streams directly into the unified hardware event pipeline (`serial-rx` & `waveform-points`).

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream, UdpSocket};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter};

use super::protocol_engine::ProtocolEngine;
use super::serial_manager::{SerialRxPayload, WaveformPointsPayload};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum NetworkMode {
    TcpClient,
    TcpServer,
    UdpSocket,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NetworkStreamInfo {
    pub name: String,
    pub mode: NetworkMode,
    pub host: String,
    pub port: u16,
    pub is_connected: bool,
    pub remote_addr: Option<String>,
}

enum ConnectionBackend {
    Tcp(TcpStream),
    Udp(UdpSocket, Option<std::net::SocketAddr>),
}

pub struct NetworkSession {
    pub name: String,
    pub mode: NetworkMode,
    pub host: String,
    pub port: u16,
    backend: Arc<Mutex<Option<ConnectionBackend>>>,
    pub is_running: Arc<AtomicBool>,
}

pub struct NetworkManager {
    sessions: Arc<Mutex<HashMap<String, Arc<NetworkSession>>>>,
    protocol_engine: Arc<Mutex<Option<ProtocolEngine>>>,
    waveform_source: Arc<Mutex<Option<String>>>,
}

impl NetworkManager {
    pub fn new(
        protocol_engine: Arc<Mutex<Option<ProtocolEngine>>>,
        waveform_source: Arc<Mutex<Option<String>>>,
    ) -> Self {
        Self {
            sessions: Arc::new(Mutex::new(HashMap::new())),
            protocol_engine,
            waveform_source,
        }
    }

    /// List active network sessions
    pub fn list_sessions(&self) -> Vec<NetworkStreamInfo> {
        let sessions = self.sessions.lock().unwrap();
        sessions
            .values()
            .map(|s| {
                let is_connected = s.is_running.load(Ordering::Relaxed) && s.backend.lock().unwrap().is_some();
                let remote_addr = if let Ok(guard) = s.backend.lock() {
                    match guard.as_ref() {
                        Some(ConnectionBackend::Tcp(stream)) => stream.peer_addr().ok().map(|a| a.to_string()),
                        Some(ConnectionBackend::Udp(_, addr)) => addr.map(|a| a.to_string()),
                        None => None,
                    }
                } else {
                    None
                };

                NetworkStreamInfo {
                    name: s.name.clone(),
                    mode: s.mode.clone(),
                    host: s.host.clone(),
                    port: s.port,
                    is_connected,
                    remote_addr,
                }
            })
            .collect()
    }

    /// Connect or listen to a network stream
    pub fn start_stream(
        &self,
        app: AppHandle,
        name: String,
        mode: NetworkMode,
        host: String,
        port: u16,
    ) -> Result<(), String> {
        self.stop_stream(&name);

        let is_running = Arc::new(AtomicBool::new(true));
        let backend = Arc::new(Mutex::new(None));

        let session = Arc::new(NetworkSession {
            name: name.clone(),
            mode: mode.clone(),
            host: host.clone(),
            port,
            backend: Arc::clone(&backend),
            is_running: Arc::clone(&is_running),
        });

        {
            let mut map = self.sessions.lock().unwrap();
            map.insert(name.clone(), Arc::clone(&session));
            // Auto bind to waveform source if not configured
            let mut wf_guard = self.waveform_source.lock().unwrap();
            if wf_guard.is_none() {
                *wf_guard = Some(name.clone());
            }
        }

        let stream_name = name.clone();
        let engine_clone = Arc::clone(&self.protocol_engine);
        let wf_source_clone = Arc::clone(&self.waveform_source);

        std::thread::spawn(move || {
            match mode {
                NetworkMode::TcpClient => {
                    let addr = format!("{}:{}", host, port);
                    println!("[NetworkManager] Connecting to TCP server {}...", addr);
                    match TcpStream::connect(&addr) {
                        Ok(stream) => {
                            let _ = stream.set_read_timeout(Some(Duration::from_millis(50)));
                            let _ = stream.set_nodelay(true);
                            if let Ok(reader_clone) = stream.try_clone() {
                                {
                                    let mut b_guard = backend.lock().unwrap();
                                    *b_guard = Some(ConnectionBackend::Tcp(stream));
                                }
                                Self::run_tcp_read_loop(
                                    app,
                                    reader_clone,
                                    stream_name,
                                    is_running,
                                    engine_clone,
                                    wf_source_clone,
                                );
                            }
                        }
                        Err(e) => {
                            eprintln!("[NetworkManager] Failed to connect to {}: {}", addr, e);
                            is_running.store(false, Ordering::SeqCst);
                        }
                    }
                }
                NetworkMode::TcpServer => {
                    let bind_addr = format!("{}:{}", host, port);
                    println!("[NetworkManager] Starting TCP Server on {}...", bind_addr);
                    match TcpListener::bind(&bind_addr) {
                        Ok(listener) => {
                            let _ = listener.set_nonblocking(true);
                            while is_running.load(Ordering::Relaxed) {
                                match listener.accept() {
                                    Ok((client_stream, peer)) => {
                                        println!("[NetworkManager] TCP Client connected: {}", peer);
                                        let _ = client_stream.set_read_timeout(Some(Duration::from_millis(50)));
                                        let _ = client_stream.set_nodelay(true);
                                        if let Ok(reader_clone) = client_stream.try_clone() {
                                            {
                                                let mut b_guard = backend.lock().unwrap();
                                                *b_guard = Some(ConnectionBackend::Tcp(client_stream));
                                            }
                                            Self::run_tcp_read_loop(
                                                app.clone(),
                                                reader_clone,
                                                stream_name.clone(),
                                                Arc::clone(&is_running),
                                                Arc::clone(&engine_clone),
                                                Arc::clone(&wf_source_clone),
                                            );
                                        }
                                        break;
                                    }
                                    Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                                        std::thread::sleep(Duration::from_millis(100));
                                    }
                                    Err(_) => {
                                        break;
                                    }
                                }
                            }
                        }
                        Err(e) => {
                            eprintln!("[NetworkManager] Failed to bind TCP server on {}: {}", bind_addr, e);
                            is_running.store(false, Ordering::SeqCst);
                        }
                    }
                }
                NetworkMode::UdpSocket => {
                    let bind_addr = format!("{}:{}", host, port);
                    println!("[NetworkManager] Binding UDP Socket on {}...", bind_addr);
                    match UdpSocket::bind(&bind_addr) {
                        Ok(socket) => {
                            let _ = socket.set_read_timeout(Some(Duration::from_millis(50)));
                            let socket_clone = socket.try_clone().unwrap_or_else(|_| socket.try_clone().unwrap());
                            {
                                let mut b_guard = backend.lock().unwrap();
                                *b_guard = Some(ConnectionBackend::Udp(socket, None));
                            }
                            Self::run_udp_read_loop(
                                app,
                                socket_clone,
                                stream_name,
                                is_running,
                                engine_clone,
                                wf_source_clone,
                            );
                        }
                        Err(e) => {
                            eprintln!("[NetworkManager] Failed to bind UDP on {}: {}", bind_addr, e);
                            is_running.store(false, Ordering::SeqCst);
                        }
                    }
                }
            }
        });

        Ok(())
    }

    /// Read loop for TCP connection
    fn run_tcp_read_loop(
        app: AppHandle,
        mut stream: TcpStream,
        stream_name: String,
        is_running: Arc<AtomicBool>,
        engine_arc: Arc<Mutex<Option<ProtocolEngine>>>,
        waveform_source_arc: Arc<Mutex<Option<String>>>,
    ) {
        let mut read_buf = [0u8; 4096];
        let mut batch_buffer: Vec<u8> = Vec::with_capacity(4096);
        let mut last_flush = Instant::now();

        while is_running.load(Ordering::Relaxed) {
            match stream.read(&mut read_buf) {
                Ok(n) if n > 0 => {
                    let incoming = &read_buf[..n];

                    // Check if current network stream is selected as waveform data source
                    let is_active_wf_source = {
                        let wf_guard = waveform_source_arc.lock().unwrap();
                        wf_guard.as_ref().map(|s| s == &stream_name).unwrap_or(true)
                    };

                    if is_active_wf_source {
                        let mut parsed_points = Vec::new();
                        {
                            if let Ok(mut engine_opt) = engine_arc.lock() {
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
                                port: stream_name.clone(),
                                points: parsed_points,
                                timestamp_ms: now_ms,
                            };
                            let _ = app.emit("waveform-points", points_payload);
                        }
                    }

                    batch_buffer.extend_from_slice(incoming);
                }
                Ok(_) => {
                    // Connection closed by remote peer
                    println!("[NetworkManager] Remote closed stream {}", stream_name);
                    break;
                }
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
                    port: stream_name.clone(),
                    data: std::mem::take(&mut batch_buffer),
                    timestamp_ms: now_ms,
                };

                let _ = app.emit("serial-rx", payload);
                last_flush = Instant::now();
            }

            std::thread::sleep(Duration::from_millis(2));
        }

        is_running.store(false, Ordering::SeqCst);
    }

    /// Read loop for UDP socket
    fn run_udp_read_loop(
        app: AppHandle,
        socket: UdpSocket,
        stream_name: String,
        is_running: Arc<AtomicBool>,
        engine_arc: Arc<Mutex<Option<ProtocolEngine>>>,
        waveform_source_arc: Arc<Mutex<Option<String>>>,
    ) {
        let mut read_buf = [0u8; 4096];
        let mut batch_buffer: Vec<u8> = Vec::with_capacity(4096);
        let mut last_flush = Instant::now();

        while is_running.load(Ordering::Relaxed) {
            match socket.recv_from(&mut read_buf) {
                Ok((n, _src)) if n > 0 => {
                    let incoming = &read_buf[..n];

                    let is_active_wf_source = {
                        let wf_guard = waveform_source_arc.lock().unwrap();
                        wf_guard.as_ref().map(|s| s == &stream_name).unwrap_or(true)
                    };

                    if is_active_wf_source {
                        let mut parsed_points = Vec::new();
                        {
                            if let Ok(mut engine_opt) = engine_arc.lock() {
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
                                port: stream_name.clone(),
                                points: parsed_points,
                                timestamp_ms: now_ms,
                            };
                            let _ = app.emit("waveform-points", points_payload);
                        }
                    }

                    batch_buffer.extend_from_slice(incoming);
                }
                Ok(_) => {}
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
                    port: stream_name.clone(),
                    data: std::mem::take(&mut batch_buffer),
                    timestamp_ms: now_ms,
                };

                let _ = app.emit("serial-rx", payload);
                last_flush = Instant::now();
            }

            std::thread::sleep(Duration::from_millis(2));
        }

        is_running.store(false, Ordering::SeqCst);
    }

    /// Write data to an active network stream
    pub fn write_data(&self, name: &str, data: &[u8]) -> Result<usize, String> {
        let sessions = self.sessions.lock().unwrap();
        let session = sessions.get(name).ok_or_else(|| format!("网络数据流 {} 未找到", name))?;

        let mut b_guard = session.backend.lock().unwrap();
        match b_guard.as_mut() {
            Some(ConnectionBackend::Tcp(stream)) => {
                stream.write_all(data).map_err(|e| format!("TCP Write failed: {}", e))?;
                stream.flush().map_err(|e| format!("TCP Flush failed: {}", e))?;
                Ok(data.len())
            }
            Some(ConnectionBackend::Udp(socket, remote_opt)) => {
                if let Some(target) = remote_opt {
                    socket.send_to(data, *target).map_err(|e| format!("UDP Send failed: {}", e))
                } else {
                    Err("UDP 未配置目标发送地址".to_string())
                }
            }
            None => Err(format!("网络连接 {} 未建立", name)),
        }
    }

    /// Stop and close a network stream
    pub fn stop_stream(&self, name: &str) {
        let mut sessions = self.sessions.lock().unwrap();
        if let Some(s) = sessions.remove(name) {
            s.is_running.store(false, Ordering::SeqCst);
            let mut b_guard = s.backend.lock().unwrap();
            *b_guard = None;
        }
    }
}
