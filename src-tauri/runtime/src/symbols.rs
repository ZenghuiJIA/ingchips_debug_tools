use object::{Object, ObjectSection, ObjectSymbol, SymbolKind};
use serde_json::{json, Value};
use std::path::Path;
pub fn dispatch(method: &str, args: &Value) -> Result<Value, String> {
    let path = args["file_path"]
        .as_str()
        .or(args["elf_path"].as_str())
        .or(args["axf_path"].as_str())
        .ok_or("ELF file path required")?;
    use std::io::Read;
    const MAX_ELF_BYTES: u64 = 128 * 1024 * 1024;
    let file = std::fs::File::open(path).map_err(|e| e.to_string())?;
    if file.metadata().map_err(|e| e.to_string())?.len() > MAX_ELF_BYTES {
        return Err("ELF exceeds 128 MiB".into());
    }
    let mut bytes = Vec::new();
    file.take(MAX_ELF_BYTES + 1).read_to_end(&mut bytes).map_err(|e| e.to_string())?;
    if bytes.len() as u64 > MAX_ELF_BYTES { return Err("ELF exceeds 128 MiB".into()); }
    let elf = object::File::parse(&*bytes).map_err(|e| e.to_string())?;
    if elf.format() != object::BinaryFormat::Elf { return Err("Expected an ELF/AXF file".into()); }
    // Address resolution is independent of display filters and result limits.
    // Undefined symbols have address zero but do not identify target memory.
    if method == "resolve_symbol" {
        let wanted = args["symbol"].as_str().filter(|s| !s.is_empty()).ok_or("symbol required")?;
        let found: Vec<_> = elf.symbols()
            .filter(|s| !s.is_undefined() && s.name().ok() == Some(wanted)).collect();
        if found.len() != 1 { return Err("Symbol must resolve uniquely to a defined address".into()); }
        let address = found[0].address();
        if address > u32::MAX as u64 { return Err("Symbol address exceeds 32 bits".into()); }
        return Ok(json!({"address": address}));
    }
    let filter = args["filter_keyword"].as_str().unwrap_or("").to_lowercase();
    let maximum = args["max_results"]
        .as_u64()
        .unwrap_or(if method == "parse_firmware_functions" {
            500
        } else {
            200
        })
        .min(10000) as usize;
    let mut symbols = vec![];
    for symbol in elf.symbols() {
        let name = symbol.name().unwrap_or("");
        if name.is_empty()
            || name.starts_with('$')
            || name.starts_with('.')
            || !name.to_lowercase().contains(&filter)
        {
            continue;
        }
        let address = symbol.address();
        let size = symbol.size();
        symbols.push((
            name.to_string(),
            address,
            size,
            symbol.kind(),
            symbol.is_global(),
        ));
    }
    if method == "detect_rtos_kernel" {
        let signatures = [
            (
                "FreeRTOS",
                vec![
                    "pxReadyTasksLists",
                    "pxCurrentTCB",
                    "uxCurrentNumberOfTasks",
                    "xSchedulerRunning",
                ],
            ),
            (
                "RTX5",
                vec!["osRtxInfo", "osRtxConfig", "os_idle_thread_cb"],
            ),
            (
                "ThreadX",
                vec![
                    "_tx_thread_created_ptr",
                    "_tx_thread_current_ptr",
                    "_tx_timer_system_clock",
                ],
            ),
            (
                "uCOS-II",
                vec!["OSTCBTbl", "OSTCBCur", "OSCPUUsage", "OSTaskCtr"],
            ),
            (
                "uCOS-III",
                vec!["OSTaskDbgListPtr", "OSTCBCurPtr", "OSCfg_ISRStk"],
            ),
            (
                "RT-Thread",
                vec![
                    "rt_thread_priority_table",
                    "rt_current_thread",
                    "rt_object_container",
                ],
            ),
        ];
        let mut scores = serde_json::Map::new();
        let mut best = None;
        let mut count = 0;
        for (name, list) in &signatures {
            let score = list
                .iter()
                .filter(|n| symbols.iter().any(|s| &s.0 == *n))
                .count();
            scores.insert((*name).into(), json!(score));
            if score > count {
                count = score;
                best = Some((*name, list));
            }
        }
        if let Some((name, list)) = best {
            let matched: serde_json::Map<_, _> = symbols
                .iter()
                .filter(|s| list.contains(&s.0.as_str()))
                .map(|s| (s.0.clone(), json!(format!("0x{:08X}", s.1))))
                .collect();
            return Ok(
                json!({"detected":true,"rtos_type":name,"confidence":format!("{count}/{}",list.len()),"matched_symbols":matched,"all_rtos_scores":scores}),
            );
        }
        return Ok(
            json!({"detected":false,"rtos_type":"Bare Metal / Custom OS","matched_symbols":{},"all_rtos_scores":scores}),
        );
    }
    if method == "elf_sections" {
        return Ok(
            json!({"file_path":path,"architecture":format!("{:?}",elf.architecture()),"entry":elf.entry(),"sections":elf.sections().map(|s|json!({"name":s.name().unwrap_or(""),"address":s.address(),"size":s.size(),"kind":format!("{:?}",s.kind())})).collect::<Vec<_>>()}),
        );
    }
    let functions = method == "parse_firmware_functions";
    let mut result = vec![];
    for (name, address, size, kind, global) in symbols {
        if functions {
            if kind != SymbolKind::Text || size == 0 {
                continue;
            }
        } else {
            if size == 0
                || !matches!(kind, SymbolKind::Data | SymbolKind::Unknown)
                || !((0x20000000..0x20100000).contains(&address)
                    || (0x10000000..0x10100000).contains(&address)
                    || (0x30000000..0x30100000).contains(&address))
            {
                continue;
            }
        }
        let address = if functions { address & !1 } else { address };
        let low = name.to_lowercase();
        let suggested = match size {
            1 => "uint8",
            2 => "uint16",
            4 => {
                if ["flt", "float", "speed", "temp", "cur", "vol", "angle"]
                    .iter()
                    .any(|word| low.contains(word))
                {
                    "float32"
                } else {
                    "int32"
                }
            }
            8 => "float64",
            _ => "uint32",
        };
        let mut row = json!({"name":name,"address":format!("0x{address:08X}"),"raw_address":address,"size":size,"type":suggested,"bind":if global{"STB_GLOBAL"}else{"STB_LOCAL"}});
        if functions {
            row["category"] = json!(
                if ["isr", "handler", "irq"].iter().any(|w| low.contains(w)) {
                    "ISR"
                } else if ["ble", "hci", "ll_", "gap", "gatt"]
                    .iter()
                    .any(|w| low.contains(w))
                {
                    "BLE Stack"
                } else if ["os", "task", "xqueue", "vtask", "rt_"]
                    .iter()
                    .any(|w| low.contains(w))
                {
                    "RTOS"
                } else if ["driver", "hal_", "uart", "spi", "i2c", "dma"]
                    .iter()
                    .any(|w| low.contains(w))
                {
                    "Driver/HAL"
                } else if ["aes", "sha", "ecc", "crypto"]
                    .iter()
                    .any(|w| low.contains(w))
                {
                    "Security"
                } else {
                    "App Code"
                }
            );
            row["end_address"] = json!(address + size);
            row["raw_end"] = json!(address + size);
        }
        result.push(row);
        if result.len() >= maximum {
            break;
        }
    }
    result.sort_by_key(|v| v["raw_address"].as_u64().unwrap());
    if functions {
        Ok(
            json!({"file_path":path,"file_name":Path::new(path).file_name().unwrap().to_string_lossy(),"count":result.len(),"functions":result}),
        )
    } else {
        Ok(json!({"file_path":path,"count":result.len(),"symbols":result}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn put16(bytes: &mut [u8], offset: usize, value: u16) { bytes[offset..offset + 2].copy_from_slice(&value.to_le_bytes()); }
    fn put32(bytes: &mut [u8], offset: usize, value: u32) { bytes[offset..offset + 4].copy_from_slice(&value.to_le_bytes()); }
    // Minimal ELF32 with a real string table and symbol table, no Python dependency.
    fn elf(symbols: &[(u32, u16)]) -> Vec<u8> {
        let sym_offset = 64;
        let sym_size = (symbols.len() + 1) * 16;
        let sections = sym_offset + sym_size;
        let mut bytes = vec![0u8; sections + 3 * 40];
        bytes[..7].copy_from_slice(b"\x7fELF\x01\x01\x01");
        put16(&mut bytes, 16, 2); put16(&mut bytes, 18, 40); put32(&mut bytes, 20, 1);
        put32(&mut bytes, 32, sections as u32); put16(&mut bytes, 40, 52);
        put16(&mut bytes, 46, 40); put16(&mut bytes, 48, 3); put16(&mut bytes, 50, 1);
        bytes[52..59].copy_from_slice(b"\0value\0");
        for (i, (address, section)) in symbols.iter().enumerate() {
            let at = sym_offset + (i + 1) * 16;
            put32(&mut bytes, at, 1); put32(&mut bytes, at + 4, *address);
            put32(&mut bytes, at + 8, 4); bytes[at + 12] = 0x11; put16(&mut bytes, at + 14, *section);
        }
        let strings = sections + 40;
        put32(&mut bytes, strings + 4, 3); put32(&mut bytes, strings + 16, 52); put32(&mut bytes, strings + 20, 7);
        let table = sections + 80;
        put32(&mut bytes, table + 4, 2); put32(&mut bytes, table + 16, sym_offset as u32);
        put32(&mut bytes, table + 20, sym_size as u32); put32(&mut bytes, table + 24, 1);
        put32(&mut bytes, table + 28, 1); put32(&mut bytes, table + 32, 4); put32(&mut bytes, table + 36, 16);
        bytes
    }
    #[test]
    fn native_resolution_requires_unique_defined_elf_symbol() {
        let path = std::env::temp_dir().join(format!("hil-symbols-{}.axf", std::process::id()));
        let args = json!({"axf_path":path,"symbol":"value","filter_keyword":"ignored","max_results":0});
        std::fs::write(&path, elf(&[(0x20000010, 0xfff1)])).unwrap();
        assert_eq!(dispatch("resolve_symbol", &args).unwrap()["address"], 0x20000010u32);
        std::fs::write(&path, elf(&[(0, 0)])).unwrap();
        assert!(dispatch("resolve_symbol", &args).unwrap_err().contains("defined"));
        std::fs::write(&path, elf(&[(0x20000010, 0xfff1), (0x20000020, 0xfff1)])).unwrap();
        assert!(dispatch("resolve_symbol", &args).unwrap_err().contains("uniquely"));
        std::fs::write(&path, b"not an ELF").unwrap();
        assert!(dispatch("resolve_symbol", &args).is_err());
        std::fs::remove_file(path).unwrap();
    }
}
