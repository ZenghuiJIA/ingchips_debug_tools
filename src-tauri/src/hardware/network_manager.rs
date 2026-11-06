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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn udp_reply_requires_peer_and_close_releases_session() {
        let manager = NetworkManager::new(Arc::new(Mutex::new(None)), Arc::new(Mutex::new(None)));
        let peer = UdpSocket::bind("127.0.0.1:0").unwrap();
        peer.set_read_timeout(Some(Duration::from_secs(1))).unwrap();
        let socket = UdpSocket::bind("127.0.0.1:0").unwrap();
        let name = "UDP:127.0.0.1:0";
        let backend = Arc::new(Mutex::new(Some(ConnectionBackend::Udp(socket, None))));
        let running = Arc::new(AtomicBool::new(true));
        manager.sessions.lock().unwrap().insert(name.into(), Arc::new(NetworkSession {
            name: name.into(), mode: NetworkMode::UdpSocket, host: "127.0.0.1".into(), port: 0,
            backend: Arc::clone(&backend), is_running: Arc::clone(&running),
        }));
        assert!(manager.write_data(name, b"reply").is_err());
        if let Some(ConnectionBackend::Udp(_, remote)) = backend.lock().unwrap().as_mut() {
            *remote = Some(peer.local_addr().unwrap());
        }
        assert_eq!(manager.write_data(name, b"reply").unwrap(), 5);
        let mut bytes = [0; 16];
        let (count, _) = peer.recv_from(&mut bytes).unwrap();
        assert_eq!(&bytes[..count], b"reply");
        manager.stop_stream(name);
        assert!(!running.load(Ordering::SeqCst));
        assert!(manager.list_sessions().is_empty());
        assert!(manager.write_data(name, b"reply").is_err());
    }
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
    lifecycle: Mutex<()>,
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
            lifecycle: Mutex::new(()),
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
        &self, app: AppHandle, name: String, mode: NetworkMode, host: String, port: u16,
    ) -> Result<(), String> {
        let _lifecycle = self.lifecycle.lock().unwrap();
        use std::net::ToSocketAddrs;
        if self.sessions.lock().unwrap().contains_key(&name) {
            return Err("网络会话已存在，请先关闭".into());
        }
        let addr = format!("{}:{}", host, port);
        // Establish/bind first. A successful invoke never hides a connection failure.
        let mut listener = None;
        let initial = match mode {
            NetworkMode::TcpClient => {
                let peer = addr.to_socket_addrs().map_err(|e| e.to_string())?.next().ok_or("无效网络地址")?;
                let stream = TcpStream::connect_timeout(&peer, Duration::from_secs(3)).map_err(|e| e.to_string())?;
                stream.set_read_timeout(Some(Duration::from_millis(50))).map_err(|e| e.to_string())?;
                stream.set_write_timeout(Some(Duration::from_secs(3))).map_err(|e| e.to_string())?;
                Some(ConnectionBackend::Tcp(stream))
            }
            NetworkMode::TcpServer => {
                let tcp = TcpListener::bind(&addr).map_err(|e| e.to_string())?;
                tcp.set_nonblocking(true).map_err(|e| e.to_string())?;
                listener = Some(tcp);
                None
            }
            NetworkMode::UdpSocket => {
                let socket = UdpSocket::bind(&addr).map_err(|e| e.to_string())?;
                socket.set_read_timeout(Some(Duration::from_millis(50))).map_err(|e| e.to_string())?;
                socket.set_write_timeout(Some(Duration::from_secs(3))).map_err(|e| e.to_string())?;
                Some(ConnectionBackend::Udp(socket, None))
            }
        };
        let is_running = Arc::new(AtomicBool::new(true));
        let backend = Arc::new(Mutex::new(initial));
        let session = Arc::new(NetworkSession {
            name: name.clone(), mode: mode.clone(), host, port,
            backend: Arc::clone(&backend), is_running: Arc::clone(&is_running),
        });
        self.sessions.lock().unwrap().insert(name.clone(), session);
        {
            let mut source = self.waveform_source.lock().unwrap();
            if source.is_none() { *source = Some(name.clone()); }
        }
        let engine = Arc::clone(&self.protocol_engine);
        let source = Arc::clone(&self.waveform_source);
        let sessions = Arc::clone(&self.sessions);
        std::thread::spawn(move || {
            let result: Result<(), String> = (|| {
                if let Some(listener) = listener {
                    while is_running.load(Ordering::SeqCst) {
                        match listener.accept() {
                            Ok((stream, _)) => {
                                stream.set_read_timeout(Some(Duration::from_millis(50))).map_err(|e| e.to_string())?;
                                stream.set_write_timeout(Some(Duration::from_secs(3))).map_err(|e| e.to_string())?;
                                let reader = stream.try_clone().map_err(|e| e.to_string())?;
                                *backend.lock().unwrap() = Some(ConnectionBackend::Tcp(stream));
                                let _ = app.emit("network-state", &name);
                                Self::run_tcp_read_loop(app.clone(), reader, name.clone(), Arc::clone(&is_running), Arc::clone(&engine), Arc::clone(&source), true);
                                *backend.lock().unwrap() = None;
                                let _ = app.emit("network-state", &name);
                            }
                            Err(e) if e.kind() == std::io::ErrorKind::WouldBlock => std::thread::sleep(Duration::from_millis(50)),
                            Err(e) => return Err(e.to_string()),
                        }
                    }
                } else {
                    let cloned = {
                        let guard = backend.lock().unwrap();
                        match guard.as_ref() {
                            Some(ConnectionBackend::Tcp(stream)) => Some((Some(stream.try_clone().map_err(|e| e.to_string())?), None)),
                            Some(ConnectionBackend::Udp(socket, _)) => Some((None, Some(socket.try_clone().map_err(|e| e.to_string())?))),
                            None => None,
                        }
                    };
                    if let Some((tcp, udp)) = cloned {
                        if let Some(stream) = tcp {
                            Self::run_tcp_read_loop(app.clone(), stream, name.clone(), Arc::clone(&is_running), engine, source, false);
                        } else if let Some(socket) = udp {
                            Self::run_udp_read_loop(app.clone(), socket, name.clone(), Arc::clone(&is_running), engine, source, Arc::clone(&backend));
                        }
                    }
                }
                Ok(())
            })();
            is_running.store(false, Ordering::SeqCst);
            *backend.lock().unwrap() = None;
            // An old worker must not remove a replacement session with the same name.
            let mut map = sessions.lock().unwrap();
            if map.get(&name).map(|s| Arc::ptr_eq(&s.is_running, &is_running)).unwrap_or(false) {
                map.remove(&name);
            }
            drop(map);
            let _ = app.emit("serial-disconnected", super::serial_manager::SerialDisconnectPayload {
                port: name.clone(), reason: result.err().unwrap_or_else(|| "网络连接已关闭".into()),
            });
            let _ = app.emit("network-state", &name);
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
        keep_listening: bool,
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
                    session_id: None,
                    port: stream_name.clone(),
                    data: std::mem::take(&mut batch_buffer),
                    timestamp_ms: now_ms,
                };

                let _ = app.emit("serial-rx", payload);
                last_flush = Instant::now();
            }

            std::thread::sleep(Duration::from_millis(2));
        }

        if !batch_buffer.is_empty() {
            let _ = app.emit("serial-rx", SerialRxPayload {
                session_id: None,
                port: stream_name, data: batch_buffer,
                timestamp_ms: std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap_or_default().as_millis() as u64,
            });
        }
        if !keep_listening { is_running.store(false, Ordering::SeqCst); }
    }

    /// Read loop for UDP socket
    fn run_udp_read_loop(
        app: AppHandle,
        socket: UdpSocket,
        stream_name: String,
        is_running: Arc<AtomicBool>,
        engine_arc: Arc<Mutex<Option<ProtocolEngine>>>,
        waveform_source_arc: Arc<Mutex<Option<String>>>,
        backend: Arc<Mutex<Option<ConnectionBackend>>>,
    ) {
        let mut read_buf = [0u8; 4096];
        let mut batch_buffer: Vec<u8> = Vec::with_capacity(4096);
        let mut last_flush = Instant::now();

        while is_running.load(Ordering::Relaxed) {
            match socket.recv_from(&mut read_buf) {
                Ok((n, src)) if n > 0 => {
                    if let Some(ConnectionBackend::Udp(_, peer)) = backend.lock().unwrap().as_mut() { *peer = Some(src); }
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
                    session_id: None,
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
                    Err("UDP 尚未收到对端数据；请先让对端向本地监听地址发送一个数据报，再回复该对端".to_string())
                }
            }
            None => Err(format!("网络连接 {} 未建立", name)),
        }
    }

    /// Stop and close a network stream
    pub fn stop_stream(&self, name: &str) {
        let _lifecycle = self.lifecycle.lock().unwrap();
        let mut sessions = self.sessions.lock().unwrap();
        if let Some(s) = sessions.remove(name) {
            s.is_running.store(false, Ordering::SeqCst);
            let mut b_guard = s.backend.lock().unwrap();
            *b_guard = None;
        }
        let mut source = self.waveform_source.lock().unwrap();
        if source.as_deref() == Some(name) { *source = None; }
    }
}
