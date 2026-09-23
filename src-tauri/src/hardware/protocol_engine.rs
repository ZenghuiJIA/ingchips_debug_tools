use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChannelDef {
    pub name: String,
    pub offset: usize,
    #[serde(rename = "type")]
    pub data_type: String, // "float32", "float64", "int16", "uint16", "int32", "uint32", "int8", "uint8"
    #[serde(default = "default_scale")]
    pub scale: f64,
    #[serde(default = "default_bias")]
    pub bias: f64,
}

fn default_scale() -> f64 {
    1.0
}

fn default_bias() -> f64 {
    0.0
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChecksumConfig {
    #[serde(rename = "type")]
    pub check_type: String, // "none", "sum8", "xor8"
    pub offset: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FrameConfig {
    pub header: Option<Vec<u8>>,
    pub tail: Option<Vec<u8>>,
    pub fixed_length: Option<usize>,
    pub checksum: Option<ChecksumConfig>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ProtocolConfig {
    pub name: String,
    pub description: Option<String>,
    #[serde(rename = "type")]
    pub protocol_type: String, // "binary", "firewater", "justfloat", "raw"
    #[serde(default = "default_endian")]
    pub endian: String, // "little" or "big"
    pub frame: Option<FrameConfig>,
    #[serde(default)]
    pub channels: Vec<ChannelDef>,
}

fn default_endian() -> String {
    "little".to_string()
}

pub struct ProtocolEngine {
    config: ProtocolConfig,
    buffer: Vec<u8>,
}

impl ProtocolEngine {
    pub fn new(config: ProtocolConfig) -> Self {
        Self {
            config,
            buffer: Vec::with_capacity(8192),
        }
    }

    pub fn update_config(&mut self, config: ProtocolConfig) {
        self.config = config;
        self.buffer.clear();
    }

    pub fn get_config(&self) -> &ProtocolConfig {
        &self.config
    }

    /// Parse incoming chunk of raw bytes, returning extracted points
    pub fn parse_chunk(&mut self, raw: &[u8]) -> Vec<HashMap<String, f64>> {
        let mut results = Vec::new();

        match self.config.protocol_type.as_str() {
            "justfloat" => {
                // JustFloat: N * float32 (little endian) + 4-byte tail [0x00, 0x00, 0x80, 0x7F]
                self.buffer.extend_from_slice(raw);
                while self.buffer.len() >= 8 {
                    // Search for tail 0x00 0x00 0x80 0x7F
                    let mut found_tail = None;
                    for i in 0..=(self.buffer.len() - 4) {
                        if self.buffer[i] == 0x00
                            && self.buffer[i + 1] == 0x00
                            && self.buffer[i + 2] == 0x80
                            && self.buffer[i + 3] == 0x7F
                        {
                            found_tail = Some(i);
                            break;
                        }
                    }

                    if let Some(tail_idx) = found_tail {
                        if tail_idx >= 4 && (tail_idx % 4 == 0) {
                            let float_count = tail_idx / 4;
                            let mut point = HashMap::new();
                            for c in 0..float_count {
                                let start = c * 4;
                                let f_bytes: [u8; 4] = [
                                    self.buffer[start],
                                    self.buffer[start + 1],
                                    self.buffer[start + 2],
                                    self.buffer[start + 3],
                                ];
                                let val = f32::from_le_bytes(f_bytes) as f64;
                                if !val.is_nan() && val.is_finite() {
                                    let ch_name = if c < self.config.channels.len() {
                                        self.config.channels[c].name.clone()
                                    } else {
                                        format!("CH{}", c)
                                    };
                                    point.insert(ch_name, val);
                                }
                            }
                            if !point.is_empty() {
                                results.push(point);
                            }
                        }
                        // Discard up to end of tail
                        self.buffer.drain(0..(tail_idx + 4));
                    } else {
                        // Keep buffer bounded
                        if self.buffer.len() > 4096 {
                            let excess = self.buffer.len() - 512;
                            self.buffer.drain(0..excess);
                        }
                        break;
                    }
                }
            }
            "firewater" => {
                // Firewater ASCII CSV or Key-Value separated by \n
                self.buffer.extend_from_slice(raw);
                while let Some(newline_pos) = self.buffer.iter().position(|&b| b == b'\n') {
                    let line_bytes = self.buffer.drain(0..=newline_pos).collect::<Vec<u8>>();
                    if let Ok(line_str) = std::str::from_utf8(&line_bytes) {
                        let trimmed = line_str.trim();
                        if !trimmed.is_empty() {
                            if let Some(point) = parse_telemetry_line_rust(trimmed) {
                                results.push(point);
                            }
                        }
                    }
                }
            }
            "binary" => {
                // Custom Binary Protocol defined by JSON frame & channels
                self.buffer.extend_from_slice(raw);
                if let Some(frame) = &self.config.frame {
                    let fixed_len = frame.fixed_length.unwrap_or(0);
                    let is_little = self.config.endian.to_lowercase() != "big";

                    while !self.buffer.is_empty() {
                        // 1. Align to header if specified
                        if let Some(header) = &frame.header {
                            if !header.is_empty() {
                                if let Some(hdr_pos) = self
                                    .buffer
                                    .windows(header.len())
                                    .position(|w| w == header.as_slice())
                                {
                                    if hdr_pos > 0 {
                                        self.buffer.drain(0..hdr_pos);
                                    }
                                } else {
                                    // Header not found in buffer, clear except last possible prefix
                                    let keep = header.len().saturating_sub(1);
                                    if self.buffer.len() > keep {
                                        let discard = self.buffer.len() - keep;
                                        self.buffer.drain(0..discard);
                                    }
                                    break;
                                }
                            }
                        }

                        // Determine frame size
                        let frame_size = if fixed_len > 0 {
                            fixed_len
                        } else if let Some(tail) = &frame.tail {
                            if let Some(tail_pos) = self
                                .buffer
                                .windows(tail.len())
                                .position(|w| w == tail.as_slice())
                            {
                                tail_pos + tail.len()
                            } else {
                                break; // Need more data for tail
                            }
                        } else {
                            // Default frame size based on max channel offset
                            let max_offset = self
                                .config
                                .channels
                                .iter()
                                .map(|c| c.offset + get_type_size(&c.data_type))
                                .max()
                                .unwrap_or(4);
                            max_offset
                        };

                        if self.buffer.len() < frame_size {
                            break; // Wait for full frame
                        }

                        // Extract frame slice
                        let frame_bytes: Vec<u8> = self.buffer.drain(0..frame_size).collect();

                        // 2. Validate Checksum if configured
                        let checksum_valid = if let Some(chk) = &frame.checksum {
                            validate_checksum(&frame_bytes, chk)
                        } else {
                            true
                        };

                        if checksum_valid {
                            let mut point = HashMap::new();
                            for ch in &self.config.channels {
                                if let Some(val) = extract_channel_value(&frame_bytes, ch, is_little) {
                                    point.insert(ch.name.clone(), val);
                                }
                            }
                            if !point.is_empty() {
                                results.push(point);
                            }
                        }
                    }
                }
            }
            _ => {
                // Fallback to auto-detect text line
                self.buffer.extend_from_slice(raw);
                while let Some(newline_pos) = self.buffer.iter().position(|&b| b == b'\n') {
                    let line_bytes = self.buffer.drain(0..=newline_pos).collect::<Vec<u8>>();
                    if let Ok(line_str) = std::str::from_utf8(&line_bytes) {
                        let trimmed = line_str.trim();
                        if !trimmed.is_empty() {
                            if let Some(point) = parse_telemetry_line_rust(trimmed) {
                                results.push(point);
                            }
                        }
                    }
                }
            }
        }

        results
    }
}

fn get_type_size(dt: &str) -> usize {
    match dt.to_lowercase().as_str() {
        "float32" | "int32" | "uint32" => 4,
        "float64" => 8,
        "int16" | "uint16" => 2,
        "int8" | "uint8" => 1,
        _ => 4,
    }
}

fn extract_channel_value(bytes: &[u8], ch: &ChannelDef, is_little: bool) -> Option<f64> {
    let offset = ch.offset;
    let size = get_type_size(&ch.data_type);
    if offset + size > bytes.len() {
        return None;
    }

    let slice = &bytes[offset..offset + size];
    let raw_val: f64 = match ch.data_type.to_lowercase().as_str() {
        "float32" => {
            let arr: [u8; 4] = slice.try_into().ok()?;
            (if is_little {
                f32::from_le_bytes(arr)
            } else {
                f32::from_be_bytes(arr)
            }) as f64
        }
        "float64" => {
            let arr: [u8; 8] = slice.try_into().ok()?;
            if is_little {
                f64::from_le_bytes(arr)
            } else {
                f64::from_be_bytes(arr)
            }
        }
        "int32" => {
            let arr: [u8; 4] = slice.try_into().ok()?;
            (if is_little {
                i32::from_le_bytes(arr)
            } else {
                i32::from_be_bytes(arr)
            }) as f64
        }
        "uint32" => {
            let arr: [u8; 4] = slice.try_into().ok()?;
            (if is_little {
                u32::from_le_bytes(arr)
            } else {
                u32::from_be_bytes(arr)
            }) as f64
        }
        "int16" => {
            let arr: [u8; 2] = slice.try_into().ok()?;
            (if is_little {
                i16::from_le_bytes(arr)
            } else {
                i16::from_be_bytes(arr)
            }) as f64
        }
        "uint16" => {
            let arr: [u8; 2] = slice.try_into().ok()?;
            (if is_little {
                u16::from_le_bytes(arr)
            } else {
                u16::from_be_bytes(arr)
            }) as f64
        }
        "int8" => slice[0] as i8 as f64,
        "uint8" => slice[0] as f64,
        _ => 0.0,
    };

    if raw_val.is_nan() || !raw_val.is_finite() {
        return None;
    }

    Some(raw_val * ch.scale + ch.bias)
}

fn validate_checksum(bytes: &[u8], chk: &ChecksumConfig) -> bool {
    if chk.offset >= bytes.len() {
        return false;
    }
    match chk.check_type.to_lowercase().as_str() {
        "sum8" => {
            let expected = bytes[chk.offset];
            let mut sum: u8 = 0;
            for (idx, &b) in bytes.iter().enumerate() {
                if idx != chk.offset {
                    sum = sum.wrapping_add(b);
                }
            }
            sum == expected
        }
        "xor8" => {
            let expected = bytes[chk.offset];
            let mut xor_val: u8 = 0;
            for (idx, &b) in bytes.iter().enumerate() {
                if idx != chk.offset {
                    xor_val ^= b;
                }
            }
            xor_val == expected
        }
        "modbus_crc16" | "modbus" => {
            if chk.offset + 1 >= bytes.len() {
                return false;
            }
            let data_slice = &bytes[..chk.offset];
            let computed = crate::hardware::checksum::crc16_modbus(data_slice);
            let expected_low = (computed & 0xFF) as u8;
            let expected_high = ((computed >> 8) & 0xFF) as u8;
            bytes[chk.offset] == expected_low && bytes[chk.offset + 1] == expected_high
        }
        "crc16_ccitt" | "ccitt" => {
            if chk.offset + 1 >= bytes.len() {
                return false;
            }
            let data_slice = &bytes[..chk.offset];
            let computed = crate::hardware::checksum::crc16_ccitt(data_slice);
            let expected_high = ((computed >> 8) & 0xFF) as u8;
            let expected_low = (computed & 0xFF) as u8;
            bytes[chk.offset] == expected_high && bytes[chk.offset + 1] == expected_low
        }
        _ => true,
    }
}

/// Fallback text parser for CSV & Key-Value lines
fn parse_telemetry_line_rust(line: &str) -> Option<HashMap<String, f64>> {
    let mut map = HashMap::new();

    // 1. Try Key-Value: "ch0:12.3, ch1:45.6" or "temp=25.4"
    if line.contains(':') || line.contains('=') {
        let delimiter = if line.contains(',') {
            ','
        } else if line.contains(';') {
            ';'
        } else {
            ' '
        };

        let parts = line.split(delimiter);
        let mut count = 0;
        for part in parts {
            let p = part.trim();
            if p.is_empty() {
                continue;
            }
            let kv_sep = if p.contains(':') {
                ':'
            } else if p.contains('=') {
                '='
            } else {
                continue;
            };

            let mut split = p.splitn(2, kv_sep);
            if let (Some(k), Some(v)) = (split.next(), split.next()) {
                let key = k.trim().to_string();
                if let Ok(num) = v.trim().parse::<f64>() {
                    if !num.is_nan() && num.is_finite() {
                        map.insert(key, num);
                        count += 1;
                    }
                }
            }
        }
        if count > 0 {
            return Some(map);
        }
    }

    // 2. Try Delimited numbers: "12.3, 45.6, -7.8"
    let delimiter = if line.contains(',') {
        ','
    } else if line.contains('\t') {
        '\t'
    } else {
        ' '
    };

    let tokens = line.split(delimiter);
    let mut idx = 0;
    for token in tokens {
        let tok = token.trim();
        if tok.is_empty() {
            continue;
        }
        if let Ok(num) = tok.parse::<f64>() {
            if !num.is_nan() && num.is_finite() {
                map.insert(format!("CH{}", idx), num);
                idx += 1;
            }
        }
    }

    if !map.is_empty() {
        Some(map)
    } else {
        None
    }
}
