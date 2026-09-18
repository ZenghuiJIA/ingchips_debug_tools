use crate::daemon::process_manager::DaemonManager;
use crate::hardware::serial_manager::{PortInfo, SerialManager};
use crate::system_metrics::{collect_metrics, SystemMetrics};
use serde_json::{json, Value};
use std::sync::Arc;
use tauri::{AppHandle, State};

pub struct AppState {
    pub serial: Arc<SerialManager>,
    pub daemon: Arc<DaemonManager>,
}

#[tauri::command]
pub fn list_serial_ports() -> Vec<PortInfo> {
    SerialManager::list_ports()
}

#[tauri::command]
pub fn open_serial_port(
    app: AppHandle,
    state: State<'_, AppState>,
    port_name: String,
    baud_rate: u32,
) -> Result<(), String> {
    state.serial.open(app, &port_name, baud_rate)
}

#[tauri::command]
pub fn close_serial_port(state: State<'_, AppState>) -> Result<(), String> {
    state.serial.close()
}

#[tauri::command]
pub fn send_serial_data(state: State<'_, AppState>, data: Vec<u8>) -> Result<usize, String> {
    state.serial.write_data(&data)
}

#[tauri::command]
pub fn set_dtr(state: State<'_, AppState>, level: bool) -> Result<(), String> {
    state.serial.set_dtr(level)
}

#[tauri::command]
pub fn set_rts(state: State<'_, AppState>, level: bool) -> Result<(), String> {
    state.serial.set_rts(level)
}

#[tauri::command]
pub async fn execute_reset_sequence(
    state: State<'_, AppState>,
    seq_type: String,
) -> Result<(), String> {
    let is_bootloader = seq_type == "bootloader_reset";
    state.serial.execute_reset(is_bootloader).await
}

#[tauri::command]
pub fn get_serial_status(state: State<'_, AppState>) -> (bool, Option<String>, bool, bool, bool) {
    state.serial.get_status()
}

#[tauri::command]
pub fn pyocd_list_probes(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc("list_probes", json!({}))
}

#[tauri::command]
pub fn pyocd_read_registers(
    app: AppHandle,
    state: State<'_, AppState>,
    probe_id: Option<String>,
    target_override: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "read_core_registers",
        json!({
            "probe_id": probe_id,
            "target_override": target_override
        }),
    )
}

#[tauri::command]
pub fn pyocd_read_memory(
    app: AppHandle,
    state: State<'_, AppState>,
    address: String,
    count: u32,
    probe_id: Option<String>,
    target_override: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "read_memory",
        json!({
            "address": address,
            "count": count,
            "probe_id": probe_id,
            "target_override": target_override
        }),
    )
}

#[tauri::command]
pub fn pyocd_write_memory(
    app: AppHandle,
    state: State<'_, AppState>,
    address: String,
    value: String,
    probe_id: Option<String>,
    target_override: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "write_memory",
        json!({
            "address": address,
            "value": value,
            "probe_id": probe_id,
            "target_override": target_override
        }),
    )
}

#[tauri::command]
pub fn pyocd_flash_firmware(
    app: AppHandle,
    state: State<'_, AppState>,
    file_path: String,
    target_override: Option<String>,
    probe_id: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "flash_firmware",
        json!({
            "file_path": file_path,
            "target_override": target_override,
            "probe_id": probe_id
        }),
    )
}

#[tauri::command]
pub fn pyocd_reset_target(
    app: AppHandle,
    state: State<'_, AppState>,
    halt: bool,
    probe_id: Option<String>,
    target_override: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "reset_target",
        json!({
            "halt": halt,
            "probe_id": probe_id,
            "target_override": target_override
        }),
    )
}

#[tauri::command]
pub fn pyocd_diagnose_hardfault(
    app: AppHandle,
    state: State<'_, AppState>,
    probe_id: Option<String>,
    target_override: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "diagnose_hardfault",
        json!({
            "probe_id": probe_id,
            "target_override": target_override
        }),
    )
}

#[tauri::command]
pub fn call_mcp_tool(
    app: AppHandle,
    state: State<'_, AppState>,
    tool_name: String,
    arguments: Value,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_mcp_tool(&tool_name, arguments)
}

#[tauri::command]
pub fn get_system_metrics(state: State<'_, AppState>) -> SystemMetrics {
    let daemon_pid = *state.daemon.child_pid.lock().unwrap();
    collect_metrics(daemon_pid)
}
