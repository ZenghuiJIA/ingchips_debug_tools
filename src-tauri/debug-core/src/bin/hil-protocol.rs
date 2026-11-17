//! Bounded JSONL adapter to the exact codec used by the desktop.
use hil_debug_core::{capture::{hex, unhex}, protocol::{Protocol,Decoder}};
use serde_json::{Value,json};
use std::io::{BufRead,Write,Read};
fn main() {
    let mut decoders=std::collections::HashMap::<String,Decoder>::new();
    let mut instrumentation=std::collections::HashMap::<String,hil_debug_core::instrumentation::Decoder>::new();
    let mut reader=std::io::stdin().lock(); let mut writer=std::io::stdout().lock();
    loop {
        let mut line=Vec::new();
        let n=match reader.by_ref().take(4*1024*1024+1).read_until(b'\n',&mut line){Ok(n)=>n,Err(_)=>break};
        if n==0{break;}
        if n>4*1024*1024{let _=writeln!(writer,"{}",json!({"error":"Request exceeds 4 MiB"}));break;}
        let input=serde_json::from_slice::<Value>(&line);
        let id=input.as_ref().ok().and_then(|v|v.get("id")).cloned().unwrap_or(Value::Null);
        let output=(||->Result<Value,String>{
            let input=input.map_err(|e|e.to_string())?;
            let session=input["session"].as_str().unwrap_or("default").to_string();
            match input["operation"].as_str().unwrap_or("") {
                "hili_encode"=>{let e=serde_json::from_value(input["event"].clone()).map_err(|e|e.to_string())?;Ok(json!({"data":hex(&hil_debug_core::instrumentation::encode(&e)?)}))},
                "hili_configure"=>{if instrumentation.len()>=64&&!instrumentation.contains_key(&session){return Err("Session limit".into());}instrumentation.insert(session,hil_debug_core::instrumentation::Decoder::new(input["mode"]=="text",input["timeout_ms"].as_f64().unwrap_or(1000.))?);Ok(json!({"configured":true}))},
                "hili_feed"=>{let d=instrumentation.get_mut(&session).ok_or("Configure HILI session first")?;Ok(json!(d.feed(&unhex(input["data"].as_str().ok_or("HEX data required")?)?,input["elapsed_ms"].as_f64().ok_or("elapsed_ms required")?)?))},
                "hili_finish"=>{let d=instrumentation.remove(&session).ok_or("Unknown HILI session")?;Ok(json!({"partial":d.finish()}))},
                "replay"=>{let p:Protocol=serde_json::from_value(input["protocol"].clone()).map_err(|e|e.to_string())?;hil_debug_core::analysis::replay(p,input["events"].as_array().ok_or("events must be an array")?)},
                "validate"=>{let p:Protocol=serde_json::from_value(input["protocol"].clone()).map_err(|e|e.to_string())?;p.validate()?;Ok(json!({"valid":true}))},
                "encode"=>{let p:Protocol=serde_json::from_value(input["protocol"].clone()).map_err(|e|e.to_string())?;let values=input["values"].as_object().ok_or("values must be an object")?;Ok(json!({"data":hex(&p.encode(values)?)}))},
                "configure"=>{if !decoders.contains_key(&session)&&decoders.len()>=64{return Err("Session limit".into());}let p:Protocol=serde_json::from_value(input["protocol"].clone()).map_err(|e|e.to_string())?;decoders.insert(session,Decoder::new(p)?);Ok(json!({"configured":true}))},
                "feed"=>{let decoder=decoders.get_mut(&session).ok_or("Configure session first")?;let data=unhex(input["data"].as_str().ok_or("data must be HEX")?)?;Ok(json!({"frames":decoder.feed(&data,input["elapsed_ms"].as_f64().ok_or("elapsed_ms is required")?)?}))},
                "close"=>{decoders.remove(&session);Ok(json!({"closed":true}))},
                _=>Err("Unknown protocol operation".into())
            }
        })();
        let response=match output{Ok(result)=>json!({"id":id,"result":result}),Err(error)=>json!({"id":id,"error":error})};
        if writeln!(writer,"{response}").and_then(|_|writer.flush()).is_err(){break;}
    }
}
