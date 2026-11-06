//! Board-declared host control line levels. USB vendor names never imply wiring.
use serde::{Deserialize, Serialize};
use std::time::{Duration, Instant};
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PinReset {
    pub profile_id: String,
    pub wiring_verified: bool,
    pub reset_asserted_dtr: bool,
    pub boot_asserted_rts: bool,
    pub settle_ms: u64,
    pub pulse_ms: u64,
    pub boot_hold_ms: u64,
}
impl PinReset {
    pub fn validate(&self) -> Result<(), String> {
        if self.profile_id.trim().is_empty() || !self.wiring_verified {
            return Err("Pin reset requires an explicitly verified board wiring profile".into());
        }
        if !(1..=5000).contains(&self.pulse_ms) || self.settle_ms > 5000 || self.boot_hold_ms > 5000
        {
            return Err("Invalid pin reset timing (maximum 5000 ms per stage)".into());
        }
        Ok(())
    }
}
pub trait ResetLines {
    fn dtr(&self, level: bool) -> Result<(), String>;
    fn rts(&self, level: bool) -> Result<(), String>;
}
pub fn execute(
    lines: &impl ResetLines,
    p: &PinReset,
    boot: bool,
    end: Instant,
    cancel: impl Fn() -> bool,
) -> Result<(), String> {
    execute_with_wait(lines, p, boot, |ms| {
        let until = Instant::now() + Duration::from_millis(ms);
        loop {
            if cancel() {
                return Err("CANCELLED".into());
            }
            if Instant::now() >= end {
                return Err("TIMEOUT: pin reset sequence".into());
            }
            if Instant::now() >= until {
                return Ok(());
            }
            std::thread::sleep(Duration::from_millis(2));
        }
    })
}
fn execute_with_wait(
    lines: &impl ResetLines,
    p: &PinReset,
    boot: bool,
    mut wait: impl FnMut(u64) -> Result<(), String>,
) -> Result<(), String> {
    p.validate()?;
    wait(0)?;
    // Always deassert reset first, select boot strap, then produce one reset pulse.
    let result = (|| {
        lines.dtr(!p.reset_asserted_dtr)?;
        lines.rts(if boot {
            p.boot_asserted_rts
        } else {
            !p.boot_asserted_rts
        })?;
        wait(p.settle_ms)?;
        lines.dtr(p.reset_asserted_dtr)?;
        wait(p.pulse_ms)?;
        lines.dtr(!p.reset_asserted_dtr)?;
        wait(p.boot_hold_ms)?;
        lines.rts(!p.boot_asserted_rts)?;
        Ok(())
    })();
    if result.is_err() {
        // Release asserted lines even on cancellation; preserve failure if cleanup cannot be confirmed.
        let d = lines.dtr(!p.reset_asserted_dtr);
        let r = lines.rts(!p.boot_asserted_rts);
        if d.is_err() || r.is_err() {
            return Err(format!("PIN_STATE_UNKNOWN: reset cleanup failed (DTR={d:?}, RTS={r:?}); original={result:?}"));
        }
    }
    result
}
#[cfg(test)]
mod tests {
    use super::*;
    use std::cell::RefCell;
    struct Lines(RefCell<Vec<(char, bool)>>);
    impl ResetLines for Lines {
        fn dtr(&self, x: bool) -> Result<(), String> {
            self.0.borrow_mut().push(('D', x));
            Ok(())
        }
        fn rts(&self, x: bool) -> Result<(), String> {
            self.0.borrow_mut().push(('R', x));
            Ok(())
        }
    }
    fn p() -> PinReset {
        PinReset {
            profile_id: "fixture".into(),
            wiring_verified: true,
            reset_asserted_dtr: true,
            boot_asserted_rts: true,
            settle_ms: 50,
            pulse_ms: 100,
            boot_hold_ms: 10,
        }
    }
    #[test]
    fn boot_sequence_polarities_and_timings() {
        let lines = Lines(RefCell::new(vec![]));
        let mut times = vec![];
        execute_with_wait(&lines, &p(), true, |ms| {
            times.push(ms);
            Ok(())
        })
        .unwrap();
        assert_eq!(
            *lines.0.borrow(),
            vec![
                ('D', false),
                ('R', true),
                ('D', true),
                ('D', false),
                ('R', false)
            ]
        );
        assert_eq!(times, vec![0, 50, 100, 10]);
        let mut inv = p();
        inv.reset_asserted_dtr = false;
        inv.boot_asserted_rts = false;
        let lines = Lines(RefCell::new(vec![]));
        execute_with_wait(&lines, &inv, false, |_| Ok(())).unwrap();
        assert_eq!(lines.0.borrow()[1], ('R', true));
        assert_eq!(lines.0.borrow()[2], ('D', false));
    }
    #[test]
    fn cancel_each_wait_releases_lines_and_unverified_never_writes() {
        for cancelled in 0..4 {
            let lines = Lines(RefCell::new(vec![]));
            let mut n = 0;
            let result = execute_with_wait(&lines, &p(), true, |_| {
                let cancel = n == cancelled;
                n += 1;
                if cancel {
                    Err("CANCELLED".into())
                } else {
                    Ok(())
                }
            });
            assert!(result.is_err());
            if cancelled == 0 {
                assert!(lines.0.borrow().is_empty());
            } else {
                assert_eq!(
                    &lines.0.borrow()[lines.0.borrow().len() - 2..],
                    &[('D', false), ('R', false)]
                );
            }
        }
        let mut bad = p();
        bad.wiring_verified = false;
        let lines = Lines(RefCell::new(vec![]));
        assert!(execute_with_wait(&lines, &bad, true, |_| Ok(())).is_err());
        assert!(lines.0.borrow().is_empty());
    }
}
