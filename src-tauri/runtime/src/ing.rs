use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

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
    0x00, 0xC1, 0x81, 0x40, 0x01, 0xC0, 0x80, 0x41, 0x01, 0xC0, 0x80, 0x41, 0x00, 0xC1, 0x81, 0x40,
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
    0x44, 0x84, 0x85, 0x45, 0x87, 0x47, 0x46, 0x86, 0x82, 0x42, 0x43, 0x83, 0x41, 0x81, 0x80, 0x40,
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
pub static FLASH_BUSY: AtomicBool = AtomicBool::new(false);
pub static FLASH_PORT: std::sync::Mutex<Option<String>> = std::sync::Mutex::new(None);
pub static FLASH_JOB: std::sync::Mutex<Option<String>> = std::sync::Mutex::new(None);

pub struct FlashPermit;
impl Drop for FlashPermit {
    fn drop(&mut self) {
        *FLASH_PORT.lock().unwrap() = None;
        *FLASH_JOB.lock().unwrap() = None;
        FLASH_BUSY.store(false, Ordering::SeqCst);
    }
}

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
    pub job_id: String,
    pub port_name: String,
    pub mode: String, // "ini" | "single"
    pub ini_path: Option<String>,
    pub single_file_path: Option<String>,
    pub single_address: Option<String>,
    pub family: Option<String>, // "auto" | "ing916" | "ing918"
    pub target_baud: Option<u32>,
    pub manual_boot: Option<bool>,
    pub timeout_sec: Option<u64>,
}

pub struct FlashOptions {
    pub cancelled: Arc<dyn Fn() -> bool + Send + Sync>,
    pub pin_reset: Option<crate::reset::PinReset>,
    pub suppress_launch: bool,
}
/// HIL owns boot entry separately through a verified reset profile. Never infer wiring.
pub fn hil_request(p: &serde_json::Value, job: &str) -> IngFlashRequest {
    IngFlashRequest {
        job_id: job.into(),
        port_name: p["port_name"].as_str().unwrap_or("").into(),
        mode: "ini".into(),
        ini_path: p["file_path"].as_str().map(str::to_string),
        single_file_path: None,
        single_address: None,
        family: None,
        target_baud: None,
        // A chip family or reference downloader is not evidence of board wiring.
        // HIL enters ISP through an explicit reset profile (or a manual action).
        manual_boot: Some(true),
        timeout_sec: Some(15),
    }
}
impl Default for FlashOptions {
    fn default() -> Self {
        Self {
            cancelled: Arc::new(|| FLASH_CANCEL.load(Ordering::SeqCst)),
            pin_reset: None,
            suppress_launch: false,
        }
    }
}
pub struct PreparedFlash {
    files: Vec<(String, u32, Vec<u8>)>,
    family: String,
    baud: u32,
    launch: bool,
    set_entry: bool,
    entry: Option<u32>,
    reset_reserved: bool,
}
pub fn prepare(req: &IngFlashRequest) -> Result<PreparedFlash, String> {
    let mut plan = PreparedFlash {
        files: vec![],
        family: req.family.clone().unwrap_or("auto".into()).to_lowercase(),
        baud: req.target_baud.unwrap_or(115200),
        launch: true,
        set_entry: false,
        entry: None,
        reset_reserved: false,
    };
    if req.mode == "ini" {
        let cfg = parse_ini_file(req.ini_path.as_deref().ok_or("INI path required")?)?;
        if plan.family == "auto" {
            plan.family = cfg.family;
        }
        if req.target_baud.is_none() {
            plan.baud = cfg.baud;
        }
        plan.launch = cfg.launch;
        plan.set_entry = cfg.set_entry;
        plan.entry = cfg.entry_address;
        plan.reset_reserved = cfg.reset_reserved_flash;
        for item in cfg.items.into_iter().filter(|i| i.checked) {
            let path = Path::new(&item.resolved_path);
            if path
                .extension()
                .and_then(|s| s.to_str())
                .map_or(false, |s| s.eq_ignore_ascii_case("hex"))
            {
                return Err(
                    "INI filename must be raw BIN; use single HEX mode for addressed images".into(),
                );
            }
            plan.files
                .push((item.name, item.address, read_firmware(path)?));
        }
    } else if req.mode == "single" {
        let path = Path::new(
            req.single_file_path
                .as_deref()
                .ok_or("Firmware file required")?,
        );
        if path
            .extension()
            .and_then(|s| s.to_str())
            .map_or(false, |s| s.eq_ignore_ascii_case("hex"))
        {
            let image = crate::image::Image::load(path, "hex", 0)?;
            for segment in image.segments() {
                let start = segment["raw_start"].as_u64().unwrap() as u32;
                let end = segment["raw_end"].as_u64().unwrap();
                let bytes = image
                    .bytes
                    .range(start..)
                    .take_while(|(a, _)| (**a as u64) < end)
                    .map(|(_, v)| *v)
                    .collect();
                plan.files.push((format!("HEX_{start:08x}"), start, bytes));
            }
        } else {
            let address = parse_hex_or_dec(
                req.single_address
                    .as_deref()
                    .ok_or("BIN base address must be explicit")?,
            )?;
            plan.files.push((
                path.file_name()
                    .unwrap_or_default()
                    .to_string_lossy()
                    .into(),
                address,
                read_firmware(path)?,
            ));
        }
    } else {
        return Err("ING mode must be ini/single".into());
    }
    if !["auto", "ing916", "ing918", "ing20", "ing920"].contains(&plan.family.as_str()) {
        return Err("Unsupported ING family".into());
    }
    if plan.baud < 300 || plan.baud > 4000000 {
        return Err("Invalid ISP baud rate".into());
    }
    if plan.files.is_empty() || plan.files.iter().any(|(_, _, b)| b.is_empty()) {
        return Err("No selected nonempty firmware".into());
    }
    if plan.files.iter().map(|(_, _, b)| b.len()).sum::<usize>() > 64 * 1024 * 1024 {
        return Err("Total firmware exceeds 64 MiB".into());
    }
    if plan.set_entry && plan.entry.is_none() {
        return Err("INI set-entry requires a valid entry address".into());
    }
    let mut spans = vec![];
    for (_, address, bytes) in &plan.files {
        let start = *address as u64;
        let end = start + bytes.len() as u64;
        if end > u32::MAX as u64 + 1 {
            return Err("Firmware address overflow".into());
        }
        if *address < RAM_BASE_ADDR && start % 4096 != 0 {
            return Err(
                "Flash image base must be 4 KiB sector aligned to avoid erasing unrelated data"
                    .into(),
            );
        }
        let erased_end = if *address < RAM_BASE_ADDR {
            (end + 4095) & !4095
        } else {
            end
        };
        if spans.iter().any(|(a, b)| start < *b && *a < erased_end) {
            return Err("Firmware erase/program ranges overlap".into());
        }
        spans.push((start, erased_end));
    }
    Ok(plan)
}
fn read_firmware(path: &Path) -> Result<Vec<u8>, String> {
    let size = path.metadata().map_err(|e| e.to_string())?.len();
    if size == 0 || size > 64 * 1024 * 1024 {
        return Err("Firmware must contain 1..64 MiB bytes".into());
    }
    std::fs::read(path).map_err(|e| e.to_string())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IngFlashProgress {
    pub job_id: String,
    pub port_name: String,
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

    let content = String::from_utf8(content_bytes.clone())
        .unwrap_or_else(|_| content_bytes.iter().map(|&b| b as char).collect());

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
                sections
                    .entry(current_section.clone())
                    .or_default()
                    .insert(key, val);
            }
        }
    }

    if sections.is_empty() || !sections.contains_key("main") {
        let alt_candidate = parent_dir.join("flash_download.ini");
        let hint = if alt_candidate.exists() {
            format!(
                "，同目录下检测到可用的烧录配置: {}",
                alt_candidate.display()
            )
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
            let checked = sec
                .get("checked")
                .map(|s| s == "1" || s.eq_ignore_ascii_case("true"))
                .unwrap_or(false);
            let file_name = sec.get("filename").cloned().unwrap_or_default();
            let addr_str = sec
                .get("address")
                .cloned()
                .unwrap_or_else(|| "0".to_string());
            let address = parse_hex_or_dec(&addr_str).map_err(|e| format!("bin-{i}: {e}"))?;

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
        clean
            .parse::<u32>()
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
    cancelled: Arc<dyn Fn() -> bool + Send + Sync>,
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

        Ok(Self {
            port,
            cancelled: Arc::new(|| FLASH_CANCEL.load(Ordering::SeqCst)),
        })
    }

    pub fn set_timeout(&mut self, timeout: Duration) -> Result<(), String> {
        self.port.set_timeout(timeout).map_err(|e| e.to_string())
    }

    pub fn set_baud_rate(&mut self, baud: u32) -> Result<(), String> {
        self.port.set_baud_rate(baud).map_err(|e| e.to_string())
    }

    pub fn toggle_reset_for_boot(&mut self) -> Result<(), String> {
        self.port
            .write_request_to_send(true)
            .map_err(|e| e.to_string())?;
        self.port
            .write_data_terminal_ready(true)
            .map_err(|e| e.to_string())?;
        std::thread::sleep(Duration::from_millis(100));
        self.port
            .write_data_terminal_ready(false)
            .map_err(|e| e.to_string())?;
        self.port
            .write_request_to_send(false)
            .map_err(|e| e.to_string())?;
        Ok(())
    }

    pub fn write_all(&mut self, data: &[u8]) -> Result<(), String> {
        self.port
            .write_all(data)
            .map_err(|e| format!("串口写入失败: {}", e))?;
        self.port
            .flush()
            .map_err(|e| format!("串口刷新失败: {}", e))
    }

    pub fn read_exact(&mut self, len: usize) -> Result<Vec<u8>, String> {
        let mut buf = vec![0u8; len];
        self.port
            .read_exact(&mut buf)
            .map_err(|e| format!("串口读取响应超时或失败: {}", e))?;
        Ok(buf)
    }

    pub fn exec_cmd(&mut self, cmd: &[u8]) -> Result<Vec<u8>, String> {
        self.write_all(cmd)?;
        self.read_exact(ACK.len())
    }

    pub fn wait_hello_candidates(
        &mut self,
        candidates: &[(&str, &[u8])],
        timeout: Duration,
    ) -> Result<String, String> {
        // Fast non-blocking / low-timeout polling (15ms timeout)
        self.set_timeout(Duration::from_millis(15))?;
        let start = Instant::now();
        let mut acc = Vec::with_capacity(256);
        let mut buf = [0u8; 64];

        while start.elapsed() < timeout {
            if (self.cancelled)() {
                return Err("CANCELLED: ISP handshake stopped before erase/program".to_string());
            }

            match self.port.read(&mut buf) {
                Ok(n) if n > 0 => {
                    acc.extend_from_slice(&buf[..n]);
                    // Check against all candidate sequences in memory
                    for (family_name, target_hello) in candidates {
                        if acc.windows(target_hello.len()).any(|w| w == *target_hello) {
                            return Ok(family_name.to_string());
                        }
                    }
                    // Keep sliding window size reasonable (prevent unbounded growth)
                    if acc.len() > 1024 {
                        let drain_len = acc.len() - 256;
                        acc.drain(0..drain_len);
                    }
                }
                Ok(_) => {}
                Err(ref e) if e.kind() == std::io::ErrorKind::TimedOut => {}
                Err(e) => return Err(format!("握手读取出错: {}", e)),
            }

            std::thread::sleep(Duration::from_millis(2));
        }

        let cand_names: Vec<&str> = candidates.iter().map(|(c, _)| *c).collect();
        Err(format!("等待芯片握手信号超时 (未收到 {:?} Boot 握手响应)，请检查接线或重新上电/按复位键进入 BOOT", cand_names))
    }
}
impl crate::reset::ResetLines for FlasherSerial {
    fn dtr(&self, level: bool) -> Result<(), String> {
        self.port
            .try_clone()
            .map_err(|e| e.to_string())?
            .write_data_terminal_ready(level)
            .map_err(|e| e.to_string())
    }
    fn rts(&self, level: bool) -> Result<(), String> {
        self.port
            .try_clone()
            .map_err(|e| e.to_string())?
            .write_request_to_send(level)
            .map_err(|e| e.to_string())
    }
}

// ----------------------------------------------------------------------------
// Flasher Routines
// ----------------------------------------------------------------------------
pub fn run_flash_core<F>(req: &IngFlashRequest, emit_progress: &F) -> Result<(), String>
where
    F: Fn(&str, &str, usize, usize, f32, f32, &str),
{
    run_with_options(req, &FlashOptions::default(), emit_progress)
}

fn validate_boot_policy(req: &IngFlashRequest, options: &FlashOptions) -> Result<(), String> {
    if let Some(pins) = &options.pin_reset {
        pins.validate()?;
    }
    if req.manual_boot == Some(false) && options.pin_reset.is_none() {
        return Err("Automatic ISP reset requires an explicit board pin-reset profile; use manual boot when wiring is unknown".into());
    }
    Ok(())
}

pub fn run_with_options<F>(
    req: &IngFlashRequest,
    options: &FlashOptions,
    emit_progress: &F,
) -> Result<(), String>
where
    F: Fn(&str, &str, usize, usize, f32, f32, &str),
{
    validate_boot_policy(req, options)?;
    let prepared = prepare(req)?;
    if (options.cancelled)() {
        return Err("CANCELLED: before ISP connection".into());
    }
    let mut flasher = FlasherSerial::new(&req.port_name, 115200)?;
    flasher.cancelled = options.cancelled.clone();
    if let Some(pins) = &options.pin_reset {
        crate::reset::execute(
            &flasher,
            pins,
            true,
            Instant::now() + Duration::from_secs(req.timeout_sec.unwrap_or(15)),
            || (options.cancelled)(),
        )?;
    }
    run_prepared(&mut flasher, req, prepared, options, emit_progress)
}

pub trait IspTransport {
    fn write_all(&mut self, data: &[u8]) -> Result<(), String>;
    fn read_exact(&mut self, length: usize) -> Result<Vec<u8>, String>;
    fn set_baud_rate(&mut self, baud: u32) -> Result<(), String>;
    fn set_timeout(&mut self, timeout: Duration) -> Result<(), String>;
    fn hello(&mut self, candidates: &[(&str, &[u8])], timeout: Duration) -> Result<String, String>;
    fn reset_boot(&mut self) -> Result<(), String>;
    fn exec_cmd(&mut self, data: &[u8]) -> Result<Vec<u8>, String> {
        self.write_all(data)?;
        self.read_exact(ACK.len())
    }
}
impl IspTransport for FlasherSerial {
    fn write_all(&mut self, d: &[u8]) -> Result<(), String> {
        FlasherSerial::write_all(self, d)
    }
    fn read_exact(&mut self, n: usize) -> Result<Vec<u8>, String> {
        FlasherSerial::read_exact(self, n)
    }
    fn set_baud_rate(&mut self, b: u32) -> Result<(), String> {
        FlasherSerial::set_baud_rate(self, b)
    }
    fn set_timeout(&mut self, t: Duration) -> Result<(), String> {
        FlasherSerial::set_timeout(self, t)
    }
    fn hello(&mut self, c: &[(&str, &[u8])], t: Duration) -> Result<String, String> {
        self.wait_hello_candidates(c, t)
    }
    fn reset_boot(&mut self) -> Result<(), String> {
        self.toggle_reset_for_boot()
    }
}
fn expect_ack(port: &mut impl IspTransport, data: &[u8]) -> Result<(), String> {
    let response = port.exec_cmd(data)?;
    if response != ACK {
        return Err(format!("ISP command rejected: {response:?}"));
    }
    Ok(())
}
fn run_prepared<F>(
    flasher: &mut impl IspTransport,
    req: &IngFlashRequest,
    prepared: PreparedFlash,
    options: &FlashOptions,
    emit_progress: &F,
) -> Result<(), String>
where
    F: Fn(&str, &str, usize, usize, f32, f32, &str),
{
    let PreparedFlash {
        files: files_to_flash,
        family,
        baud: target_baud,
        launch,
        set_entry: should_set_entry,
        entry: entry_address,
        reset_reserved,
    } = prepared;
    let should_launch = launch && !options.suppress_launch;
    let check = || {
        if (options.cancelled)() {
            Err("CANCELLED: ISP stopped at acknowledged page/sector boundary".to_string())
        } else {
            Ok(())
        }
    };
    if (options.cancelled)() {
        return Err("CANCELLED: before ISP handshake".into());
    }
    validate_boot_policy(req, options)?;
    let wait_timeout_sec = req.timeout_sec.unwrap_or(15);
    let mut is_918 = family.contains("918");

    // Prepare candidate greetings
    let mut candidates: Vec<(&str, &[u8])> = Vec::new();
    if family == "auto" {
        candidates.push(("ing916", BOOT_HELLO_916));
        candidates.push(("ing920", BOOT_HELLO_920));
        candidates.push(("ing918", BOOT_HELLO_918));
    } else if is_918 {
        candidates.push(("ing918", BOOT_HELLO_918));
    } else {
        candidates.push(("ing916", BOOT_HELLO_916));
        candidates.push(("ing920", BOOT_HELLO_920));
    }

    let boot_message = if options.pin_reset.is_some() {
        format!(
            "已执行明确配置的复位时序，等待 ISP 握手（最长 {} 秒）...",
            wait_timeout_sec
        )
    } else {
        format!("【手动Boot模式】等待 ISP 握手（最长 {} 秒）；不会自动驱动 RTS/DTR，请按板级说明进入 Boot 模式...", wait_timeout_sec)
    };
    emit_progress("handshake", "", 0, 0, 0.0, 0.0, &boot_message);

    // A failed handshake is not permission to guess wiring or reset again.
    let detected_family = flasher.hello(&candidates, Duration::from_secs(wait_timeout_sec))?;

    if detected_family == "ing918" {
        is_918 = true;
    } else {
        is_918 = false;
    }

    emit_progress(
        "unlock",
        "",
        0,
        0,
        0.0,
        0.0,
        &format!(
            "芯片响应握手成功 (识别型号: {})！检查 Flash 加密与保护状态...",
            detected_family.to_uppercase()
        ),
    );

    // 握手识别完成，进入 Flash 擦除与写入阶段：配置 5000ms 充足超时（对齐 Downloader 标准），确保 20ms~400ms 的慢速 Flash 擦除顺利完成
    flasher.set_timeout(Duration::from_millis(5000))?;
    check()?;
    let lock = flasher.exec_cmd(CMD_QLOCKSTATE)?;
    check()?;
    if lock == STATUS_LOCKED {
        expect_ack(flasher, CMD_UNLOCK)?;
    } else if lock != STATUS_UNLOCKED && lock != ACK {
        return Err(format!("Unknown ISP lock response: {lock:?}"));
    }
    // ING916 QSPI Init
    if !is_918 {
        emit_progress(
            "init",
            "",
            0,
            0,
            0.0,
            0.0,
            "配置 ING916 QSPI 接口模式 (0x0200)...",
        );
        let mut set_qspi_cmd = Vec::new();
        set_qspi_cmd.extend_from_slice(CMD_FLASH_SET_916);
        set_qspi_cmd.extend_from_slice(&0x0200u16.to_le_bytes());
        check()?;
        expect_ack(flasher, &set_qspi_cmd)?;
    }

    // Baudrate negotiation
    if target_baud != 115200 {
        emit_progress(
            "baudrate",
            "",
            0,
            0,
            0.0,
            0.0,
            &format!("与芯片协商切换高速烧录波特率 -> {} bps...", target_baud),
        );
        let mut baud_cmd = Vec::new();
        baud_cmd.extend_from_slice(CMD_SET_BAUD);
        baud_cmd.extend_from_slice(&target_baud.to_le_bytes());
        check()?;
        expect_ack(flasher, &baud_cmd)?;
        flasher.set_baud_rate(target_baud)?;
    }

    // Reset reserved flash if requested (ING916)
    if !is_918 && reset_reserved {
        emit_progress("erase", "", 0, 0, 0.0, 0.0, "擦除保留扇区 0x02000000...");
        let mut erase_cmd = Vec::new();
        erase_cmd.extend_from_slice(ERASE_SECTOR_916);
        erase_cmd.extend_from_slice(&0x02000000u32.to_le_bytes());
        check()?;
        expect_ack(flasher, &erase_cmd)?;
    }

    // Compute total bytes across all files
    let grand_total_bytes: usize = files_to_flash.iter().map(|(_, _, d)| d.len()).sum();
    let mut total_burned_bytes = 0usize;
    let burn_start_time = Instant::now();

    for (file_idx, (name, addr, data)) in files_to_flash.iter().enumerate() {
        check()?;

        let file_total = data.len();
        let mut file_offset = 0usize;
        emit_progress(
            "burn",
            name,
            total_burned_bytes,
            grand_total_bytes,
            (total_burned_bytes as f32 / grand_total_bytes.max(1) as f32) * 100.0,
            0.0,
            &format!(
                "[{}/{}] 开始烧录固件: {} (目标地址: 0x{:08X}, 大小: {} 字节)",
                file_idx + 1,
                files_to_flash.len(),
                name,
                addr,
                file_total
            ),
        );

        if is_918 {
            // ING918 Page-based Burn (8KB per page)
            while file_offset < file_total {
                check()?;

                let seg_len = (file_total - file_offset).min(PAGE_SIZE_918);
                let current_addr = addr + file_offset as u32;
                let chunk = &data[file_offset..file_offset + seg_len];

                let cmd_prefix = if current_addr < RAM_BASE_ADDR {
                    SEND_PAGE_918
                } else {
                    SEND_RAM_918
                };
                let mut page_req = Vec::new();
                page_req.extend_from_slice(cmd_prefix);
                page_req.extend_from_slice(&current_addr.to_le_bytes());
                page_req.extend_from_slice(&(seg_len as u16).to_le_bytes());

                match flasher.exec_cmd(&page_req) {
                    Ok(rsp) if rsp == ACK => {}
                    other => {
                        return Err(format!(
                            "下发页地址失败: 0x{:08X}, 响应: {:?}",
                            current_addr, other
                        ));
                    }
                }

                flasher
                    .write_all(chunk)
                    .map_err(|e| format!("写入数据失败: {}", e))?;

                let crc = calc_crc_16(chunk);
                flasher
                    .write_all(&crc.to_le_bytes())
                    .map_err(|e| format!("写入 CRC 校验失败: {}", e))?;

                match flasher.read_exact(ACK.len()) {
                    Ok(rsp) if rsp == ACK => {}
                    other => {
                        return Err(format!(
                            "CRC 校验应答失败 (地址 0x{:08X}): {:?}",
                            current_addr, other
                        ));
                    }
                }

                file_offset += seg_len;
                total_burned_bytes += seg_len;

                let elapsed_sec = burn_start_time.elapsed().as_secs_f32().max(0.001);
                let speed_kbps = (total_burned_bytes as f32 / 1024.0) / elapsed_sec;
                let pct = (total_burned_bytes as f32 / grand_total_bytes.max(1) as f32) * 100.0;
                emit_progress(
                    "burn",
                    name,
                    total_burned_bytes,
                    grand_total_bytes,
                    pct,
                    speed_kbps,
                    &format!(
                        "正在传输: 0x{:08X} ({}/{} 字节)",
                        current_addr + seg_len as u32,
                        total_burned_bytes,
                        grand_total_bytes
                    ),
                );
            }
        } else {
            // ING916 Sector-erase (4KB) & Page-write (256B)
            let mut sector_offset = 0usize;
            while sector_offset < file_total {
                check()?;

                let current_sector_addr = addr + sector_offset as u32;
                if current_sector_addr < RAM_BASE_ADDR {
                    let mut erase_cmd = Vec::new();
                    erase_cmd.extend_from_slice(ERASE_SECTOR_916);
                    erase_cmd.extend_from_slice(&current_sector_addr.to_le_bytes());
                    match flasher.exec_cmd(&erase_cmd) {
                        Ok(rsp) if rsp == ACK => {}
                        other => {
                            return Err(format!(
                                "扇区擦除失败: 0x{:08X}, 响应: {:?}",
                                current_sector_addr, other
                            ));
                        }
                    }
                }

                let sector_bytes = (file_total - sector_offset).min(SECTOR_SIZE_916);
                let mut page_offset = 0usize;

                while page_offset < sector_bytes {
                    check()?;

                    let page_len = (sector_bytes - page_offset).min(PAGE_SIZE_916);
                    let page_addr = current_sector_addr + page_offset as u32;
                    let chunk =
                        &data[sector_offset + page_offset..sector_offset + page_offset + page_len];

                    let cmd_prefix = if page_addr < RAM_BASE_ADDR {
                        SEND_PAGE_916
                    } else {
                        SEND_RAM_DATA_916
                    };
                    let mut page_cmd = Vec::new();
                    page_cmd.extend_from_slice(cmd_prefix);
                    page_cmd.extend_from_slice(&page_addr.to_le_bytes());
                    page_cmd.push((page_len - 1) as u8);

                    match flasher.exec_cmd(&page_cmd) {
                        Ok(rsp) if rsp == ACK => {}
                        other => {
                            return Err(format!(
                                "写页指令失败: 0x{:08X}, 响应: {:?}",
                                page_addr, other
                            ));
                        }
                    }

                    flasher
                        .write_all(chunk)
                        .map_err(|e| format!("写入页面数据失败: {}", e))?;

                    let crc = calc_crc_16(chunk);
                    flasher
                        .write_all(&crc.to_le_bytes())
                        .map_err(|e| format!("写入 CRC 校验失败: {}", e))?;

                    match flasher.read_exact(ACK.len()) {
                        Ok(rsp) if rsp == ACK => {}
                        other => {
                            return Err(format!(
                                "CRC 页面校验应答失败 (地址 0x{:08X}): {:?}",
                                page_addr, other
                            ));
                        }
                    }

                    page_offset += page_len;
                    total_burned_bytes += page_len;

                    let elapsed_sec = burn_start_time.elapsed().as_secs_f32().max(0.001);
                    let speed_kbps = (total_burned_bytes as f32 / 1024.0) / elapsed_sec;
                    let pct = (total_burned_bytes as f32 / grand_total_bytes.max(1) as f32) * 100.0;
                    emit_progress(
                        "burn",
                        name,
                        total_burned_bytes,
                        grand_total_bytes,
                        pct,
                        speed_kbps,
                        &format!(
                            "已烧录: 0x{:08X} ({}/{} 字节)",
                            page_addr + page_len as u32,
                            total_burned_bytes,
                            grand_total_bytes
                        ),
                    );
                }

                sector_offset += sector_bytes;
            }
        }
    }

    check()?;
    // Set Entry point if needed
    if should_set_entry {
        if let Some(entry) = entry_address {
            emit_progress(
                "launch",
                "",
                grand_total_bytes,
                grand_total_bytes,
                100.0,
                0.0,
                &format!("设置入口执行地址: 0x{:08X}...", entry),
            );
            if is_918 {
                let mut entry_cmd = Vec::new();
                entry_cmd.extend_from_slice(SET_ENTRY_918);
                entry_cmd.extend_from_slice(&entry.to_le_bytes());
                expect_ack(flasher, &entry_cmd)?;
            }
        }
    }

    check()?;
    // Launch application
    if should_launch {
        emit_progress(
            "launch",
            "",
            grand_total_bytes,
            grand_total_bytes,
            100.0,
            0.0,
            "发送启动跳转指令，目标开始运行！",
        );
        if is_918 {
            flasher.write_all(CMD_LAUNCH_918)?;
        } else {
            flasher.write_all(CMD_LAUNCH_916)?;
        }
    }

    let elapsed_sec = burn_start_time.elapsed().as_secs_f32();
    emit_progress(
        "success",
        "",
        grand_total_bytes,
        grand_total_bytes,
        100.0,
        (grand_total_bytes as f32 / 1024.0) / elapsed_sec.max(0.001),
        &format!(
            "全部烧录成功！共写入 {} 字节，耗时 {:.2} 秒",
            grand_total_bytes, elapsed_sec
        ),
    );

    // Explicitly drop flasher before returning to immediately close the COM port handle

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    struct FakeIsp {
        writes: Vec<Vec<u8>>,
        cancel: Arc<AtomicBool>,
        stop_at: Option<&'static [u8]>,
        nack: bool,
        hello_fails: bool,
    }
    impl IspTransport for FakeIsp {
        fn write_all(&mut self, d: &[u8]) -> Result<(), String> {
            self.writes.push(d.into());
            if self.stop_at.map_or(false, |p| d.starts_with(p)) {
                self.cancel.store(true, Ordering::SeqCst);
            }
            Ok(())
        }
        fn read_exact(&mut self, _: usize) -> Result<Vec<u8>, String> {
            Ok(if self.nack {
                b"ERROR".to_vec()
            } else {
                ACK.to_vec()
            })
        }
        fn set_baud_rate(&mut self, _: u32) -> Result<(), String> {
            Ok(())
        }
        fn set_timeout(&mut self, _: Duration) -> Result<(), String> {
            Ok(())
        }
        fn hello(&mut self, _: &[(&str, &[u8])], _: Duration) -> Result<String, String> {
            if self.hello_fails {
                return Err("ISP handshake timed out".into());
            }
            Ok("ing916".into())
        }
        fn reset_boot(&mut self) -> Result<(), String> {
            panic!("HIL must not infer reset wiring")
        }
    }
    fn prepared() -> PreparedFlash {
        PreparedFlash {
            files: vec![("app".into(), 0x02004000, vec![0xA5; 8192])],
            family: "ing916".into(),
            baud: 115200,
            launch: true,
            set_entry: false,
            entry: None,
            reset_reserved: false,
        }
    }
    #[test]
    fn unknown_wiring_never_triggers_reset_even_on_handshake_failure() {
        let mut req = hil_request(&serde_json::json!({"manual_boot": false}), "test");
        assert_eq!(req.manual_boot, Some(true));
        let options = FlashOptions::default();
        let mut io = FakeIsp {
            writes: vec![],
            cancel: Arc::new(AtomicBool::new(false)),
            stop_at: None,
            nack: false,
            hello_fails: true,
        };
        for manual in [Some(true), None] {
            req.manual_boot = manual;
            let error = run_prepared(
                &mut io,
                &req,
                prepared(),
                &options,
                &|_, _, _, _, _, _, _| {},
            )
            .unwrap_err();
            assert!(error.contains("handshake timed out"));
            assert!(io.writes.is_empty());
        }
        req.manual_boot = Some(false);
        let error = run_prepared(
            &mut io,
            &req,
            prepared(),
            &options,
            &|_, _, _, _, _, _, _| {},
        )
        .unwrap_err();
        assert!(error.contains("explicit board pin-reset profile"));
        assert!(io.writes.is_empty());
        // Entry-point validation precedes file loading and opening a serial port.
        assert!(run_with_options(&req, &options, &|_, _, _, _, _, _, _| {})
            .unwrap_err()
            .contains("explicit board pin-reset profile"));
    }

    #[test]
    fn automatic_reset_requires_a_verified_profile_before_opening_port() {
        let mut req = hil_request(&serde_json::json!({}), "test");
        req.manual_boot = Some(false);
        let mut options = FlashOptions::default();
        options.pin_reset = Some(crate::reset::PinReset {
            profile_id: "test-fixture".into(),
            wiring_verified: false,
            reset_asserted_dtr: true,
            boot_asserted_rts: false,
            settle_ms: 0,
            pulse_ms: 100,
            boot_hold_ms: 0,
        });
        assert!(run_with_options(&req, &options, &|_, _, _, _, _, _, _| {})
            .unwrap_err()
            .contains("verified board wiring"));
        options.pin_reset.as_mut().unwrap().wiring_verified = true;
        assert!(validate_boot_policy(&req, &options).is_ok());
    }

    #[test]
    fn cancel_during_page_finishes_payload_ack_without_next_write_or_launch() {
        for command in [ERASE_SECTOR_916, SEND_PAGE_916] {
            let cancel = Arc::new(AtomicBool::new(false));
            let token = cancel.clone();
            let mut io = FakeIsp {
                writes: vec![],
                cancel,
                stop_at: Some(command),
                nack: false,
                hello_fails: false,
            };
            let options = FlashOptions {
                cancelled: Arc::new(move || token.load(Ordering::SeqCst)),
                pin_reset: None,
                suppress_launch: true,
            };
            let req = hil_request(&serde_json::json!({}), "test");
            let err = run_prepared(
                &mut io,
                &req,
                prepared(),
                &options,
                &|_, _, _, _, _, _, _| {},
            )
            .unwrap_err();
            assert!(err.contains("acknowledged page/sector boundary"));
            assert_eq!(
                io.writes
                    .iter()
                    .filter(|w| w.starts_with(ERASE_SECTOR_916))
                    .count(),
                1
            );
            let pages = io
                .writes
                .iter()
                .filter(|w| w.starts_with(SEND_PAGE_916))
                .count();
            assert_eq!(pages, if command == SEND_PAGE_916 { 1 } else { 0 });
            if pages == 1 {
                assert!(io.writes.iter().any(|w| w.len() == 256));
            }
            assert!(!io.writes.iter().any(|w| w.as_slice() == CMD_LAUNCH_916));
        }
    }
    #[test]
    fn completed_hil_download_stays_in_isp_and_nack_is_error() {
        let mut io = FakeIsp {
            writes: vec![],
            cancel: Arc::new(AtomicBool::new(false)),
            stop_at: None,
            nack: false,
            hello_fails: false,
        };
        let options = FlashOptions {
            cancelled: Arc::new(|| false),
            pin_reset: None,
            suppress_launch: true,
        };
        let req = hil_request(&serde_json::json!({}), "test");
        run_prepared(
            &mut io,
            &req,
            prepared(),
            &options,
            &|_, _, _, _, _, _, _| {},
        )
        .unwrap();
        assert_eq!(
            io.writes
                .iter()
                .filter(|w| w.starts_with(SEND_PAGE_916))
                .count(),
            32
        );
        assert!(!io.writes.iter().any(|w| w.as_slice() == CMD_LAUNCH_916));
        io.nack = true;
        assert!(run_prepared(
            &mut io,
            &req,
            prepared(),
            &options,
            &|_, _, _, _, _, _, _| {}
        )
        .is_err());
    }
}
