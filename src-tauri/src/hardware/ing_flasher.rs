use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter};
use super::serial_manager::SerialManager;

// ----------------------------------------------------------------------------
// CRC-16 (Modbus/ARC) Table matching icsdw.py
// ----------------------------------------------------------------------------
const AUCH_CRC_HI: [u8; 256] = [
    0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
    0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
    0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
    0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
    0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
    0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
    0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
    0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
    0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
    0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
    0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
    0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
    0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
    0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
    0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40, 0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41,
    0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40
];

const AUCH_CRC_LO: [u8; 256] = [
    0x00, 0xC0, 0xC1, 0x01, 0xC3, 0x03, 0x02, 0xC2, 0xC6, 0x06, 0x07, 0xC7, 0x05, 0xC5, 0xC4, 0x04,
    0xCC, 0x0C, 0x0D, 0xCD, 0x0F, 0xCF, 0xCE, 0x0E, 0x0A, 0xCA, 0xCB, 0x0B, 0xC9, 0x09, 0x08, 0xC8,
    0xD8, 0x18, 0x19, 0xD9, 0x1B, 0xDB, 0xDA, 0x1A, 0x1E, 0xDE, 0xDF, 0x1F, 0xDD, 0x1D, 0x1C, 0xDC,
    0x14, 0xD4, 0xD5, 0x15, 0xD7, 0x17, 0x16, 0xD6, 0xD2, 0x12, 0x13, 0xD3, 0x11, 0xD1, 0xD0, 0x10,
    0xF0, 0x30, 0x31, 0xF1, 0x33, 0xF3, 0xF2, 0x32, 0x36, 0xF6, 0xF7, 0x37, 0xF5, 0x35, 0x34, 0xF4,
    0x3C, 0xFC, 0xFD, 0x3D, 0xFF, 0x3F, 0x3E, 0xFE, 0xFA, 0x3A, 0x3B, 0xFB, 0x39, 0xF9, 0xF8, 0x38,
    0x28, 0xE8, 0xE9, 0x29, 0xEB, 0x2B, 0x2A, 0xEA, 0xEE, 0x2E, 0x2F, 0xEF, 0x2D, 0xED, 0xEC, 0x2C,
    0xE4, 0x24, 0x25, 0xE5, 0x27, 0xE7, 0xE6, 0x26, 0x22, 0xE2, 0xE3, 0x23, 0xE1, 0x21, 0x20, 0xE0,
    0xA0, 0x60, 0x61, 0xA1, 0x63, 0xA3, 0xA2, 0x62, 0x66, 0xA6, 0xA7, 0x67, 0xA5, 0x65, 0x64, 0xA4,
    0x6C, 0xAC, 0xAD, 0x6D, 0xAF, 0x6F, 0x6E, 0xAE, 0xAA, 0x6A, 0x6B, 0xAB, 0x69, 0xA9, 0xA8, 0x68,
    0x78, 0xB8, 0xB9, 0x79, 0xBB, 0x7B, 0x7A, 0xBA, 0xBE, 0x7E, 0x7F, 0xBF, 0x7D, 0xBD, 0xBC, 0x7C,
    0xB4, 0x74, 0x75, 0xB5, 0x77, 0xB7, 0xB6, 0x76, 0x72, 0xB2, 0xB3, 0x73, 0xB1, 0x71, 0x70, 0xB0,
    0x50, 0x90, 0x91, 0x51, 0x93, 0x53, 0x52, 0x92, 0x96, 0x56, 0x57, 0x97, 0x55, 0x95, 0x94, 0x54,
    0x9C, 0x5C, 0x5D, 0x9D, 0x5F, 0x9F, 0x9E, 0x5E, 0x5A, 0x9A, 0x9B, 0x5B, 0x99, 0x59, 0x58, 0x98,
    0x88, 0x48, 0x49, 0x89, 0x4B, 0x8B, 0x8A, 0x4A, 0x4E, 0x8E, 0x8F, 0x4F, 0x8D, 0x4D, 0x4C, 0x8C,
    0x44, 0x84, 0x85, 0x45, 0x87, 0x47, 0x46, 0x86, 0x82, 0x42, 0x43, 0x83, 0x41, 0x81, 0x80, 0x40
];

pub fn calc_crc_16(data: &[u8]) -> u16 {
    let mut uch_crc_hi: u8 = 0xFF;
    let mut uch_crc_lo: u8 = 0xFF;

    for &b in data {
        let u_index = (uch_crc_hi ^ b) as usize;
        uch_crc_hi = uch_crc_lo ^ AUCH_CRC_HI[u_index];
        uch_crc_lo = AUCH_CRC_LO[u_index];
    }

    ((uch_crc_hi as u16) << 8) | (uch_crc_lo as u16)
}

// ----------------------------------------------------------------------------
// Constants
// ----------------------------------------------------------------------------
pub const RAM_BASE_ADDR: u32 = 0x20000000;
pub const AHB_QSPI_MEM_BASE: u32 = 0x04000000;

pub const ACK: &[u8] = b"#$ack\n";
pub const NACK: &[u8] = b"#$nak\n";
pub const STATUS_LOCKED: &[u8] = b"#$lck\n";
pub const STATUS_UNLOCKED: &[u8] = b"#$ulk\n";

pub const CMD_QLOCKSTATE: &[u8] = b"#$state";
pub const CMD_UNLOCK: &[u8] = b"#$unlck";
pub const CMD_LOCK: &[u8] = b"#$lockk";
pub const CMD_SET_BAUD: &[u8] = b"#$sbaud";

// 918 constants
pub const BOOT_HELLO_918: &[u8] = b"UartBurnStart\n";
pub const SEND_PAGE_918: &[u8] = b"#$start";
pub const SEND_RAM_918: &[u8] = b"#$stram";
pub const SET_ENTRY_918: &[u8] = b"#$setja";
pub const CMD_LAUNCH_918: &[u8] = b"#$jumpp";
pub const CMD_JUMPD_918: &[u8] = b"#$jumpd";
pub const PAGE_SIZE_918: usize = 8 * 1024;

// 916 constants
pub const BOOT_HELLO_916: &[u8] = b"UartBurnStart916\n";
pub const BOOT_HELLO_920: &[u8] = b"UartBurnStart920\n";
pub const SEND_PAGE_916: &[u8] = b"#$u2fsh";
pub const SEND_RAM_DATA_916: &[u8] = b"#$u2ram";
pub const ERASE_SECTOR_916: &[u8] = b"#$stera";
pub const CMD_LAUNCH_916: &[u8] = b"#$j2fsh";
pub const CMD_FLASH_SET_916: &[u8] = b"#$fshst";
pub const CMD_JRAM_916: &[u8] = b"#$j2ram";
pub const PAGE_SIZE_916: usize = 256;
pub const SECTOR_SIZE_916: usize = 4096;

// Global cancel flag
pub static FLASH_CANCEL: AtomicBool = AtomicBool::new(false);

// ----------------------------------------------------------------------------
// Data Structures
// ----------------------------------------------------------------------------
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngBinItem {
    pub index: usize,
    pub name: String,
    pub checked: bool,
    pub file_name: String,
    pub resolved_path: String,
    pub address: u32,
    pub size_bytes: Option<usize>,
    pub file_exists: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngIniConfig {
    pub file_path: String,
    pub family: String, // "ing916" | "ing918" | "ing20"
    pub baud: u32,
    pub entry_address: Option<u32>,
    pub set_entry: bool,
    pub launch: bool,
    pub reset_reserved_flash: bool,
    pub items: Vec<IngBinItem>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngFlashRequest {
    pub port_name: String,
    pub mode: String, // "ini" | "single"
    pub ini_path: Option<String>,
    pub single_file_path: Option<String>,
    pub single_address: Option<String>,
    pub family: Option<String>, // "auto" | "ing916" | "ing918"
    pub target_baud: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngFlashProgress {
    pub stage: String, // "init", "handshake", "unlock", "baudrate", "erase", "burn", "launch", "success", "error"
    pub file_name: String,
    pub current_bytes: usize,
    pub total_bytes: usize,
    pub percentage: f32,
    pub speed_kbps: f32,
    pub message: String,
}

// ----------------------------------------------------------------------------
// INI Parsing
// ----------------------------------------------------------------------------
pub fn parse_ini_file(ini_path_str: &str) -> Result<IngIniConfig, String> {
    let ini_path = Path::new(ini_path_str);
    if !ini_path.exists() {
        return Err(format!("INI 方案文件不存在: {}", ini_path_str));
    }

    let parent_dir = ini_path.parent().unwrap_or(Path::new("."));
    let mut file = File::open(ini_path).map_err(|e| format!("打开 INI 文件失败: {}", e))?;
    let mut content_bytes = Vec::new();
    file.read_to_end(&mut content_bytes)
        .map_err(|e| format!("读取 INI 文件内容失败: {}", e))?;

    let content = String::from_utf8(content_bytes.clone()).unwrap_or_else(|_| {
        content_bytes.iter().map(|&b| b as char).collect()
    });

    let mut current_section = String::new();
    let mut sections: HashMap<String, HashMap<String, String>> = HashMap::new();

    for line in content.lines() {
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.starts_with('#') || trimmed.starts_with(';') {
            continue;
        }

        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            current_section = trimmed[1..trimmed.len() - 1].trim().to_lowercase();
            sections.entry(current_section.clone()).or_default();
            continue;
        }

        if let Some(eq_idx) = trimmed.find('=') {
            let key = trimmed[..eq_idx].trim().to_lowercase();
            let val = trimmed[eq_idx + 1..].trim().to_string();
            if !current_section.is_empty() {
                sections.entry(current_section.clone()).or_default().insert(key, val);
            }
        }
    }

    if sections.is_empty() || !sections.contains_key("main") {
        let alt_candidate = parent_dir.join("flash_download.ini");
        let hint = if alt_candidate.exists() {
            format!("，同目录下检测到可用的烧录配置: {}", alt_candidate.display())
        } else {
            "".to_string()
        };
        return Err(format!(
            "选中的 INI 文件格式不符合固件烧录规范（缺少 [main] 或 [bin-x] 配置节点）{}",
            hint
        ));
    }

    let family = sections
        .get("main")
        .and_then(|m| m.get("family"))
        .map(|s| s.to_lowercase())
        .unwrap_or_else(|| "ing916".to_string());

    let baud = sections
        .get("uart")
        .and_then(|m| m.get("baud"))
        .and_then(|s| s.parse::<u32>().ok())
        .unwrap_or(115200);

    let opt_sec = sections.get("options");
    let launch = opt_sec
        .and_then(|m| m.get("launch"))
        .map(|s| s == "1" || s.eq_ignore_ascii_case("true"))
        .unwrap_or(false);
    let set_entry = opt_sec
        .and_then(|m| m.get("set-entry"))
        .map(|s| s == "1" || s.eq_ignore_ascii_case("true"))
        .unwrap_or(false);
    let reset_reserved_flash = opt_sec
        .and_then(|m| m.get("resetreservedflash"))
        .map(|s| s == "1" || s.eq_ignore_ascii_case("true"))
        .unwrap_or(false);

    let entry_address = opt_sec
        .and_then(|m| m.get("entry"))
        .and_then(|s| parse_hex_or_dec(s).ok());

    let mut items = Vec::new();
    for i in 0..10 {
        let sec_key = format!("bin-{}", i);
        if let Some(sec) = sections.get(&sec_key) {
            let name = sec.get("name").cloned().unwrap_or_default();
            let checked = sec.get("checked").map(|s| s == "1" || s.eq_ignore_ascii_case("true")).unwrap_or(false);
            let file_name = sec.get("filename").cloned().unwrap_or_default();
            let addr_str = sec.get("address").cloned().unwrap_or_else(|| "0".to_string());
            let address = parse_hex_or_dec(&addr_str).unwrap_or(0);

            let mut resolved_path = String::new();
            let mut file_exists = false;
            let mut size_bytes = None;

            if !file_name.is_empty() {
                let candidate = Path::new(&file_name);
                let full = if candidate.is_absolute() {
                    candidate.to_path_buf()
                } else {
                    parent_dir.join(candidate)
                };

                resolved_path = full.to_string_lossy().to_string();
                if full.exists() {
                    file_exists = true;
                    if let Ok(meta) = full.metadata() {
                        size_bytes = Some(meta.len() as usize);
                    }
                }
            }

            items.push(IngBinItem {
                index: i,
                name,
                checked,
                file_name,
                resolved_path,
                address,
                size_bytes,
                file_exists,
            });
        }
    }

    Ok(IngIniConfig {
        file_path: ini_path_str.to_string(),
        family,
        baud,
        entry_address,
        set_entry,
        launch,
        reset_reserved_flash,
        items,
    })
}

pub fn parse_hex_or_dec(s: &str) -> Result<u32, String> {
    let clean = s.trim();
    if clean.starts_with("0x") || clean.starts_with("0X") {
        u32::from_str_radix(&clean[2..], 16)
            .map_err(|e| format!("无效十六进制地址: {} ({})", clean, e))
    } else {
        clean.parse::<u32>()
            .map_err(|e| format!("无效数字地址: {} ({})", clean, e))
    }
}

// ----------------------------------------------------------------------------
// Intel HEX Parser
// ----------------------------------------------------------------------------
#[derive(Debug, Clone)]
pub struct HexSegment {
    pub address: u32,
    pub data: Vec<u8>,
}

pub fn parse_intel_hex(file_path: &Path) -> Result<Vec<HexSegment>, String> {
    let mut file = File::open(file_path).map_err(|e| format!("打开 HEX 失败: {}", e))?;
    let mut text = String::new();
    file.read_to_string(&mut text)
        .map_err(|e| format!("读取 HEX 失败: {}", e))?;

    let mut segments: Vec<HexSegment> = Vec::new();
    let mut upper_address: u32 = 0;

    for line in text.lines() {
        let trimmed = line.trim();
        if !trimmed.starts_with(':') || trimmed.len() < 11 {
            continue;
        }

        let bytes_res: Result<Vec<u8>, _> = (1..trimmed.len())
            .step_by(2)
            .map(|i| u8::from_str_radix(&trimmed[i..i + 2], 16))
            .collect();
        let bytes = bytes_res.map_err(|e| format!("解析 HEX 记录字节失败: {}", e))?;
        if bytes.len() < 5 {
            continue;
        }

        let byte_count = bytes[0] as usize;
        let offset = ((bytes[1] as u32) << 8) | (bytes[2] as u32);
        let record_type = bytes[3];
        let data = &bytes[4..4 + byte_count];

        match record_type {
            0x00 => {
                let full_addr = upper_address | offset;
                if let Some(last_seg) = segments.last_mut() {
                    let next_expected = last_seg.address + last_seg.data.len() as u32;
                    if next_expected == full_addr {
                        last_seg.data.extend_from_slice(data);
                        continue;
                    }
                }
                segments.push(HexSegment {
                    address: full_addr,
                    data: data.to_vec(),
                });
            }
            0x01 => break, // EOF
            0x02 => {
                if data.len() >= 2 {
                    upper_address = (((data[0] as u32) << 8) | (data[1] as u32)) << 4;
                }
            }
            0x04 => {
                if data.len() >= 2 {
                    upper_address = (((data[0] as u32) << 8) | (data[1] as u32)) << 16;
                }
            }
            _ => {}
        }
    }

    if segments.is_empty() {
        return Err("HEX 文件中未找到有效固件数据记录".to_string());
    }

    Ok(segments)
}

// ----------------------------------------------------------------------------
// Flasher Execution Engine
// ----------------------------------------------------------------------------
pub struct FlasherSerial {
    port: Box<dyn serialport::SerialPort>,
}

impl FlasherSerial {
    pub fn new(port_name: &str, baud: u32) -> Result<Self, String> {
        let port = serialport::new(port_name, baud)
            .timeout(Duration::from_millis(1500))
            .data_bits(serialport::DataBits::Eight)
            .stop_bits(serialport::StopBits::One)
            .parity(serialport::Parity::None)
            .open()
            .map_err(|e| format!("打开串口 {} 失败: {}", port_name, e))?;

        Ok(Self { port })
    }

    pub fn set_timeout(&mut self, timeout: Duration) -> Result<(), String> {
        self.port.set_timeout(timeout).map_err(|e| e.to_string())
    }

    pub fn set_baud_rate(&mut self, baud: u32) -> Result<(), String> {
        self.port.set_baud_rate(baud).map_err(|e| e.to_string())
    }

    pub fn toggle_reset_for_boot(&mut self) -> Result<(), String> {
        let _ = self.port.write_request_to_send(true);
        let _ = self.port.write_data_terminal_ready(true);
        std::thread::sleep(Duration::from_millis(100));
        let _ = self.port.write_data_terminal_ready(false);
        let _ = self.port.write_request_to_send(false);
        Ok(())
    }

    pub fn write_all(&mut self, data: &[u8]) -> Result<(), String> {
        self.port.write_all(data).map_err(|e| format!("串口写入失败: {}", e))?;
        self.port.flush().map_err(|e| format!("串口刷新失败: {}", e))
    }

    pub fn read_exact(&mut self, len: usize) -> Result<Vec<u8>, String> {
        let mut buf = vec![0u8; len];
        self.port.read_exact(&mut buf).map_err(|e| format!("串口读取响应超时或失败: {}", e))?;
        Ok(buf)
    }

    pub fn exec_cmd(&mut self, cmd: &[u8]) -> Result<Vec<u8>, String> {
        self.write_all(cmd)?;
        self.read_exact(ACK.len())
    }

    pub fn wait_hello(&mut self, target_hello: &[u8], timeout: Duration) -> Result<(), String> {
        self.set_timeout(Duration::from_millis(200))?;
        let start = Instant::now();
        let mut acc = Vec::new();

        while start.elapsed() < timeout {
            if FLASH_CANCEL.load(Ordering::SeqCst) {
                return Err("烧录已被用户取消".to_string());
            }

            let mut b = [0u8; 1];
            match self.port.read(&mut b) {
                Ok(1) => {
                    acc.push(b[0]);
                    if acc.len() >= target_hello.len() {
                        let tail = &acc[acc.len() - target_hello.len()..];
                        if tail == target_hello {
                            return Ok(());
                        }
                    }
                }
                Ok(_) => {}
                Err(ref e) if e.kind() == std::io::ErrorKind::TimedOut => {}
                Err(e) => return Err(format!("握手读取出错: {}", e)),
            }
        }

        Err(format!("等待芯片握手信号超时 (未收到 {:?})，请检查硬件接线或按复位键", String::from_utf8_lossy(target_hello)))
    }
}

// ----------------------------------------------------------------------------
// Flasher Routines
// ----------------------------------------------------------------------------
pub fn run_flash_task(
    app: AppHandle,
    req: IngFlashRequest,
    serial_mgr: Arc<SerialManager>,
    previous_baud: Option<u32>,
) {
    FLASH_CANCEL.store(false, Ordering::SeqCst);
    let port_name = req.port_name.clone();

    let emit_progress = |stage: &str, file: &str, curr: usize, total: usize, pct: f32, speed: f32, msg: &str| {
        let _ = app.emit("ing-flash-progress", IngFlashProgress {
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
    let res = run_flash_core(&app, &req, &emit_progress);
    if let Err(err_msg) = res {
        emit_progress("error", "", 0, 0, 0.0, 0.0, &err_msg);
    }

    // Always restore the port if it was previously active in the serial terminal
    if let Some(baud) = previous_baud {
        emit_progress("restore", "", 0, 0, 0.0, 0.0, &format!("烧录已完成，正在恢复终端串口监听 (波特率: {})...", baud));
        if let Err(e) = serial_mgr.resume_after_flashing(&app, &port_name, baud) {
            eprintln!("Failed to restore serial port {} after flashing: {}", port_name, e);
        }
    }
}

fn run_flash_core<F>(_app: &AppHandle, req: &IngFlashRequest, emit_progress: &F) -> Result<(), String>
where
    F: Fn(&str, &str, usize, usize, f32, f32, &str),
{
    let port_name = req.port_name.clone();
    emit_progress("init", "", 0, 0, 0.0, 0.0, "准备初始化串口并建立硬件连接...");

    let mut flasher = FlasherSerial::new(&port_name, 115200)
        .map_err(|e| format!("串口打开失败（请确认端口未被其他外部程序占用）: {}", e))?;

    // Determine target chips and firmware files
    let mut files_to_flash: Vec<(String, u32, Vec<u8>)> = Vec::new();
    let mut family = req.family.clone().unwrap_or_else(|| "auto".to_string()).to_lowercase();
    let mut target_baud = req.target_baud.unwrap_or(115200);
    let mut should_launch = true;
    let mut should_set_entry = false;
    let mut entry_address: Option<u32> = None;
    let mut reset_reserved = false;

    if req.mode == "ini" {
        let ini_p = match req.ini_path {
            Some(ref p) if !p.is_empty() => p,
            _ => return Err("未指定 INI 配置文件路径".to_string()),
        };

        emit_progress("init", "", 0, 0, 0.0, 0.0, &format!("正在解析 INI 烧录配置: {}", ini_p));
        let cfg = parse_ini_file(ini_p)?;

        if family == "auto" {
            family = cfg.family;
        }
        if req.target_baud.is_none() || req.target_baud == Some(115200) {
            target_baud = cfg.baud;
        }
        should_launch = cfg.launch;
        should_set_entry = cfg.set_entry;
        entry_address = cfg.entry_address;
        reset_reserved = cfg.reset_reserved_flash;

        for item in cfg.items {
            if !item.checked {
                continue;
            }
            if !item.file_exists {
                return Err(format!("固件文件不存在: {}", item.resolved_path));
            }
            let mut buf = Vec::new();
            if let Ok(mut f) = File::open(&item.resolved_path) {
                let _ = f.read_to_end(&mut buf);
                files_to_flash.push((item.name, item.address, buf));
            }
        }
    } else {
        // Single File Mode (BIN or HEX)
        let file_path_str = match req.single_file_path {
            Some(ref p) if !p.is_empty() => p,
            _ => return Err("未选择待烧录的 BIN 或 HEX 固件文件".to_string()),
        };
        let p = Path::new(file_path_str);
        if !p.exists() {
            return Err(format!("固件文件不存在: {}", file_path_str));
        }

        let is_hex = file_path_str.to_lowercase().ends_with(".hex");
        if is_hex {
            emit_progress("init", "", 0, 0, 0.0, 0.0, "解析 Intel HEX 固件记录...");
            let segs = parse_intel_hex(p).map_err(|e| format!("解析 HEX 记录失败: {}", e))?;
            for (i, seg) in segs.into_iter().enumerate() {
                files_to_flash.push((format!("HEX_SEG_{} (0x{:08X})", i, seg.address), seg.address, seg.data));
            }
        } else {
            // Raw BIN file
            let addr_str = req.single_address.clone().unwrap_or_else(|| "0x02002000".to_string());
            let addr = parse_hex_or_dec(&addr_str).map_err(|e| format!("烧录地址格式错误: {}", e))?;
            let mut buf = Vec::new();
            if let Ok(mut f) = File::open(p) {
                let _ = f.read_to_end(&mut buf);
                let fname = p.file_name().and_then(|n| n.to_str()).unwrap_or("firmware.bin");
                files_to_flash.push((fname.to_string(), addr, buf));
            }
        }
    }

    if files_to_flash.is_empty() {
        return Err("没有可烧录的固件内容 (请确认文件已勾选且不为空)".to_string());
    }

    if family == "auto" {
        family = "ing916".to_string();
    }

    let is_918 = family.contains("918");
    emit_progress("handshake", "", 0, 0, 0.0, 0.0, &format!("正在向芯片发送 RTS/DTR 复位序列，等待 {} Boot 握手...", if is_918 { "ING918" } else { "ING916" }));

    let _ = flasher.toggle_reset_for_boot();
    let hello_seq = if is_918 { BOOT_HELLO_918 } else { BOOT_HELLO_916 };

    if let Err(e) = flasher.wait_hello(hello_seq, Duration::from_secs(4)) {
        if !is_918 {
            let _ = flasher.toggle_reset_for_boot();
            if let Err(e2) = flasher.wait_hello(BOOT_HELLO_920, Duration::from_secs(2)) {
                return Err(format!("握手失败: {} / {}", e, e2));
            }
        } else {
            return Err(format!("握手失败: {}", e));
        }
    }

    emit_progress("unlock", "", 0, 0, 0.0, 0.0, "握手成功！检查芯片 Flash 加密与保护状态...");

    // Check lock state
    if let Ok(rsp) = flasher.exec_cmd(CMD_QLOCKSTATE) {
        if rsp == STATUS_LOCKED {
            emit_progress("unlock", "", 0, 0, 0.0, 0.0, "检测到 Flash 已上锁，正在执行解锁指令...");
            let _ = flasher.exec_cmd(CMD_UNLOCK);
        }
    }

    // ING916 QSPI Init
    if !is_918 {
        emit_progress("init", "", 0, 0, 0.0, 0.0, "配置 ING916 QSPI 接口模式 (0x0200)...");
        let mut set_qspi_cmd = Vec::new();
        set_qspi_cmd.extend_from_slice(CMD_FLASH_SET_916);
        set_qspi_cmd.extend_from_slice(&0x0200u16.to_le_bytes());
        let _ = flasher.exec_cmd(&set_qspi_cmd);
    }

    // Baudrate negotiation
    if target_baud != 115200 {
        emit_progress("baudrate", "", 0, 0, 0.0, 0.0, &format!("与芯片协商切换高速烧录波特率 -> {} bps...", target_baud));
        let mut baud_cmd = Vec::new();
        baud_cmd.extend_from_slice(CMD_SET_BAUD);
        baud_cmd.extend_from_slice(&target_baud.to_le_bytes());
        if let Ok(rsp) = flasher.exec_cmd(&baud_cmd) {
            if rsp == ACK {
                std::thread::sleep(Duration::from_millis(60));
                let _ = flasher.set_baud_rate(target_baud);
                std::thread::sleep(Duration::from_millis(60));
            }
        }
    }

    // Reset reserved flash if requested (ING916)
    if !is_918 && reset_reserved {
        emit_progress("erase", "", 0, 0, 0.0, 0.0, "擦除保留扇区 0x02000000...");
        let mut erase_cmd = Vec::new();
        erase_cmd.extend_from_slice(ERASE_SECTOR_916);
        erase_cmd.extend_from_slice(&0x02000000u32.to_le_bytes());
        let _ = flasher.exec_cmd(&erase_cmd);
    }

    // Compute total bytes across all files
    let grand_total_bytes: usize = files_to_flash.iter().map(|(_, _, d)| d.len()).sum();
    let mut total_burned_bytes = 0usize;
    let burn_start_time = Instant::now();

    for (file_idx, (name, addr, data)) in files_to_flash.iter().enumerate() {
        if FLASH_CANCEL.load(Ordering::SeqCst) {
            return Err("烧录已被取消".to_string());
        }

        let file_total = data.len();
        let mut file_offset = 0usize;
        emit_progress("burn", name, total_burned_bytes, grand_total_bytes, 
            (total_burned_bytes as f32 / grand_total_bytes.max(1) as f32) * 100.0, 0.0,
            &format!("[{}/{}] 开始烧录固件: {} (目标地址: 0x{:08X}, 大小: {} 字节)", file_idx + 1, files_to_flash.len(), name, addr, file_total)
        );

        if is_918 {
            // ING918 Page-based Burn (8KB per page)
            while file_offset < file_total {
                if FLASH_CANCEL.load(Ordering::SeqCst) {
                    return Err("烧录已被取消".to_string());
                }

                let seg_len = (file_total - file_offset).min(PAGE_SIZE_918);
                let current_addr = addr + file_offset as u32;
                let chunk = &data[file_offset..file_offset + seg_len];

                let cmd_prefix = if current_addr < RAM_BASE_ADDR { SEND_PAGE_918 } else { SEND_RAM_918 };
                let mut page_req = Vec::new();
                page_req.extend_from_slice(cmd_prefix);
                page_req.extend_from_slice(&current_addr.to_le_bytes());
                page_req.extend_from_slice(&(seg_len as u16).to_le_bytes());

                match flasher.exec_cmd(&page_req) {
                    Ok(rsp) if rsp == ACK => {},
                    other => {
                        return Err(format!("下发页地址失败: 0x{:08X}, 响应: {:?}", current_addr, other));
                    }
                }

                flasher.write_all(chunk).map_err(|e| format!("写入数据失败: {}", e))?;

                let crc = calc_crc_16(chunk);
                flasher.write_all(&crc.to_le_bytes()).map_err(|e| format!("写入 CRC 校验失败: {}", e))?;

                match flasher.read_exact(ACK.len()) {
                    Ok(rsp) if rsp == ACK => {},
                    other => {
                        return Err(format!("CRC 校验应答失败 (地址 0x{:08X}): {:?}", current_addr, other));
                    }
                }

                file_offset += seg_len;
                total_burned_bytes += seg_len;

                let elapsed_sec = burn_start_time.elapsed().as_secs_f32().max(0.001);
                let speed_kbps = (total_burned_bytes as f32 / 1024.0) / elapsed_sec;
                let pct = (total_burned_bytes as f32 / grand_total_bytes.max(1) as f32) * 100.0;
                emit_progress("burn", name, total_burned_bytes, grand_total_bytes, pct, speed_kbps,
                    &format!("正在传输: 0x{:08X} ({}/{} 字节)", current_addr + seg_len as u32, total_burned_bytes, grand_total_bytes)
                );
            }
        } else {
            // ING916 Sector-erase (4KB) & Page-write (256B)
            let mut sector_offset = 0usize;
            while sector_offset < file_total {
                if FLASH_CANCEL.load(Ordering::SeqCst) {
                    return Err("烧录已被取消".to_string());
                }

                let current_sector_addr = addr + sector_offset as u32;
                if current_sector_addr < RAM_BASE_ADDR {
                    let mut erase_cmd = Vec::new();
                    erase_cmd.extend_from_slice(ERASE_SECTOR_916);
                    erase_cmd.extend_from_slice(&current_sector_addr.to_le_bytes());
                    match flasher.exec_cmd(&erase_cmd) {
                        Ok(rsp) if rsp == ACK => {},
                        other => {
                            return Err(format!("扇区擦除失败: 0x{:08X}, 响应: {:?}", current_sector_addr, other));
                        }
                    }
                }

                let sector_bytes = (file_total - sector_offset).min(SECTOR_SIZE_916);
                let mut page_offset = 0usize;

                while page_offset < sector_bytes {
                    if FLASH_CANCEL.load(Ordering::SeqCst) {
                        return Err("烧录已被取消".to_string());
                    }

                    let page_len = (sector_bytes - page_offset).min(PAGE_SIZE_916);
                    let page_addr = current_sector_addr + page_offset as u32;
                    let chunk = &data[sector_offset + page_offset..sector_offset + page_offset + page_len];

                    let cmd_prefix = if page_addr < RAM_BASE_ADDR { SEND_PAGE_916 } else { SEND_RAM_DATA_916 };
                    let mut page_cmd = Vec::new();
                    page_cmd.extend_from_slice(cmd_prefix);
                    page_cmd.extend_from_slice(&page_addr.to_le_bytes());
                    page_cmd.push((page_len - 1) as u8);

                    match flasher.exec_cmd(&page_cmd) {
                        Ok(rsp) if rsp == ACK => {},
                        other => {
                            return Err(format!("写页指令失败: 0x{:08X}, 响应: {:?}", page_addr, other));
                        }
                    }

                    flasher.write_all(chunk).map_err(|e| format!("写入页面数据失败: {}", e))?;

                    let crc = calc_crc_16(chunk);
                    flasher.write_all(&crc.to_le_bytes()).map_err(|e| format!("写入 CRC 校验失败: {}", e))?;

                    match flasher.read_exact(ACK.len()) {
                        Ok(rsp) if rsp == ACK => {},
                        other => {
                            return Err(format!("CRC 页面校验应答失败 (地址 0x{:08X}): {:?}", page_addr, other));
                        }
                    }

                    page_offset += page_len;
                    total_burned_bytes += page_len;

                    let elapsed_sec = burn_start_time.elapsed().as_secs_f32().max(0.001);
                    let speed_kbps = (total_burned_bytes as f32 / 1024.0) / elapsed_sec;
                    let pct = (total_burned_bytes as f32 / grand_total_bytes.max(1) as f32) * 100.0;
                    emit_progress("burn", name, total_burned_bytes, grand_total_bytes, pct, speed_kbps,
                        &format!("已烧录: 0x{:08X} ({}/{} 字节)", page_addr + page_len as u32, total_burned_bytes, grand_total_bytes)
                    );
                }

                sector_offset += sector_bytes;
            }
        }
    }

    // Set Entry point if needed
    if should_set_entry {
        if let Some(entry) = entry_address {
            emit_progress("launch", "", grand_total_bytes, grand_total_bytes, 100.0, 0.0, &format!("设置入口执行地址: 0x{:08X}...", entry));
            if is_918 {
                let mut entry_cmd = Vec::new();
                entry_cmd.extend_from_slice(SET_ENTRY_918);
                entry_cmd.extend_from_slice(&entry.to_le_bytes());
                let _ = flasher.exec_cmd(&entry_cmd);
            }
        }
    }

    // Launch application
    if should_launch {
        emit_progress("launch", "", grand_total_bytes, grand_total_bytes, 100.0, 0.0, "发送启动跳转指令，目标开始运行！");
        if is_918 {
            let _ = flasher.write_all(CMD_LAUNCH_918);
        } else {
            let _ = flasher.write_all(CMD_LAUNCH_916);
        }
    }

    let elapsed_sec = burn_start_time.elapsed().as_secs_f32();
    emit_progress("success", "", grand_total_bytes, grand_total_bytes, 100.0, (grand_total_bytes as f32 / 1024.0) / elapsed_sec.max(0.001), 
        &format!("全部烧录成功！共写入 {} 字节，耗时 {:.2} 秒", grand_total_bytes, elapsed_sec)
    );

    // Explicitly drop flasher before returning to immediately close the COM port handle
    drop(flasher);
    std::thread::sleep(Duration::from_millis(50));

    Ok(())
}
