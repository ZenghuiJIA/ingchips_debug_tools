use serde_json::{Value,json};
use std::collections::HashMap;
use crate::{protocol::{Protocol,Decoder},capture::unhex};
pub fn replay(protocol: Protocol, events: &[Value]) -> Result<Value,String> {
    protocol.validate()?;
    if events.len()>200000{return Err("Replay event limit exceeded".into());}
    let mut decoders=HashMap::<String,Decoder>::new();let mut frames=Vec::new();let mut last=HashMap::<String,f64>::new();let mut bytes=0;
    for (index,event) in events.iter().enumerate(){
        let direction=event["direction"].as_str().unwrap_or(if event["kind"]=="serial"{"RX"}else{"INFO"});
        if direction!="RX"{continue;}
        let session=event["session_id"].as_str().or_else(||event["port"].as_str()).unwrap_or("legacy").to_string();
        let stamp=event["elapsed_ms"].as_f64().ok_or("RX event needs elapsed_ms")?;
        if !stamp.is_finite()||stamp<0.||last.get(&session).map_or(false,|t|stamp<*t){return Err("Nonmonotonic recording timestamp".into());}last.insert(session.clone(),stamp);
        if !decoders.contains_key(&session){if decoders.len()>=64{return Err("Too many sessions".into());}decoders.insert(session.clone(),Decoder::new(protocol.clone())?);}
        let data=unhex(event["data"].as_str().ok_or("RX event needs HEX data")?)?;bytes+=data.len();if bytes>32*1024*1024{return Err("Replay preview exceeds 32 MiB; select a smaller recording segment".into());}
        for frame in decoders.get_mut(&session).unwrap().feed(&data,stamp)? {
            frames.push(json!({"session_id":session,"seq":event["seq"].as_u64().unwrap_or(index as u64),"elapsed_ms":stamp,"frame":frame}));
            if frames.len()>100000{return Err("Replay frame limit exceeded".into());}
        }
    }
    Ok(json!({"mode":"REPLAY_ONLY","hardware_verified":false,"frames":frames}))
}

#[cfg(test)]mod tests{
    use super::*;
    #[test]fn replay_keeps_sessions_separate_and_ignores_tx(){
        let protocol:Protocol=serde_json::from_value(json!({"schema_version":1,"name":"two","fixed_length":2,"fields":[{"name":"v","offset":0,"type":"uint16"}]})).unwrap();
        let events=vec![json!({"session_id":"a","direction":"RX","elapsed_ms":0,"data":"01"}),json!({"session_id":"b","direction":"RX","elapsed_ms":0,"data":"0200"}),json!({"session_id":"a","direction":"TX","elapsed_ms":1,"data":"ffff"}),json!({"session_id":"a","direction":"RX","elapsed_ms":2,"data":"00"})];
        let result=replay(protocol.clone(),&events).unwrap();assert_eq!(result["frames"].as_array().unwrap().len(),2);assert_eq!(result["frames"][1]["frame"]["fields"]["v"],1.);
        let mut bad=events;bad.push(json!({"session_id":"a","direction":"RX","elapsed_ms":1,"data":"0000"}));assert!(replay(protocol,&bad).is_err());
    }
}
