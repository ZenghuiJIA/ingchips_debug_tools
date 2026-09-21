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
    #[cfg(target_os = "windows")]
    {
        platform::windows::environment::log_to_file(msg);
    }
    println!("[PID {}] {}", std::process::id(), msg);
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
    #[cfg(target_os = "windows")]
    {
        if !platform::windows::environment::ensure_environment_ready() {
            // Missing runtime and user was prompted, exit cleanly without hanging
            return;
        }
    }

    log_debug("[INIT] app_lib::run started");

    #[cfg(debug_assertions)]
    ensure_dev_server_running();

    // 1. Asynchronously cleanup lingering background daemons so main UI thread is NEVER blocked
    std::thread::spawn(|| {
        daemon::process_manager::kill_all_daemons();
    });

    let serial = Arc::new(SerialManager::new());
    let daemon = Arc::new(DaemonManager::new());

    let serial_exit = Arc::clone(&serial);
    let daemon_exit = Arc::clone(&daemon);
    let serial_win = Arc::clone(&serial);
    let daemon_win = Arc::clone(&daemon);

    let app = match tauri::Builder::default()
        .on_window_event(move |_window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } | tauri::WindowEvent::Destroyed = event {
                log_debug("[WINDOW_EVENT] Window closing, cleaning up all background processes...");
                let _ = serial_win.close();
                daemon_win.stop();
            }
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
            commands::pyocd_write_memory_byte,
            commands::pyocd_dump_memory_to_file,
            commands::pyocd_load_file_to_memory,
            commands::pyocd_flash_firmware,
            commands::pyocd_reset_target,
            commands::pyocd_diagnose_hardfault,
            commands::call_mcp_tool,
            commands::get_system_metrics,
            commands::jscope_parse_axf,
            commands::jscope_start_sampling,
            commands::jscope_stop_sampling,
        ])
        .build(tauri::generate_context!()) {
            Ok(a) => {
                log_debug("[BUILD] Tauri build context created successfully");
                a
            },
            Err(e) => {
                let msg = format!("BUILD ERROR: {:?}", e);
                log_debug(&msg);

                #[cfg(target_os = "windows")]
                {
                    let log_dir = platform::windows::environment::get_app_log_dir();
                    let _ = std::fs::write(log_dir.join("crash.log"), &msg);
                    let title_w: Vec<u16> = "AI-HIL Debugger - 窗口初始化失败\0".encode_utf16().collect();
                    let err_display = format!(
                        "图形界面引擎初始化失败：\n\n{:?}\n\n常见原因：系统缺少 Edge WebView2 运行时或缓存权限受限。\n日志目录：{:?}",
                        e, log_dir
                    );
                    let msg_w: Vec<u16> = err_display.encode_utf16().chain(std::iter::once(0)).collect();
                    unsafe {
                        windows_sys::Win32::UI::WindowsAndMessaging::MessageBoxW(
                            0 as _,
                            msg_w.as_ptr(),
                            title_w.as_ptr(),
                            windows_sys::Win32::UI::WindowsAndMessaging::MB_ICONERROR | windows_sys::Win32::UI::WindowsAndMessaging::MB_OK,
                        );
                    }
                }
                return;
            }
        };

    log_debug("[RUN] Entering app.run loop");
    app.run(move |_app_handle, event| {
        match &event {
            tauri::RunEvent::Ready => {
                log_debug("[EVENT] RunEvent::Ready");
            }
            tauri::RunEvent::WindowEvent { event, .. } => {
                if let tauri::WindowEvent::CloseRequested { .. } | tauri::WindowEvent::Destroyed = event {
                    let _ = serial_exit.close();
                    daemon_exit.stop();
                }
            }
            tauri::RunEvent::Exit => {
                log_debug("[EVENT] RunEvent::Exit");
                let _ = serial_exit.close();
                daemon_exit.stop();
            }
            tauri::RunEvent::ExitRequested { .. } => {
                log_debug("[EVENT] RunEvent::ExitRequested");
                let _ = serial_exit.close();
                daemon_exit.stop();
            }
            _ => {}
        }
    });
}
