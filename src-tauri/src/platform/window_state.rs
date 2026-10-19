use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tauri::{PhysicalPosition, PhysicalSize, Position, Size, WebviewWindow};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WindowGeometryState {
    pub x: i32,
    pub y: i32,
    pub width: u32,
    pub height: u32,
    pub is_maximized: bool,
}

fn get_state_file_path() -> PathBuf {
    #[cfg(target_os = "windows")]
    {
        crate::platform::windows::environment::get_app_data_dir().join("window_state.json")
    }
    #[cfg(not(target_os = "windows"))]
    {
        std::env::temp_dir().join("AI-HIL-Debugger").join("window_state.json")
    }
}

pub fn load_window_state() -> Option<WindowGeometryState> {
    let path = get_state_file_path();
    if let Ok(data) = std::fs::read_to_string(&path) {
        if let Ok(state) = serde_json::from_str::<WindowGeometryState>(&data) {
            return Some(state);
        }
    }
    None
}

pub fn save_window_state(window: &WebviewWindow) {
    let is_maximized = window.is_maximized().unwrap_or(false);
    
    // If window is currently maximized, keep the last known unmaximized size/pos if possible,
    // or record is_maximized = true.
    let (x, y) = match window.outer_position() {
        Ok(pos) => (pos.x, pos.y),
        Err(_) => (100, 100),
    };

    let (width, height) = match window.outer_size() {
        Ok(sz) => (sz.width, sz.height),
        Err(_) => (1280, 840),
    };

    // Don't save invalid/collapsed sizes
    if width < 400 || height < 300 {
        return;
    }

    let state = WindowGeometryState {
        x,
        y,
        width,
        height,
        is_maximized,
    };

    let path = get_state_file_path();
    if let Some(parent) = path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    if let Ok(json_str) = serde_json::to_string_pretty(&state) {
        let _ = std::fs::write(&path, json_str);
    }
}

/// Restores window size, position, and checks whether the window rectangle falls
/// within any active display monitor. If not (e.g. secondary monitor disconnected),
/// safely center the window on the primary monitor.
pub fn restore_window_state(window: &WebviewWindow) {
    let state = match load_window_state() {
        Some(s) => s,
        None => return, // Keep defaults from tauri.conf.json
    };

    // 1. Retrieve all active monitors
    let monitors = window.available_monitors().unwrap_or_default();
    
    // Check if the saved position [x, y] or window center [x + width/2, y + height/2]
    // is visible on any monitor.
    let target_center_x = state.x + (state.width as i32 / 2);
    let target_center_y = state.y + (state.height as i32 / 2);

    let mut is_on_valid_monitor = false;

    for mon in &monitors {
        let mon_pos = mon.position();
        let mon_size = mon.size();
        let mon_left = mon_pos.x;
        let mon_right = mon_pos.x + mon_size.width as i32;
        let mon_top = mon_pos.y;
        let mon_bottom = mon_pos.y + mon_size.height as i32;

        // Give a 50px buffer so even partially displayed windows are recovered safely
        if target_center_x >= (mon_left - 50)
            && target_center_x <= (mon_right + 50)
            && target_center_y >= (mon_top - 50)
            && target_center_y <= (mon_bottom + 50)
        {
            is_on_valid_monitor = true;
            break;
        }
    }

    // Apply safe size (at least 900x600)
    let safe_width = state.width.max(1000);
    let safe_height = state.height.max(650);
    let _ = window.set_size(Size::Physical(PhysicalSize::new(safe_width, safe_height)));

    if is_on_valid_monitor && !monitors.is_empty() {
        // Valid coordinate on an existing monitor
        let _ = window.set_position(Position::Physical(PhysicalPosition::new(state.x, state.y)));
    } else {
        // Monitor was disconnected or coordinates are offscreen -> safely center on current/primary monitor
        let _ = window.center();
    }

    // Restore maximized state if it was maximized
    if state.is_maximized {
        let _ = window.maximize();
    }
}
