//! Shared streaming codec. No device access and no UI dependencies.
use serde::{Deserialize, Serialize};
use serde_json::{Value, Map};
use crate::capture::{hex, unhex};

fn max_frame() -> usize { 65536 }
fn endian() -> String { "little".into() }
fn one() -> f64 { 1. }
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct LengthField { pub offset: usize, pub size: usize, #[serde(default)] pub adjustment: i64 }
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Bits { pub offset: u8, pub width: u8 }
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Field {
    pub name: String, pub offset: usize, #[serde(rename="type")] pub kind: String,
    #[serde(default)] pub size: Option<usize>, #[serde(default)] pub endian: Option<String>,
    #[serde(default="one")] pub scale: f64, #[serde(default)] pub bias: f64,
    #[serde(default)] pub bits: Option<Bits>, #[serde(default)] pub labels: std::collections::BTreeMap<String,String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Checksum {
    pub algorithm: String, pub offset: i64, #[serde(default)] pub start: usize,
    #[serde(default)] pub end: Option<i64>, #[serde(default="endian")] pub endian: String,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Protocol {
    pub schema_version: u8, pub name: String,
    #[serde(default)] pub header: Vec<u8>, #[serde(default)] pub tail: Vec<u8>,
    #[serde(default)] pub fixed_length: Option<usize>, #[serde(default)] pub length_field: Option<LengthField>,
    #[serde(default="max_frame")] pub max_frame: usize, #[serde(default="endian")] pub endian: String,
    #[serde(default)] pub checksum: Option<Checksum>, pub fields: Vec<Field>,
    #[serde(default)] pub partial_timeout_ms: Option<u64>,
}
#[derive(Clone, Debug, Serialize)]
pub struct Frame {
    pub offset: u64, pub data: String, pub valid: bool, pub fields: Map<String,Value>,
    pub labels: Map<String,Value>, pub error: Option<String>,
}
fn width(field: &Field) -> Result<usize,String> {
    Ok(match field.kind.as_str() { "uint8"|"int8"|"bool" => 1, "uint16"|"int16" => 2,
        "uint32"|"int32"|"float32" => 4, "float64" => 8,
        "bytes"|"string" => field.size.ok_or("bytes/string field requires size")?,
        _ => return Err(format!("Unknown field type: {}",field.kind)), })
}
fn position(value: i64, size: usize) -> Result<usize,String> {
    let n = if value < 0 { size as i64 + value } else { value };
    if n < 0 || n as usize > size { return Err("Position outside frame".into()); } Ok(n as usize)
}
fn check_width(algorithm: &str) -> Result<usize,String> {
    match algorithm { "sum8"|"xor8" => Ok(1), "crc16_modbus"|"crc16_ccitt" => Ok(2), _ => Err(format!("Unknown checksum: {algorithm}")) }
}
fn checksum_value(algorithm: &str, data: &[u8]) -> u64 {
    match algorithm { "sum8" => data.iter().fold(0u8, |a,b|a.wrapping_add(*b)) as u64,
        "xor8" => data.iter().fold(0u8, |a,b|a^b) as u64,
        "crc16_modbus" => crate::checksum::crc16_modbus(data) as u64,
        "crc16_ccitt" => crate::checksum::crc16_ccitt(data) as u64, _ => unreachable!() }
}
fn unsigned(bytes: &[u8], little: bool) -> u64 {
    if little { bytes.iter().enumerate().fold(0,|v,(i,b)|v | ((*b as u64) << (i*8))) }
    else { bytes.iter().fold(0,|v,b|(v<<8)|(*b as u64)) }
}
fn write_unsigned(bytes: &mut [u8], value: u64, little: bool) {
    let size = bytes.len(); for (i,b) in bytes.iter_mut().enumerate() { *b = (value >> (8 * if little { i } else { size-1-i })) as u8; }
}
impl Protocol {
    pub fn validate(&self) -> Result<(),String> {
        if self.schema_version != 1 || self.name.is_empty() || self.max_frame == 0 || self.max_frame > 65536 { return Err("Invalid protocol version/name/maximum frame".into()); }
        if !["little","big"].contains(&self.endian.as_str()) { return Err("Invalid endian".into()); }
        if self.header.len() > self.max_frame || self.tail.len() > self.max_frame { return Err("Header/tail too long".into()); }
        if self.fixed_length.is_some() && self.length_field.is_some() { return Err("Choose fixed_length or length_field".into()); }
        if self.fixed_length.is_none() && self.length_field.is_none() && self.tail.is_empty() { return Err("Frame boundary is required".into()); }
        if let Some(size) = self.fixed_length { if size == 0 || size > self.max_frame || size < self.header.len()+self.tail.len() { return Err("Invalid fixed frame length".into()); } }
        if let Some(l) = &self.length_field {
            if ![1,2,4].contains(&l.size) || l.offset.checked_add(l.size).map_or(true, |end|end > self.max_frame) || l.offset < self.header.len() { return Err("Invalid length field".into()); }
        }
        if self.fields.len() > 256 { return Err("Too many fields".into()); }
        let mut names = std::collections::HashSet::new();
        for f in &self.fields {
            let size = width(f)?;
            if f.name.is_empty() || !names.insert(&f.name) || size == 0 || f.offset < self.header.len() || f.offset.checked_add(size).map_or(true,|end|end > self.fixed_length.unwrap_or(self.max_frame)) { return Err(format!("Invalid field bounds/name: {}",f.name)); }
            if !f.scale.is_finite() || f.scale == 0. || !f.bias.is_finite() || !["little","big"].contains(&f.endian.as_deref().unwrap_or(&self.endian)) { return Err("Invalid scale/bias/endian".into()); }
            if let Some(bits) = &f.bits {
                if !f.kind.starts_with("uint") || bits.width == 0 || bits.offset as usize + bits.width as usize > size*8 { return Err("Invalid bit field".into()); }
            }
        }
        for (i,a) in self.fields.iter().enumerate() {
            for b in self.fields.iter().skip(i+1) {
                if a.offset < b.offset+width(b)? && b.offset < a.offset+width(a)? {
                    let disjoint=match (&a.bits,&b.bits){(Some(x),Some(y))=>a.offset==b.offset && width(a)?==width(b)? && a.endian.as_deref().unwrap_or(&self.endian)==b.endian.as_deref().unwrap_or(&self.endian) && (x.offset as usize+x.width as usize<=y.offset as usize || y.offset as usize+y.width as usize<=x.offset as usize),_=>false};
                    if !disjoint{return Err("Overlapping data fields".into());}
                }
            }
            if let Some(l)=&self.length_field {if a.offset<l.offset+l.size && l.offset<a.offset+width(a)? {return Err("Length field overlaps a value field".into());}}
        }
        if let Some(c) = &self.checksum { check_width(&c.algorithm)?; if !["little","big"].contains(&c.endian.as_str()) { return Err("Invalid checksum endian".into()); } }
        if let Some(size)=self.fixed_length {
            if let Some(c)=&self.checksum {
                let at=position(c.offset,size)?;let n=check_width(&c.algorithm)?;
                if at < self.header.len() || at+n>size-self.tail.len(){return Err("Checksum overlaps frame delimiter".into());}
                self.checksum(&vec![0;size])?;
                for f in &self.fields {if f.offset<at+n && at<f.offset+width(f)?{return Err("Checksum overlaps value field".into());}}
            }
            for f in &self.fields {if f.offset+width(f)?>size-self.tail.len(){return Err("Value field overlaps tail".into());}}
        }
        if self.partial_timeout_ms == Some(0) { return Err("Partial timeout must be positive".into()); }
        Ok(())
    }
    fn checksum(&self, bytes: &[u8]) -> Result<Option<(usize,usize,u64)>,String> {
        if let Some(c) = &self.checksum {
            let at = position(c.offset,bytes.len())?; let size = check_width(&c.algorithm)?;
            let end = position(c.end.unwrap_or(c.offset),bytes.len())?;
            if at+size > bytes.len() || c.start > end || end > bytes.len() || (c.start < at+size && end > at) { return Err("Invalid checksum range (must exclude checksum bytes)".into()); }
            Ok(Some((at,size,checksum_value(&c.algorithm,&bytes[c.start..end]))))
        } else { Ok(None) }
    }
    pub fn decode(&self, bytes: &[u8], offset: u64) -> Frame {
        let mut frame = Frame { offset, data: hex(bytes), valid: false, fields: Map::new(), labels: Map::new(), error: None };
        let result = (|| -> Result<(),String> {
            if self.fixed_length.map_or(false,|size|size!=bytes.len()) || bytes.len()>self.max_frame {return Err("Frame length mismatch".into());}
            if !bytes.starts_with(&self.header) || !bytes.ends_with(&self.tail) { return Err("Header/tail mismatch".into()); }
            if let Some((at,size,want)) = self.checksum(bytes)? {
                let got = unsigned(&bytes[at..at+size],self.checksum.as_ref().unwrap().endian == "little");
                if got != want { return Err(format!("Checksum mismatch: expected {want:#x}, got {got:#x}")); }
            }
            for f in &self.fields {
                let size = width(f)?;
                if f.offset + size > bytes.len() { return Err(format!("Missing field: {}",f.name)); }
                let b = &bytes[f.offset..f.offset+size]; let little = f.endian.as_deref().unwrap_or(&self.endian) == "little";
                let value = match f.kind.as_str() {
                    "bytes" => Value::String(hex(b)),
                    "string" => Value::String(std::str::from_utf8(b).map_err(|_|"Invalid UTF-8 field")?.trim_end_matches('\0').into()),
                    _ => {
                        let raw = unsigned(b,little);
                        if f.kind=="bool" && raw>1{return Err("Boolean field must be 0 or 1".into());}
                        let raw = if let Some(bits) = &f.bits { (raw >> bits.offset) & ((1u64 << bits.width)-1) } else { raw };
                        let n = match f.kind.as_str() {
                            "int8" => raw as i8 as f64, "int16" => raw as i16 as f64, "int32" => raw as i32 as f64,
                            "float32" => f32::from_bits(raw as u32) as f64, "float64" => f64::from_bits(raw), _ => raw as f64 };
                        let scaled = n*f.scale+f.bias;
                        if !scaled.is_finite() { return Err(format!("Nonfinite field: {}",f.name)); }
                        if let Some(label) = f.labels.get(&format!("{}",n)) { frame.labels.insert(f.name.clone(),Value::String(label.clone())); }
                        serde_json::json!(scaled)
                    }
                };
                frame.fields.insert(f.name.clone(),value);
            }
            Ok(())
        })();
        frame.valid = result.is_ok(); frame.error = result.err(); frame
    }
    pub fn encode(&self, values: &Map<String,Value>) -> Result<Vec<u8>,String> {
        self.validate()?;
        if values.keys().any(|key|!self.fields.iter().any(|f|&f.name==key)) { return Err("Unknown value field".into()); }
        let minimum = self.fields.iter().map(|f|f.offset+width(f).unwrap_or(0)).max().unwrap_or(self.header.len());
        let minimum=minimum.max(self.length_field.as_ref().map_or(0,|l|l.offset+l.size));
        let mut size = self.fixed_length.unwrap_or(minimum + self.tail.len());
        if self.fixed_length.is_none() { if let Some(c) = &self.checksum { size = if c.offset >= 0 { size.max(c.offset as usize+check_width(&c.algorithm)?+self.tail.len()) } else { size + check_width(&c.algorithm)? }; } }
        if size > self.max_frame || size < self.header.len()+self.tail.len() { return Err("Encoded frame exceeds bounds".into()); }
        let mut bytes = vec![0;size]; bytes[..self.header.len()].copy_from_slice(&self.header);
        bytes[size-self.tail.len()..].copy_from_slice(&self.tail);
        for f in &self.fields {
            let value = values.get(&f.name).ok_or_else(||format!("Missing value: {}",f.name))?;
            let size = width(f)?; let little = f.endian.as_deref().unwrap_or(&self.endian)=="little";
            let output = &mut bytes[f.offset..f.offset+size];
            if f.kind == "bytes" || f.kind == "string" {
                let text = value.as_str().ok_or("Expected string/HEX field")?;
                let data = if f.kind == "bytes" { unhex(text)? } else { text.as_bytes().to_vec() };
                if data.len() != size { return Err(format!("{} requires exactly {size} bytes",f.name)); } output.copy_from_slice(&data); continue;
            }
            let n = (value.as_f64().ok_or("Expected numeric field")?-f.bias)/f.scale;
            if !n.is_finite() { return Err("Nonfinite numeric value".into()); }
            let bits = if f.kind == "float32" { let v=n as f32; if !v.is_finite(){return Err("float32 overflow".into());} v.to_bits() as u64 }
                else if f.kind == "float64" { n.to_bits() }
                else {
                    let bit_count = f.bits.as_ref().map_or(size*8,|b|b.width as usize);
                    let signed = f.kind.starts_with("int");
                    let low = if signed { -(2f64.powi(bit_count as i32-1)) } else { 0. };
                    let high = if f.kind=="bool" {1.} else {2f64.powi(bit_count as i32-if signed {1}else{0})-1.};
                    if n.fract()!=0. || n < low || n > high { return Err(format!("Field {} out of range",f.name)); }
                    if signed { n as i64 as u64 } else { n as u64 }
                };
            if let Some(b) = &f.bits {
                let mask = ((1u64<<b.width)-1)<<b.offset;
                let old = unsigned(output,little); write_unsigned(output,(old&!mask)|((bits<<b.offset)&mask),little);
            } else { write_unsigned(output,bits,little); }
        }
        if let Some(l) = &self.length_field {
            let value = bytes.len() as i64-l.adjustment;
            if value<0 || value as u64 >= (1u64 << (8*l.size)) || l.offset+l.size > bytes.len() {return Err("Length field overflow".into());}
            write_unsigned(&mut bytes[l.offset..l.offset+l.size],value as u64,self.endian=="little");
        }
        if let Some((at,size,want))=self.checksum(&bytes)? {
            if at<self.header.len() || at+size>bytes.len()-self.tail.len() || self.fields.iter().any(|f|f.offset<at+size && at<f.offset+width(f).unwrap_or(0)){return Err("Checksum overlaps data/delimiter".into());}
            write_unsigned(&mut bytes[at..at+size],want,self.checksum.as_ref().unwrap().endian=="little");
        }
        if !bytes.starts_with(&self.header) || !bytes.ends_with(&self.tail) {return Err("Fields overlap header/tail".into());}
        Ok(bytes)
    }
}
pub struct Decoder { pub protocol: Protocol, buffer: Vec<u8>, offset:u64, partial_at:Option<f64> }
impl Decoder {
    pub fn new(protocol:Protocol)->Result<Self,String>{protocol.validate()?; Ok(Self{protocol,buffer:Vec::new(),offset:0,partial_at:None})}
    fn invalid(&self,size:usize,error:&str)->Frame{Frame{offset:self.offset,data:hex(&self.buffer[..size]),valid:false,fields:Map::new(),labels:Map::new(),error:Some(error.into())}}
    fn consume(&mut self,size:usize){self.buffer.drain(..size);self.offset+=size as u64;}
    pub fn feed(&mut self,data:&[u8],now:f64)->Result<Vec<Frame>,String>{
        let initial_offset=self.offset;
        if !now.is_finite() || now<0. || data.len()>1024*1024 {return Err("Invalid timestamp/chunk size".into());}
        let mut result=Vec::new();
        if let (Some(start),Some(timeout))=(self.partial_at,self.protocol.partial_timeout_ms){
            if now-start>=timeout as f64 && !self.buffer.is_empty(){result.push(self.invalid(self.buffer.len(),"Partial frame timeout"));self.consume(self.buffer.len());}
        }
        self.buffer.extend_from_slice(data);
        while !self.buffer.is_empty(){
            let header=&self.protocol.header;
            if !header.is_empty() && !self.buffer.starts_with(header){
                let pos=self.buffer.windows(header.len()).position(|w|w==header).unwrap_or(self.buffer.len().saturating_sub(header.len()-1));
                if pos==0{break;} result.push(self.invalid(pos,"Bytes before frame header"));self.consume(pos);continue;
            }
            let size=if let Some(size)=self.protocol.fixed_length {size}
                else if let Some(l)=&self.protocol.length_field {
                    if self.buffer.len()<l.offset+l.size{break;}
                    let total=unsigned(&self.buffer[l.offset..l.offset+l.size],self.protocol.endian=="little") as i64+l.adjustment;
                    if total<=0 || total as usize>self.protocol.max_frame || (total as usize)<l.offset+l.size {result.push(self.invalid(1,"Invalid length field"));self.consume(1);continue;} total as usize
                } else {match self.buffer.windows(self.protocol.tail.len()).position(|w|w==self.protocol.tail.as_slice()) {Some(pos)=>pos+self.protocol.tail.len(),None=>{if self.buffer.len()>self.protocol.max_frame{result.push(self.invalid(self.protocol.max_frame,"Frame exceeds maximum"));self.consume(self.protocol.max_frame);continue;}break;}}};
            if self.buffer.len()<size{break;}
            let frame=self.protocol.decode(&self.buffer[..size],self.offset);
            let consumed=if !frame.valid && !self.protocol.header.is_empty(){1}else{size};
            result.push(frame);self.consume(consumed);
            if result.len()>10000{return Err("Too many frames in one chunk".into());}
        }
        if self.buffer.len()>self.protocol.max_frame{result.push(self.invalid(self.buffer.len(),"Frame buffer overrun"));self.consume(self.buffer.len());}
        self.partial_at=if self.buffer.is_empty(){None}else{Some(if self.offset!=initial_offset{now}else{self.partial_at.unwrap_or(now)})};
        Ok(result)
    }
}

#[cfg(test)] mod tests {
    use super::*;
    fn spec()->Protocol{serde_json::from_value(serde_json::json!({"schema_version":1,"name":"test","header":[170,85],"fixed_length":7,"endian":"little","checksum":{"algorithm":"sum8","offset":6},"fields":[{"name":"seq","offset":2,"type":"uint8"},{"name":"value","offset":3,"type":"int16"},{"name":"status","offset":5,"type":"uint8"}]})).unwrap()}
    #[test] fn golden_bytes_and_all_split_positions(){let p=spec();let values=serde_json::json!({"seq":1,"value":-2,"status":0});let bytes=p.encode(values.as_object().unwrap()).unwrap();assert_eq!(bytes,vec![170,85,1,254,255,0,253]);for at in 0..=bytes.len(){let mut d=Decoder::new(p.clone()).unwrap();let mut f=d.feed(&bytes[..at],0.).unwrap();f.extend(d.feed(&bytes[at..],1.).unwrap());assert_eq!(f.len(),1);assert!(f[0].valid);assert_eq!(f[0].fields["value"],-2.);}}
    #[test] fn noise_bad_crc_then_good_recovers(){let p=spec();let good=p.encode(serde_json::json!({"seq":1,"value":-2,"status":0}).as_object().unwrap()).unwrap();let mut data=vec![1,2,3];let mut bad=good.clone();bad[6]=0;data.extend(bad);data.extend(&good);data.extend(&good);let result=Decoder::new(p).unwrap().feed(&data,0.).unwrap();assert_eq!(result.iter().filter(|x|x.valid).count(),2);assert!(result.iter().any(|x|x.error.as_deref().unwrap_or("").contains("Checksum")));}
    #[test] fn rejects_unknown_and_overflow(){let mut p=spec();p.checksum.as_mut().unwrap().algorithm="typo".into();assert!(p.validate().is_err());p=spec();assert!(p.encode(serde_json::json!({"seq":256,"value":0,"status":0}).as_object().unwrap()).is_err());p.fields[0].kind="nope".into();assert!(p.validate().is_err());}
    #[test] fn partial_timeout_and_sessions_are_independent(){let p=spec();let mut a=Decoder::new(p.clone()).unwrap();let mut b=Decoder::new(p.clone()).unwrap();let bytes=p.encode(serde_json::json!({"seq":1,"value":0,"status":0}).as_object().unwrap()).unwrap();a.feed(&bytes[..3],0.).unwrap();assert_eq!(b.feed(&bytes,0.).unwrap().len(),1);assert_eq!(a.feed(&bytes[3..],1.).unwrap().len(),1);a.protocol.partial_timeout_ms=Some(10);a.feed(&bytes[..2],2.).unwrap();assert!(!a.feed(&[],20.).unwrap()[0].valid);}
    #[test] fn length_big_endian_bits_and_overlap_validation(){
        let p:Protocol=serde_json::from_value(serde_json::json!({"schema_version":1,"name":"variable","header":[170],"length_field":{"offset":1,"size":1,"adjustment":0},"tail":[13,10],"endian":"big","fields":[{"name":"word","offset":2,"type":"uint16"},{"name":"a","offset":4,"type":"uint8","bits":{"offset":0,"width":2}},{"name":"b","offset":4,"type":"uint8","bits":{"offset":2,"width":2}}]})).unwrap();
        let bytes=p.encode(serde_json::json!({"word":4660,"a":2,"b":3}).as_object().unwrap()).unwrap();
        assert_eq!(bytes,vec![170,7,18,52,14,13,10]);
        let frames=Decoder::new(p.clone()).unwrap().feed(&bytes,0.).unwrap();assert_eq!(frames[0].fields["word"],4660.);assert_eq!(frames[0].fields["b"],3.);
        let mut invalid=p;invalid.fields[2].bits.as_mut().unwrap().offset=1;assert!(invalid.validate().is_err());
    }
    #[test] fn oversized_delimiter_frame_and_empty_boundary_are_rejected(){
        let p:Protocol=serde_json::from_value(serde_json::json!({"schema_version":1,"name":"lines","tail":[10],"max_frame":32,"fields":[]})).unwrap();
        let mut decoder=Decoder::new(p.clone()).unwrap();let frames=decoder.feed(&vec![65;128],0.).unwrap();assert!(!frames.is_empty());assert!(decoder.buffer.len()<=32);
        let mut invalid=p;invalid.tail.clear();assert!(Decoder::new(invalid).is_err());
    }
}
