pub mod commands;
pub mod daemon;
pub mod hardware;
pub mod platform;
pub mod system_metrics;

use commands::AppState;
use daemon::process_manager::DaemonManager;
use hardware::serial_manager::SerialManager;
use std::sync::Arc;
use tauri::Manager;

fn log_debug(msg: &str) {
    use std::io::Write;
    let pid = std::process::id();
    if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open("app_debug.log") {
        let _ = writeln!(file, "[PID {}] {}", pid, msg);
    }
    println!("[PID {}] {}", pid, msg);
}

pub fn configure_webview_environment() {
    // Keep WebView2 default flags to ensure stable initialization across all Windows & Edge versions
}

#[cfg(debug_assertions)]
fn ensure_dev_server_running() {
    use std::net::TcpStream;
    use std::time::Duration;
    use std::process::Command;

    if let Ok(addr) = "127.0.0.1:5173".parse() {
        if TcpStream::connect_timeout(&addr, Duration::from_millis(200)).is_ok() {
            return;
        }

        println!("[DevServerCheck] Port 5173 is offline. Automatically spawning Vite dev server...");
        let mut cmd = Command::new("cmd");
        cmd.args(["/c", "pnpm", "run", "dev"]);
        #[cfg(target_os = "windows")]
        {
            use std::os::windows::process::CommandExt;
            cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
        }
        let _ = cmd.spawn();

        for _ in 0..60 {
            std::thread::sleep(Duration::from_millis(100));
            if TcpStream::connect_timeout(&addr, Duration::from_millis(100)).is_ok() {
                println!("[DevServerCheck] Vite dev server is now online!");
                break;
            }
        }
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    log_debug("[INIT] app_lib::run started");
    configure_webview_environment();

    #[cfg(debug_assertions)]
    ensure_dev_server_running();

    let serial = Arc::new(SerialManager::new());
    let daemon = Arc::new(DaemonManager::new());

    let serial_exit = Arc::clone(&serial);
    let daemon_exit = Arc::clone(&daemon);

    let app = match tauri::Builder::default()
        .on_window_event(|window, event| {
            log_debug(&format!("[WINDOW_EVENT] {}: {:?}", window.label(), event));
        })
        .on_page_load(|window, payload| {
            log_debug(&format!("[PAGE_LOAD] {}: url={}, event={:?}", window.label(), payload.url(), payload.event()));
        })
        .setup(|app| {
            log_debug("[SETUP] Tauri application setup hook triggered");
            for (label, window) in app.webview_windows() {
                log_debug(&format!("[SETUP] Found window: {}", label));
                log_debug(&format!("[SETUP] is_visible: {:?}", window.is_visible()));
                log_debug(&format!("[SETUP] show() result: {:?}", window.show()));
                log_debug(&format!("[SETUP] set_focus() result: {:?}", window.set_focus()));
                #[cfg(target_os = "windows")]
                {
                    log_debug(&format!("[SETUP] hwnd() result: {:?}", window.hwnd()));
                }
            }
            Ok(())
        })
        .manage(AppState {
            serial: Arc::clone(&serial),
            daemon: Arc::clone(&daemon),
        })
        .invoke_handler(tauri::generate_handler![
            commands::list_serial_ports,
            commands::open_serial_port,
            commands::close_serial_port,
            commands::send_serial_data,
            commands::set_dtr,
            commands::set_rts,
            commands::execute_reset_sequence,
            commands::get_serial_status,
            commands::pyocd_list_probes,
            commands::pyocd_read_registers,
            commands::pyocd_read_memory,
            commands::pyocd_write_memory,
            commands::pyocd_flash_firmware,
            commands::pyocd_reset_target,
            commands::pyocd_diagnose_hardfault,
            commands::call_mcp_tool,
            commands::get_system_metrics,
        ])
        .build(tauri::generate_context!()) {
            Ok(a) => {
                log_debug("[BUILD] Tauri build context created successfully");
                a
            },
            Err(e) => {
                let msg = format!("BUILD ERROR: {:?}", e);
                let _ = std::fs::write("crash.log", &msg);
                log_debug(&msg);
                return;
            }
        };

    log_debug("[RUN] Entering app.run loop");
    app.run(move |_app_handle, event| {
        match &event {
            tauri::RunEvent::Ready => {
                log_debug("[EVENT] RunEvent::Ready");
            }
            tauri::RunEvent::WindowEvent { label, event, .. } => {
                log_debug(&format!("[EVENT] WindowEvent {}: {:?}", label, event));
            }
            tauri::RunEvent::Exit => {
                log_debug("[EVENT] RunEvent::Exit");
                let _ = serial_exit.close();
                daemon_exit.stop();
            }
            tauri::RunEvent::ExitRequested { api: _, .. } => {
                log_debug("[EVENT] RunEvent::ExitRequested");
            }
            _ => {}
        }
    });
}
