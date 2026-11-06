use crate::config::integer;
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::path::Path;
pub struct Image {
    pub bytes: BTreeMap<u32, u8>,
    start: Option<(u8, Vec<u8>)>,
}
impl Image {
    pub fn load(path: &Path, kind: &str, offset: u64) -> Result<Self, String> {
        let data = std::fs::read(path).map_err(|e| e.to_string())?;
        if data.len() > 64 * 1024 * 1024 {
            return Err("Image file exceeds 64 MiB".into());
        }
        let mut image = Self {
            bytes: BTreeMap::new(),
            start: None,
        };
        if kind == "bin" {
            if offset + data.len() as u64 > u32::MAX as u64 + 1 {
                return Err("Image address overflow".into());
            }
            for (i, b) in data.into_iter().enumerate() {
                image.bytes.insert((offset + i as u64) as u32, b);
            }
            return Ok(image);
        }
        if kind != "hex" {
            return Err("Image type must be hex/bin".into());
        }
        let text = std::str::from_utf8(&data).map_err(|e| e.to_string())?;
        let mut base = 0u64;
        let mut eof = false;
        for (line_no, line) in text.lines().enumerate() {
            let line = line.trim();
            if line.is_empty() {
                continue;
            }
            if eof {
                return Err("HEX data after EOF".into());
            }
            let raw = hil_debug_core::capture::unhex(
                line.strip_prefix(':')
                    .ok_or("HEX line must start with colon")?,
            )?;
            if raw.len() < 5
                || raw.len() != raw[0] as usize + 5
                || raw.iter().fold(0u8, |n, b| n.wrapping_add(*b)) != 0
            {
                return Err(format!("HEX length/checksum error at line {}", line_no + 1));
            }
            let address = u16::from_be_bytes([raw[1], raw[2]]) as u64;
            let payload = &raw[4..raw.len() - 1];
            match raw[3] {
                0 => {
                    for (i, b) in payload.iter().enumerate() {
                        let address = base + address + i as u64 + offset;
                        if address > u32::MAX as u64 {
                            return Err("HEX address overflow".into());
                        }
                        if image.bytes.insert(address as u32, *b).is_some() {
                            return Err("HEX overlapping records".into());
                        }
                    }
                }
                1 if payload.is_empty() && address == 0 => eof = true,
                2 | 4 if payload.len() == 2 && address == 0 => {
                    let value = u16::from_be_bytes([payload[0], payload[1]]) as u64;
                    base = value << if raw[3] == 2 { 4 } else { 16 };
                }
                3 | 5 if payload.len() == 4 && address == 0 => {
                    if image.start.is_some() {
                        return Err("Duplicate HEX start record".into());
                    }
                    if offset != 0 {
                        return Err(
                            "Rebasing HEX entry records requires explicit entry-point mapping"
                                .into(),
                        );
                    }
                    image.start = Some((raw[3], payload.into()));
                }
                _ => return Err("Invalid/unsupported HEX record".into()),
            }
        }
        if !eof {
            return Err("HEX EOF record missing".into());
        }
        Ok(image)
    }
    pub fn segments(&self) -> Vec<Value> {
        let mut result = vec![];
        let mut start = None;
        let mut end = 0u64;
        for address in self.bytes.keys() {
            let address = *address as u64;
            if start.is_some() && address != end {
                let s = start.take().unwrap();
                result.push(json!({"start":format!("0x{s:08X}"),"end":format!("0x{end:08X}"),"raw_start":s,"raw_end":end,"size":end-s}));
            }
            if start.is_none() {
                start = Some(address);
            }
            end = address + 1;
        }
        if let Some(s) = start {
            result.push(json!({"start":format!("0x{s:08X}"),"end":format!("0x{end:08X}"),"raw_start":s,"raw_end":end,"size":end-s}));
        }
        result
    }
    fn hex_record(kind: u8, address: u16, data: &[u8]) -> String {
        let mut record = vec![data.len() as u8, (address >> 8) as u8, address as u8, kind];
        record.extend(data);
        let sum = record.iter().fold(0u8, |a, b| a.wrapping_add(*b));
        record.push(0u8.wrapping_sub(sum));
        format!(
            ":{}\n",
            hil_debug_core::capture::hex(&record).to_uppercase()
        )
    }
    pub fn save(&self, path: &Path, kind: &str, pad: u8) -> Result<(), String> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let temp = path.with_extension("hil-tmp");
        if kind == "bin" {
            let min = self.bytes.keys().next().copied().unwrap_or(0);
            let max = self.bytes.keys().next_back().copied().unwrap_or(0);
            let size = if self.bytes.is_empty() {
                0
            } else {
                max as u64 - min as u64 + 1
            };
            if size > 64 * 1024 * 1024 {
                return Err("Sparse BIN span exceeds 64 MiB".into());
            }
            let mut data = vec![pad; size as usize];
            for (a, b) in &self.bytes {
                data[(*a - min) as usize] = *b;
            }
            std::fs::write(&temp, data).map_err(|e| e.to_string())?;
        } else if kind == "hex" {
            let mut output = String::new();
            let mut upper = None;
            let entries: Vec<_> = self.bytes.iter().collect();
            let mut i = 0;
            while i < entries.len() {
                let address = *entries[i].0;
                let high = (address >> 16) as u16;
                if upper != Some(high) {
                    output.push_str(&Self::hex_record(4, 0, &high.to_be_bytes()));
                    upper = Some(high);
                }
                let mut data = vec![*entries[i].1];
                i += 1;
                while i < entries.len()
                    && data.len() < 16
                    && *entries[i].0 as u64 == address as u64 + data.len() as u64
                    && (*entries[i].0 >> 16) == high as u32
                {
                    data.push(*entries[i].1);
                    i += 1;
                }
                output.push_str(&Self::hex_record(0, address as u16, &data));
            }
            if let Some((kind, data)) = &self.start {
                output.push_str(&Self::hex_record(*kind, 0, data));
            }
            output.push_str(":00000001FF\n");
            std::fs::write(&temp, output).map_err(|e| e.to_string())?;
        } else {
            return Err("Output format must be bin/hex".into());
        }
        std::fs::rename(temp, path).map_err(|e| e.to_string())
    }
}
fn kind(path: &str) -> &str {
    if path.to_lowercase().ends_with(".hex") {
        "hex"
    } else {
        "bin"
    }
}
pub fn dispatch(method: &str, args: &Value) -> Result<Value, String> {
    if method == "read_memory_image" {
        let path = args["file_path"].as_str().ok_or("file_path required")?;
        let count = integer(&args["count"], "count", 1, 1024 * 1024)?;
        let address = integer(&args["address"], "address", 0, u32::MAX as u64)?;
        if address + count > u32::MAX as u64 + 1 {
            return Err("Address range overflow".into());
        }
        let image = Image::load(Path::new(path), kind(path), 0)?;
        if kind(path) == "bin" {
            return Ok(json!(image
                .bytes
                .values()
                .take(count as usize)
                .collect::<Vec<_>>()));
        }
        if !image
            .bytes
            .range(address as u32..=(address + count - 1) as u32)
            .next()
            .is_some()
        {
            return Err("HEX file has no data in selected address range".into());
        }
        return Ok(json!((address..address + count)
            .map(|a| image.bytes.get(&(a as u32)).copied().unwrap_or(255))
            .collect::<Vec<_>>()));
    }
    if method == "inspect_firmware_file" {
        let path = args["file_path"].as_str().ok_or("file_path required")?;
        let kind = args["file_type"]
            .as_str()
            .filter(|s| !s.is_empty())
            .unwrap_or(kind(path));
        let offset = integer(
            args.get("offset").unwrap_or(&json!(0)),
            "offset",
            0,
            u32::MAX as u64,
        )?;
        let image = Image::load(Path::new(path), kind, offset)?;
        let min = image.bytes.keys().next().copied().unwrap_or(offset as u32);
        let max = image.bytes.keys().next_back().copied().unwrap_or(min);
        return Ok(
            json!({"file_path":path,"file_name":Path::new(path).file_name().unwrap().to_string_lossy(),"type":kind,"file_size":std::fs::metadata(path).map_err(|e|e.to_string())?.len(),"data_size":image.bytes.len(),"min_addr":format!("0x{min:08X}"),"max_addr":format!("0x{max:08X}"),"raw_min_addr":min,"raw_max_addr":max,"segments":image.segments()}),
        );
    }
    let files = args["files"]
        .as_array()
        .filter(|f| !f.is_empty() && f.len() <= 100)
        .ok_or("1..100 input files required")?;
    let mode = args["overlap_strategy"].as_str().unwrap_or("error");
    if !["error", "ignore", "replace"].contains(&mode) {
        return Err("Invalid overlap strategy".into());
    }
    let path = args["output_path"].as_str().ok_or("output_path required")?;
    let format = args["output_format"]
        .as_str()
        .unwrap_or(if method == "merge_hex_files" {
            "hex"
        } else {
            "bin"
        });
    let pad = integer(
        args.get("pad_byte").unwrap_or(&json!(255)),
        "pad_byte",
        0,
        255,
    )? as u8;
    let mut merged = Image {
        bytes: BTreeMap::new(),
        start: None,
    };
    let mut inputs = vec![];
    for input in files {
        let file = input["file_path"]
            .as_str()
            .ok_or("input file_path required")?;
        let offset = integer(
            input
                .get("offset")
                .filter(|v| !v.is_null() && **v != "")
                .unwrap_or(&json!(0)),
            "offset",
            0,
            u32::MAX as u64,
        )?;
        let image = Image::load(
            Path::new(file),
            if method == "merge_hex_files" {
                "hex"
            } else {
                "bin"
            },
            offset,
        )?;
        if merged.bytes.len() + image.bytes.len() > 64 * 1024 * 1024 {
            return Err("Merged image exceeds 64 MiB".into());
        }
        inputs.push(json!({"file_path":file,"file_name":Path::new(file).file_name().unwrap().to_string_lossy(),"size":image.bytes.len(),"min_addr":format!("0x{:08X}",image.bytes.keys().next().copied().unwrap_or(0)),"max_addr":format!("0x{:08X}",image.bytes.keys().next_back().copied().unwrap_or(0))}));
        for (a, b) in image.bytes {
            if merged.bytes.contains_key(&a) {
                match mode {
                    "error" => return Err(format!("Image overlap at {a:#x}")),
                    "ignore" => continue,
                    _ => {}
                }
            }
            merged.bytes.insert(a, b);
        }
        if image.start.is_some() {
            if merged.start.is_some() && mode == "error" {
                return Err("Multiple HEX entry records".into());
            }
            if merged.start.is_none() || mode == "replace" {
                merged.start = image.start;
            }
        }
    }
    merged.save(Path::new(path), format, pad)?;
    Ok(
        json!({"status":"success","output_path":path,"output_format":format,"file_size":std::fs::metadata(path).map_err(|e|e.to_string())?.len(),"data_bytes":merged.bytes.len(),"min_addr":format!("0x{:08X}",merged.bytes.keys().next().copied().unwrap_or(0)),"max_addr":format!("0x{:08X}",merged.bytes.keys().next_back().copied().unwrap_or(0)),"segments":merged.segments(),"merged_count":files.len(),"inputs":inputs}),
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn hex_checksum_and_sparse_roundtrip() {
        let root = std::env::temp_dir().join(format!("hil-image-{}", std::process::id()));
        std::fs::create_dir_all(&root).unwrap();
        let image = Image {
            bytes: BTreeMap::from([(0x02004000, 1), (0x02004002, 3)]),
            start: None,
        };
        image.save(&root.join("app.hex"), "hex", 255).unwrap();
        let loaded = Image::load(&root.join("app.hex"), "hex", 0).unwrap();
        assert_eq!(loaded.bytes, image.bytes);
        assert_eq!(
            dispatch(
                "read_memory_image",
                &json!({"file_path":root.join("app.hex"),"address":"0x02004000","count":3})
            )
            .unwrap(),
            json!([1, 255, 3])
        );
        std::fs::write(root.join("bad.hex"), ":0100000001FF\n:00000001FF\n").unwrap();
        assert!(Image::load(&root.join("bad.hex"), "hex", 0).is_err());
        std::fs::remove_dir_all(root).unwrap();
    }
}
