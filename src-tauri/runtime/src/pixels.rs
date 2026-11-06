use base64::Engine;
use serde_json::{json, Value};
pub fn render(args: &Value) -> Result<Value, String> {
    let width = crate::config::integer(&args["width"], "width", 1, 4096)? as usize;
    let height = crate::config::integer(&args["height"], "height", 1, 4096)? as usize;
    let format = args["pixel_format"].as_str().unwrap_or("rgb565");
    let data =
        hil_debug_core::capture::unhex(args["data"].as_str().ok_or("HEX pixel data required")?)?;
    let needed = match format {
        "rgb565" => width * height * 2,
        "rgb888" => width * height * 3,
        "argb8888" => width * height * 4,
        "mono" | "1bit" => (width * height + 7) / 8,
        _ => return Err("Unsupported pixel format".into()),
    };
    if needed > 16 * 1024 * 1024 || data.len() != needed {
        return Err("Incomplete/oversize framebuffer".into());
    }
    let row = (width * 3 + 3) & !3;
    let size = 54 + row * height;
    let mut bmp = vec![0u8; size];
    bmp[..2].copy_from_slice(b"BM");
    bmp[2..6].copy_from_slice(&(size as u32).to_le_bytes());
    bmp[10..14].copy_from_slice(&54u32.to_le_bytes());
    bmp[14..18].copy_from_slice(&40u32.to_le_bytes());
    bmp[18..22].copy_from_slice(&(width as i32).to_le_bytes());
    bmp[22..26].copy_from_slice(&(-(height as i32)).to_le_bytes());
    bmp[26..28].copy_from_slice(&1u16.to_le_bytes());
    bmp[28..30].copy_from_slice(&24u16.to_le_bytes());
    for y in 0..height {
        for x in 0..width {
            let i = y * width + x;
            let (b, g, r) = match format {
                "rgb565" => {
                    let v = u16::from_le_bytes([data[i * 2], data[i * 2 + 1]]);
                    (
                        ((v & 31) * 255 / 31) as u8,
                        (((v >> 5) & 63) * 255 / 63) as u8,
                        (((v >> 11) & 31) * 255 / 31) as u8,
                    )
                }
                "rgb888" => (data[i * 3 + 2], data[i * 3 + 1], data[i * 3]),
                "argb8888" => (data[i * 4], data[i * 4 + 1], data[i * 4 + 2]),
                _ => {
                    let value = if data[i / 8] & (1 << (7 - i % 8)) != 0 {
                        255
                    } else {
                        0
                    };
                    (value, value, value)
                }
            };
            let at = 54 + y * row + x * 3;
            bmp[at..at + 3].copy_from_slice(&[b, g, r]);
        }
    }
    Ok(
        json!({"status":"success","address":args["address"],"width":width,"height":height,"format":format,"byte_count":data.len(),"image_base64":format!("data:image/bmp;base64,{}",base64::engine::general_purpose::STANDARD.encode(bmp))}),
    )
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rgb565_golden_and_short_read() {
        let result =
            render(&json!({"width":1,"height":1,"pixel_format":"rgb565","data":"00f8"})).unwrap();
        let encoded = result["image_base64"]
            .as_str()
            .unwrap()
            .split_once(',')
            .unwrap()
            .1;
        let bytes = base64::engine::general_purpose::STANDARD
            .decode(encoded)
            .unwrap();
        assert_eq!(&bytes[54..57], &[0, 0, 255]);
        assert!(render(&json!({"width":1,"height":1,"data":"00"})).is_err());
    }
}
