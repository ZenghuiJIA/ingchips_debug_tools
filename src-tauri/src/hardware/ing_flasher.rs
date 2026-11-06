pub use hil_runtime::ing::*;
use std::sync::Arc;
use tauri::{AppHandle, Emitter};
use super::serial_manager::SerialManager;

pub fn run_flash_task(
    app: AppHandle,
    req: IngFlashRequest,
    serial_mgr: Arc<SerialManager>,
    previous_baud: Option<u32>,
) -> Result<(), String> {
    let port_name = req.port_name.clone();

    let emit_progress = |stage: &str, file: &str, curr: usize, total: usize, pct: f32, speed: f32, msg: &str| {
        let _ = app.emit("ing-flash-progress", IngFlashProgress {
            job_id: req.job_id.clone(),
            port_name: port_name.clone(),
            stage: stage.to_string(),
            file_name: file.to_string(),
            current_bytes: curr,
            total_bytes: total,
            percentage: pct,
            speed_kbps: speed,
            message: msg.to_string(),
        });
    };

    // Run inner flash routine
    let res = run_flash_core(&req, &emit_progress);
    if let Err(ref err_msg) = res {
        emit_progress("error", "", 0, 0, 0.0, 0.0, &err_msg);
    }

    *FLASH_PORT.lock().unwrap() = None;
    // Always restore the port if it was previously active in the serial terminal
    if let Some(baud) = previous_baud {
        emit_progress("restore", "", 0, 0, 0.0, 0.0, &format!("烧录已完成，正在恢复终端串口监听 (波特率: {})...", baud));
        if let Err(e) = serial_mgr.resume_after_flashing(&app, &port_name, baud) {
            eprintln!("Failed to restore serial port {} after flashing: {}", port_name, e);
        }
    }
    res
}
