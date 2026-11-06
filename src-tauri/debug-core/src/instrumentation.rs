//! HILI v1 framing. Integers wider than JS's exact range serialize as decimal strings.
use serde::{Serialize,Deserialize};
use base64::Engine;
pub const HEADER:usize=40;
pub const MAX_PAYLOAD:usize=1024;
pub fn crc32(parts:&[&[u8]])->u32{let mut crc=0xffff_ffffu32;for part in parts{for byte in *part{crc^=*byte as u32;for _ in 0..8{crc=(crc>>1)^if crc&1!=0{0xedb88320}else{0};}}}crc^0xffff_ffff}
#[derive(Debug,Clone,Serialize,Deserialize)]
pub struct Event{pub major:u8,pub minor:u8,pub event_type:u16,pub flags:u16,pub boot_id:String,pub sequence:u32,pub ticks:String,pub payload_hex:String,pub offset:u64}
pub fn encode(event:&Event)->Result<Vec<u8>,String>{
    if event.major!=1||event.flags!=0{return Err("Unsupported HILI version/flags".into());}
    let payload=crate::capture::unhex(&event.payload_hex)?;if payload.len()>MAX_PAYLOAD{return Err("HILI payload exceeds 1024 bytes".into());}
    let boot=event.boot_id.parse::<u64>().map_err(|_|"Invalid boot_id")?;let ticks=event.ticks.parse::<u64>().map_err(|_|"Invalid ticks")?;
    let mut bytes=vec![0u8;HEADER];bytes[..4].copy_from_slice(b"HILI");bytes[4]=1;bytes[5]=event.minor;bytes[6..8].copy_from_slice(&event.event_type.to_le_bytes());bytes[8..10].copy_from_slice(&(HEADER as u16).to_le_bytes());bytes[12..16].copy_from_slice(&(payload.len()as u32).to_le_bytes());bytes[16..24].copy_from_slice(&boot.to_le_bytes());bytes[24..28].copy_from_slice(&event.sequence.to_le_bytes());bytes[28..36].copy_from_slice(&ticks.to_le_bytes());let crc=crc32(&[&bytes[..36],&payload]);bytes[36..40].copy_from_slice(&crc.to_le_bytes());bytes.extend(payload);Ok(bytes)
}
#[derive(Debug,Serialize)]pub struct DecodeResult{pub events:Vec<Event>,pub errors:Vec<serde_json::Value>}
pub struct Decoder{buffer:Vec<u8>,offset:u64,partial:Option<f64>,last:f64,pub timeout_ms:f64,text:bool}
impl Decoder{
    pub fn new(text:bool,timeout_ms:f64)->Result<Self,String>{if !timeout_ms.is_finite()||timeout_ms<=0.{return Err("Positive timeout required".into());}Ok(Self{buffer:vec![],offset:0,partial:None,last:0.,timeout_ms,text})}
    pub fn feed(&mut self,bytes:&[u8],now:f64)->Result<DecodeResult,String>{
        let original_offset=self.offset;
        if !now.is_finite()||now<self.last||bytes.len()>1024*1024{return Err("Invalid HILI time/chunk size".into());}self.last=now;let mut result=DecodeResult{events:vec![],errors:vec![]};
        if self.partial.map_or(false,|t|now-t>=self.timeout_ms)&&!self.buffer.is_empty(){result.errors.push(serde_json::json!({"code":"PARTIAL_TIMEOUT","offset":self.offset,"length":self.buffer.len()}));self.offset+=self.buffer.len()as u64;self.buffer.clear();self.partial=None;}
        let was_empty=self.buffer.is_empty();self.buffer.extend(bytes);if was_empty&&!bytes.is_empty(){self.partial=Some(now);}
        if self.text{
            while let Some(end)=self.buffer.iter().position(|b|*b==b'\n'){
                let line:Vec<u8>=self.buffer.drain(..=end).collect();let at=self.offset;self.offset+=line.len()as u64;
                if line.starts_with(b"@HILI1 "){
                    let body=&line[7..line.len()-1];let body=body.strip_suffix(b"\r").unwrap_or(body);
                    if body.len()>1420{result.errors.push(serde_json::json!({"code":"LINE_TOO_LONG","offset":at}));continue;}
                    match base64::engine::general_purpose::STANDARD.decode(body){Ok(frame)=>match decode_one(&frame,at){Ok(e)=>result.events.push(e),Err(e)=>result.errors.push(serde_json::json!({"code":e,"offset":at}))},Err(_)=>result.errors.push(serde_json::json!({"code":"INVALID_BASE64","offset":at}))}
                }
            }
            if self.buffer.len()>65536{result.errors.push(serde_json::json!({"code":"LINE_OVERFLOW","offset":self.offset}));self.offset+=self.buffer.len()as u64;self.buffer.clear();}
        }else{
            loop{
                if self.buffer.len()<4{break;}
                if !self.buffer.starts_with(b"HILI"){let skip=self.buffer.windows(4).position(|w|w==b"HILI").unwrap_or(self.buffer.len()-3);result.errors.push(serde_json::json!({"code":"NOISE","offset":self.offset,"length":skip}));self.buffer.drain(..skip);self.offset+=skip as u64;continue;}
                if self.buffer.len()<HEADER{break;}
                let payload=u32::from_le_bytes(self.buffer[12..16].try_into().unwrap())as usize;
                if self.buffer[4]!=1||self.buffer[8..10]!=(HEADER as u16).to_le_bytes()||self.buffer[10..12]!=[0,0]||payload>MAX_PAYLOAD{result.errors.push(serde_json::json!({"code":"INVALID_HEADER","offset":self.offset}));self.buffer.remove(0);self.offset+=1;continue;}
                if self.buffer.len()<HEADER+payload{break;}
                match decode_one(&self.buffer[..HEADER+payload],self.offset){Ok(event)=>{result.events.push(event);self.buffer.drain(..HEADER+payload);self.offset+=(HEADER+payload)as u64;},Err(error)=>{result.errors.push(serde_json::json!({"code":error,"offset":self.offset}));self.buffer.remove(0);self.offset+=1;}}
            }
        }
        self.partial=if self.buffer.is_empty(){None}else if self.offset!=original_offset{Some(now)}else{self.partial.or(Some(now))};Ok(result)
    }
    pub fn finish(&self)->Option<serde_json::Value>{if self.buffer.is_empty(){None}else{Some(serde_json::json!({"code":"TRUNCATED_FRAME","offset":self.offset,"length":self.buffer.len()}))}}
}
fn decode_one(bytes:&[u8],offset:u64)->Result<Event,String>{if bytes.len()<HEADER||&bytes[..4]!=b"HILI"||bytes[4]!=1||bytes[8..10]!=(HEADER as u16).to_le_bytes()||bytes[10..12]!=[0,0]{return Err("INVALID_HEADER".into());}let n=u32::from_le_bytes(bytes[12..16].try_into().unwrap())as usize;if n>MAX_PAYLOAD||bytes.len()!=HEADER+n{return Err("INVALID_LENGTH".into());}if crc32(&[&bytes[..36],&bytes[40..]])!=u32::from_le_bytes(bytes[36..40].try_into().unwrap()){return Err("CRC_MISMATCH".into());}Ok(Event{major:1,minor:bytes[5],event_type:u16::from_le_bytes(bytes[6..8].try_into().unwrap()),flags:0,boot_id:u64::from_le_bytes(bytes[16..24].try_into().unwrap()).to_string(),sequence:u32::from_le_bytes(bytes[24..28].try_into().unwrap()),ticks:u64::from_le_bytes(bytes[28..36].try_into().unwrap()).to_string(),payload_hex:crate::capture::hex(&bytes[40..]),offset})}
#[cfg(test)]mod tests{use super::*;fn event()->Event{Event{major:1,minor:0,event_type:3,flags:0,boot_id:"18446744073709551615".into(),sequence:u32::MAX,ticks:"9007199254740993".into(),payload_hex:"0100000002000000".into(),offset:0}}#[test]fn crc_and_all_splits(){assert_eq!(crc32(&[b"123456789"]),0xcbf43926);let frame=encode(&event()).unwrap();for n in 0..=frame.len(){let mut d=Decoder::new(false,1000.).unwrap();let mut a=d.feed(&frame[..n],0.).unwrap().events;a.extend(d.feed(&frame[n..],1.).unwrap().events);assert_eq!(a.len(),1);assert_eq!(a[0].ticks,event().ticks);}}
#[test]fn corruption_recovery_and_text(){let good=encode(&event()).unwrap();let mut data=good.clone();data[40]^=1;data.extend(&good);let r=Decoder::new(false,1000.).unwrap().feed(&data,0.).unwrap();assert_eq!(r.events.len(),1);assert!(!r.errors.is_empty());let line=format!("noise\n@HILI1 {}\n",base64::engine::general_purpose::STANDARD.encode(good));assert_eq!(Decoder::new(true,1000.).unwrap().feed(line.as_bytes(),0.).unwrap().events.len(),1);}
#[test]fn limits_and_timeout(){let mut d=Decoder::new(false,5.).unwrap();d.feed(b"HILI",0.).unwrap();assert_eq!(d.feed(&[],6.).unwrap().errors[0]["code"],"PARTIAL_TIMEOUT");let mut e=event();e.major=2;assert!(encode(&e).is_err());}}
