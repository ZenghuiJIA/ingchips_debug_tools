use crate::daemon::process_manager::DaemonManager;
use crate::hardware::network_manager::{NetworkManager, NetworkMode, NetworkStreamInfo};
use crate::hardware::serial_manager::{PortInfo, SerialManager};
use crate::system_metrics::{collect_metrics, SystemMetrics};
use serde_json::{json, Value};
use std::sync::Arc;
use tauri::{AppHandle, State};

pub struct AppState {
    pub serial: Arc<SerialManager>,
    pub network: Arc<NetworkManager>,
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
    ram_start: Option<u64>,
    ram_size: Option<u64>,
    block_address: Option<u64>,
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
                "ram_start": ram_start,
                "ram_size": ram_size,
                "block_address": block_address,
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
pub fn close_serial_port(
    state: State<'_, AppState>,
    port_name: Option<String>,
) -> Result<(), String> {
    if let Some(ref name) = port_name {
        if name.starts_with("TCP:") || name.starts_with("UDP:") {
            state.network.stop_stream(name);
            return Ok(());
        }
        if name.starts_with("RTT") {
            let _ = state.daemon.call_rpc("stop_rtt", json!({}));
        }
    } else {
        let _ = state.daemon.call_rpc("stop_rtt", json!({}));
    }
    state.serial.close(port_name.as_deref())
}

#[tauri::command]
pub fn send_serial_data(
    state: State<'_, AppState>,
    data: Vec<u8>,
    port_name: Option<String>,
) -> Result<usize, String> {
    if let Some(ref name) = port_name {
        if name.starts_with("TCP:") || name.starts_with("UDP:") {
            return state.network.write_data(name, &data);
        }
    }
    match state.serial.write_data(&data, port_name.as_deref()) {
        Ok(sz) => Ok(sz),
        Err(err) => {
            // Fallback: check if network manager has this stream
            if let Some(ref name) = port_name {
                if let Ok(sz) = state.network.write_data(name, &data) {
                    return Ok(sz);
                }
            }
            Err(err)
        }
    }
}

#[tauri::command]
pub fn set_dtr(
    state: State<'_, AppState>,
    level: bool,
    port_name: Option<String>,
) -> Result<(), String> {
    state.serial.set_dtr(level, port_name.as_deref())
}

#[tauri::command]
pub fn set_rts(
    state: State<'_, AppState>,
    level: bool,
    port_name: Option<String>,
) -> Result<(), String> {
    state.serial.set_rts(level, port_name.as_deref())
}

#[tauri::command]
pub async fn execute_reset_sequence(
    state: State<'_, AppState>,
    seq_type: String,
    port_name: Option<String>,
) -> Result<(), String> {
    let is_bootloader = seq_type == "bootloader_reset";
    state.serial.execute_reset(is_bootloader, port_name.as_deref()).await
}

#[tauri::command]
pub fn get_serial_status(
    state: State<'_, AppState>,
    port_name: Option<String>,
) -> (bool, Option<String>, bool, bool, bool) {
    state.serial.get_status(port_name.as_deref())
}

#[tauri::command]
pub fn list_active_serial_sessions(state: State<'_, AppState>) -> Vec<String> {
    let mut list = state.serial.list_active_sessions();
    let net_list = state.network.list_sessions();
    for n in net_list {
        if n.is_connected && !list.contains(&n.name) {
            list.push(n.name);
        }
    }
    list
}

#[tauri::command]
pub fn set_waveform_source(state: State<'_, AppState>, port_name: Option<String>) {
    state.serial.set_waveform_source(port_name);
}

#[tauri::command]
pub fn get_waveform_source(state: State<'_, AppState>) -> Option<String> {
    state.serial.get_waveform_source()
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
    pack_path: Option<String>,
    frequency: Option<u32>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "flash_firmware",
        json!({
            "file_path": file_path,
            "target_override": target_override,
            "probe_id": probe_id,
            "pack_path": pack_path,
            "frequency": frequency,
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
    axf_path: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "diagnose_hardfault",
        json!({
            "probe_id": probe_id,
            "target_override": target_override,
            "axf_path": axf_path
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
    interval_ms: Option<u32>,
    interval_us: Option<u32>,
    swd_frequency_hz: Option<u32>,
    probe_id: Option<String>,
    target_override: Option<String>,
    probe_type: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    let res = state.daemon.call_rpc(
        "start_jscope_sampling",
        json!({
            "variables": variables,
            "interval_ms": interval_ms.unwrap_or(20),
            "interval_us": interval_us,
            "swd_frequency_hz": swd_frequency_hz,
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
    let _ = state.serial.close(None);
    state.daemon.call_rpc("stop_jscope_sampling", json!({}))
}

#[tauri::command]
pub fn analyze_firmware_resources(
    app: AppHandle,
    state: State<'_, AppState>,
    file_path: String,
    chip_flash_size: Option<u64>,
    chip_ram_size: Option<u64>,
    max_symbols_per_module: Option<u32>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "analyze_firmware_resources",
        json!({
            "file_path": file_path,
            "chip_flash_size": chip_flash_size,
            "chip_ram_size": chip_ram_size,
            "max_symbols_per_module": max_symbols_per_module.unwrap_or(25),
        }),
    )
}

#[tauri::command]
pub async fn pick_firmware_file(title: Option<String>) -> Result<Option<String>, String> {
    let dialog_title = title.unwrap_or_else(|| "选择固件目标或 MAP 映射文件 (.map / .axf / .elf / .hex / .bin)".to_string());
    let file = rfd::AsyncFileDialog::new()
        .set_title(&dialog_title)
        .add_filter("固件与映射文件 (*.map, *.axf, *.elf, *.hex, *.bin)", &["map", "axf", "elf", "hex", "bin"])
        .add_filter("Linker MAP 映射文件 (*.map)", &["map"])
        .add_filter("ARM ELF / AXF 可执行文件 (*.axf, *.elf)", &["axf", "elf"])
        .add_filter("所有文件 (*.*)", &["*"])
        .pick_file()
        .await;

    Ok(file.map(|f| f.path().to_string_lossy().to_string()))
}

#[tauri::command]
pub async fn pick_pack_file(title: Option<String>) -> Result<Option<String>, String> {
    let dialog_title = title.unwrap_or_else(|| "选择 CMSIS-Pack 文件 (*.pack)".to_string());
    let file = rfd::AsyncFileDialog::new()
        .set_title(&dialog_title)
        .add_filter("CMSIS-Pack 芯片描述包 (*.pack)", &["pack"])
        .add_filter("所有文件 (*.*)", &["*"])
        .pick_file()
        .await;

    Ok(file.map(|f| f.path().to_string_lossy().to_string()))
}

#[tauri::command]
pub fn svd_import_pack(
    app: AppHandle,
    state: State<'_, AppState>,
    pack_path: String,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "svd_import_pack",
        json!({
            "pack_path": pack_path,
        }),
    )
}

#[tauri::command]
pub fn svd_get_devices(
    app: AppHandle,
    state: State<'_, AppState>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc("svd_get_devices", json!({}))
}

#[tauri::command]
pub fn svd_get_peripherals(
    app: AppHandle,
    state: State<'_, AppState>,
    device_name: String,
    custom_svd_path: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "svd_get_peripherals",
        json!({
            "device_name": device_name,
            "custom_svd_path": custom_svd_path,
        }),
    )
}

#[tauri::command]
pub fn svd_get_registers(
    app: AppHandle,
    state: State<'_, AppState>,
    device_name: String,
    peripheral_name: String,
    custom_svd_path: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "svd_get_registers",
        json!({
            "device_name": device_name,
            "peripheral_name": peripheral_name,
            "custom_svd_path": custom_svd_path,
        }),
    )
}

#[tauri::command]
pub fn svd_read_register(
    app: AppHandle,
    state: State<'_, AppState>,
    address: String,
    probe_id: Option<String>,
    target_override: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "svd_read_register",
        json!({
            "address": address,
            "probe_id": probe_id,
            "target_override": target_override,
        }),
    )
}

#[tauri::command]
pub fn svd_read_all_registers(
    app: AppHandle,
    state: State<'_, AppState>,
    addresses: Vec<String>,
    probe_id: Option<String>,
    target_override: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "svd_read_all_registers",
        json!({
            "addresses": addresses,
            "probe_id": probe_id,
            "target_override": target_override,
        }),
    )
}

#[tauri::command]
pub fn svd_write_register(
    app: AppHandle,
    state: State<'_, AppState>,
    address: String,
    value: u32,
    probe_id: Option<String>,
    target_override: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "svd_write_register",
        json!({
            "address": address,
            "value": value,
            "probe_id": probe_id,
            "target_override": target_override,
        }),
    )
}

#[tauri::command]
pub fn svd_write_field(
    app: AppHandle,
    state: State<'_, AppState>,
    address: String,
    bit_offset: u32,
    bit_width: u32,
    field_value: u32,
    probe_id: Option<String>,
    target_override: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "svd_write_field",
        json!({
            "address": address,
            "bit_offset": bit_offset,
            "bit_width": bit_width,
            "field_value": field_value,
            "probe_id": probe_id,
            "target_override": target_override,
        }),
    )
}

#[tauri::command]
pub fn set_waveform_protocol(
    state: State<'_, AppState>,
    config_json: String,
) -> Result<(), String> {
    state.serial.set_protocol_config(&config_json)
}

#[tauri::command]
pub fn clear_waveform_protocol(
    state: State<'_, AppState>,
) -> Result<(), String> {
    state.serial.clear_protocol();
    Ok(())
}

#[tauri::command]
pub fn compute_checksum(
    data: Vec<u8>,
    algo: String,
) -> Result<Vec<u8>, String> {
    Ok(crate::hardware::checksum::append_checksum_by_algo(&data, &algo))
}

#[tauri::command]
pub fn modbus_build_request(
    slave_id: u8,
    func_code: u8,
    start_addr: u16,
    count_or_val: u16,
    extra_values: Option<Vec<u16>>,
) -> Result<Vec<u8>, String> {
    Ok(crate::hardware::modbus::build_modbus_request(
        slave_id,
        func_code,
        start_addr,
        count_or_val,
        extra_values.as_deref(),
    ))
}

#[tauri::command]
pub fn modbus_parse_response(
    port: String,
    start_addr: u16,
    frame: Vec<u8>,
) -> Result<crate::hardware::modbus::ModbusResponsePayload, String> {
    crate::hardware::modbus::parse_modbus_response(&port, start_addr, &frame)
}

#[tauri::command]
pub fn dsp_measure_waveform(
    samples: Vec<f64>,
    sample_rate_hz: f64,
) -> Result<crate::hardware::dsp::WaveformMeasurements, String> {
    Ok(crate::hardware::dsp::measure_waveform(&samples, sample_rate_hz))
}

#[tauri::command]
pub fn dsp_compute_fft(
    samples: Vec<f64>,
    sample_rate_hz: f64,
    fft_size: usize,
    window_type: String,
) -> Result<crate::hardware::dsp::FftAnalysisResult, String> {
    Ok(crate::hardware::dsp::compute_fft_spectrum(&samples, sample_rate_hz, fft_size, &window_type))
}

#[tauri::command]
pub fn start_network_stream(
    app: AppHandle,
    state: State<'_, AppState>,
    name: String,
    mode: String,
    host: String,
    port: u16,
) -> Result<(), String> {
    let net_mode = match mode.to_lowercase().as_str() {
        "tcp_client" | "tcpclient" | "client" => NetworkMode::TcpClient,
        "tcp_server" | "tcpserver" | "server" => NetworkMode::TcpServer,
        "udp" | "udp_socket" => NetworkMode::UdpSocket,
        _ => return Err(format!("Unsupported network mode: {}", mode)),
    };
    state.network.start_stream(app, name, net_mode, host, port)
}

#[tauri::command]
pub fn stop_network_stream(
    state: State<'_, AppState>,
    name: String,
) -> Result<(), String> {
    state.network.stop_stream(&name);
    Ok(())
}

#[tauri::command]
pub fn list_network_streams(
    state: State<'_, AppState>,
) -> Result<Vec<NetworkStreamInfo>, String> {
    Ok(state.network.list_sessions())
}

#[tauri::command]
pub fn send_network_data(
    state: State<'_, AppState>,
    name: String,
    data: Vec<u8>,
) -> Result<usize, String> {
    state.network.write_data(&name, &data)
}

#[tauri::command]
pub fn pyocd_detect_rtos(
    app: AppHandle,
    state: State<'_, AppState>,
    elf_path: String,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "detect_rtos_kernel",
        json!({
            "elf_path": elf_path,
        }),
    )
}

#[tauri::command]
pub fn pyocd_capture_framebuffer(
    app: AppHandle,
    state: State<'_, AppState>,
    address: String,
    width: u32,
    height: u32,
    pixel_format: String,
    probe_id: Option<String>,
    target_override: Option<String>,
) -> Result<Value, String> {
    state.daemon.ensure_started(&app)?;
    state.daemon.call_rpc(
        "capture_lcd_framebuffer",
        json!({
            "address": address,
            "width": width,
            "height": height,
            "pixel_format": pixel_format,
            "probe_id": probe_id,
            "target_override": target_override,
        }),
    )
}

#[tauri::command]
pub fn modbus_build_ascii_request(
    slave_id: u8,
    func_code: u8,
    start_addr: u16,
    count_or_val: u16,
    extra_values: Option<Vec<u16>>,
) -> Result<Vec<u8>, String> {
    Ok(crate::hardware::modbus::build_modbus_ascii_request(
        slave_id,
        func_code,
        start_addr,
        count_or_val,
        extra_values.as_deref(),
    ))
}



