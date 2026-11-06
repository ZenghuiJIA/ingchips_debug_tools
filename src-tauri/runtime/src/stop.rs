//! Stop acknowledgements belong to one session and only bytes after the request cursor.
use crate::{config::serial_regex, stream::Journal};
use serde_json::Value;
use std::time::{Duration, Instant};

// Deliberately independent of the run cancellation flag: cleanup must await the device.
pub fn wait_ack(
    deadline: Instant,
    mut poll: impl FnMut() -> Result<bool, String>,
) -> Result<(), String> {
    while Instant::now() < deadline {
        if poll()? {
            return Ok(());
        }
        std::thread::sleep(Duration::from_millis(10));
    }
    Err("STOP_UNCONFIRMED: STOPPED acknowledgement timeout".into())
}

pub struct StopAck {
    session: String,
    cursor: u64,
    window: Vec<u8>,
    pattern: Vec<u8>,
    regex: Option<regex::bytes::Regex>,
}
impl StopAck {
    pub fn new(session: String, cursor: u64, cfg: &Value) -> Result<Self, String> {
        let pattern = cfg["ack_pattern"]
            .as_str()
            .filter(|s| !s.is_empty() && s.len() <= 4096)
            .ok_or("stop.ack_pattern must contain 1..4096 bytes")?;
        let regex = match cfg["match_type"].as_str().unwrap_or("contains") {
            "contains" => None,
            "regex" => {
                let re = serial_regex(pattern)?;
                if re.is_match(b"") {
                    return Err("Stop regex must not match empty input".into());
                }
                Some(re)
            }
            _ => return Err("Invalid stop.match_type".into()),
        };
        Ok(Self {
            session,
            cursor,
            window: Vec::new(),
            pattern: pattern.as_bytes().into(),
            regex,
        })
    }
    pub fn poll(
        &mut self,
        session: &str,
        journal: &Journal,
        connected: bool,
    ) -> Result<bool, String> {
        if session != self.session || !connected {
            return Err("STOP_UNCONFIRMED: serial session changed/disconnected".into());
        }
        let (chunks, end) = journal.read(self.cursor)?;
        self.cursor = end;
        for c in chunks {
            self.window.extend_from_slice(&c.data);
            if self.window.len() > 65536 {
                return Err("STOP_UNCONFIRMED: acknowledgement window exceeds 64 KiB".into());
            }
            if self.regex.as_ref().map_or_else(
                || {
                    self.window
                        .windows(self.pattern.len())
                        .any(|w| w == self.pattern)
                },
                |r| r.is_match(&self.window),
            ) {
                return Ok(true);
            }
        }
        Ok(false)
    }
}
pub fn request_bytes(cfg: &Value) -> Result<Vec<u8>, String> {
    let text = cfg["send_data"]
        .as_str()
        .filter(|s| !s.is_empty() && s.len() <= 4096)
        .ok_or("stop.send_data must contain 1..4096 bytes")?;
    let mut data = match cfg["send_format"].as_str().unwrap_or("string") {
        "string" => text.as_bytes().to_vec(),
        "hex" => hil_debug_core::capture::unhex(text)?,
        _ => return Err("Invalid stop.send_format".into()),
    };
    if data.is_empty() {
        return Err("Empty STOP command".into());
    }
    data.extend_from_slice(match cfg["send_ending"].as_str().unwrap_or("none") {
        "none" => b"",
        "lf" => b"\n",
        "crlf" => b"\r\n",
        _ => return Err("Invalid stop.send_ending".into()),
    });
    Ok(data)
}
#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;
    #[test]
    fn timeout_and_io_failure_never_confirm() {
        assert!(wait_ack(Instant::now(), || Ok(true))
            .unwrap_err()
            .contains("timeout"));
        assert!(
            wait_ack(Instant::now() + Duration::from_millis(20), || Ok(false))
                .unwrap_err()
                .contains("timeout")
        );
        assert_eq!(
            wait_ack(Instant::now() + Duration::from_secs(1), || Err(
                "disconnected".into()
            ))
            .unwrap_err(),
            "disconnected"
        );
        assert!(wait_ack(Instant::now() + Duration::from_secs(1), || Ok(true)).is_ok());
    }
    #[test]
    fn old_ack_split_coalesced_and_session_identity() {
        for split in 0..=13 {
            let mut j = Journal::default();
            j.append(b"HILv1 STOPPED\n", 0.);
            let mut ack =
                StopAck::new("one".into(), j.end, &json!({"ack_pattern":"HILv1 STOPPED"})).unwrap();
            assert!(!ack.poll("one", &j, true).unwrap());
            let wire = b"HILv1 STOPPED\n";
            j.append(&wire[..split], 1.);
            let first = ack.poll("one", &j, true).unwrap();
            j.append(&wire[split..], 2.);
            assert!(first || ack.poll("one", &j, true).unwrap());
            assert!(ack.poll("two", &j, true).is_err());
            assert!(ack.poll("one", &j, false).is_err());
        }
    }
    #[test]
    fn bad_regex_overrun_disconnect_and_command_encoding() {
        assert!(StopAck::new(
            "s".into(),
            0,
            &json!({"match_type":"regex","ack_pattern":".*"})
        )
        .is_err());
        let mut ack = StopAck::new("s".into(), 0, &json!({"ack_pattern":"STOPPED"})).unwrap();
        let mut j = Journal::default();
        j.append(&vec![0; 2 * 1024 * 1024], 0.);
        assert!(ack.poll("s", &j, true).is_err());
        let mut j = Journal::default();
        j.error = Some("unplugged".into());
        assert!(ack.poll("s", &j, true).is_err());
        assert_eq!(
            request_bytes(&json!({"send_data":"STOP","send_ending":"crlf"})).unwrap(),
            b"STOP\r\n"
        );
        assert_eq!(
            request_bytes(&json!({"send_data":"53544F50","send_format":"hex"})).unwrap(),
            b"STOP"
        );
    }
}
