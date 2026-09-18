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
    if port_name.starts_with("RTT") {
        state.daemon.ensure_started(&app)?;
        let probe_type = if port_name.contains("J-Link") {
            "jlink"
        } else {
            "daplink"
        };
        let rtt_res = state.daemon.call_rpc(
            "start_rtt",
            json!({
                "probe_type": probe_type,
            }),
        )?;
        let tcp_port = rtt_res
            .get("tcp_port")
            .and_then(|p| p.as_u64())
            .ok_or_else(|| "Failed to get RTT TCP bridge port".to_string())? as u16;

        state.serial.open_rtt(app, &port_name, tcp_port)
    } else {
        state.serial.open(app, &port_name, baud_rate)
    }
}

#[tauri::command]
pub fn close_serial_port(state: State<'_, AppState>) -> Result<(), String> {
    let _ = state.daemon.call_rpc("stop_rtt", json!({}));
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
pub fn pyocd_write_memory_byte(
    app: AppHandle,
    state: State<'_, AppState>,
    address: String,
    value: u8,
    probe_id: Option<String>,
    target_override: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "write_memory_byte",
        json!({
            "address": address,
            "value": value,
            "probe_id": probe_id,
            "target_override": target_override
        }),
    )
}

#[tauri::command]
pub fn pyocd_dump_memory_to_file(
    app: AppHandle,
    state: State<'_, AppState>,
    address: String,
    count: u32,
    file_path: String,
    probe_id: Option<String>,
    target_override: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "dump_memory_to_file",
        json!({
            "address": address,
            "count": count,
            "file_path": file_path,
            "probe_id": probe_id,
            "target_override": target_override
        }),
    )
}

#[tauri::command]
pub fn pyocd_load_file_to_memory(
    app: AppHandle,
    state: State<'_, AppState>,
    address: String,
    file_path: String,
    probe_id: Option<String>,
    target_override: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "load_file_to_memory",
        json!({
            "address": address,
            "file_path": file_path,
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

#[tauri::command]
pub fn jscope_parse_axf(
    app: AppHandle,
    state: State<'_, AppState>,
    file_path: String,
    filter_keyword: Option<String>,
    max_results: Option<u32>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "parse_axf_symbols",
        json!({
            "file_path": file_path,
            "filter_keyword": filter_keyword,
            "max_results": max_results.unwrap_or(200),
        }),
    )
}

#[tauri::command]
pub fn jscope_start_sampling(
    app: AppHandle,
    state: State<'_, AppState>,
    variables: Value,
    interval_ms: u32,
    probe_id: Option<String>,
    target_override: Option<String>,
    probe_type: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    let res = state.daemon.call_rpc(
        "start_jscope_sampling",
        json!({
            "variables": variables,
            "interval_ms": interval_ms,
            "probe_id": probe_id,
            "target_override": target_override,
            "probe_type": probe_type,
        }),
    )?;

    let tcp_port = res
        .get("tcp_port")
        .and_then(|p| p.as_u64())
        .ok_or_else(|| "Failed to get JScope TCP port".to_string())? as u16;

    // Open RTT / JScope stream through serial manager so frontend receives serial-rx
    state
        .serial
        .open_rtt(app, "JScope 变量采样", tcp_port)?;

    Ok(res)
}

#[tauri::command]
pub fn jscope_stop_sampling(state: State<'_, AppState>) -> Result<Value, String> {
    let _ = state.serial.close();
    state.daemon.call_rpc("stop_jscope_sampling", json!({}))
}
