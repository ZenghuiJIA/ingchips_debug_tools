use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use sysinfo::{Pid, ProcessesToUpdate, System};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemMetrics {
    pub tauri_rss_mb: f64,
    pub daemon_rss_mb: f64,
    pub worker_rss_mb: f64,
    pub related_process_count: usize,
    pub total_rss_mb: f64,
    pub memory_budget_mb: f64,
    pub is_under_budget: bool,
    pub os_name: String,
    pub target_arch: String,
}

struct TrackedState {
    last_topology_scan: Option<Instant>,
    last_daemon_pid: Option<u32>,
    pids: Vec<Pid>,
}

pub struct MetricsCollector {
    sys: Mutex<System>,
    tracked: Mutex<TrackedState>,
}

impl MetricsCollector {
    pub fn new() -> Self {
        Self {
            sys: Mutex::new(System::new()),
            tracked: Mutex::new(TrackedState {
                last_topology_scan: None,
                last_daemon_pid: None,
                pids: Vec::new(),
            }),
        }
    }

    /// Collect RSS for the host process, optional daemon, and child workers.
    /// Full process-tree discovery runs only at startup, when `daemon_pid` changes,
    /// or every 15s; steady-state ticks refresh only the tracked PIDs.
    pub fn collect(&self, daemon_pid: Option<u32>) -> SystemMetrics {
        let current_pid = Pid::from_u32(std::process::id());
        let mut sys = self.sys.lock().unwrap();
        let mut tracked = self.tracked.lock().unwrap();

        let needs_topology_refresh = tracked.last_topology_scan.map_or(true, |t| {
            t.elapsed() >= Duration::from_secs(15)
        }) || tracked.last_daemon_pid != daemon_pid
            || tracked.pids.is_empty();

        if needs_topology_refresh {
            sys.refresh_processes(ProcessesToUpdate::All, true);
            let mut pids = vec![current_pid];
            if let Some(d_pid) = daemon_pid {
                pids.push(Pid::from_u32(d_pid));
            }
            loop {
                let children: Vec<_> = sys
                    .processes()
                    .iter()
                    .filter(|(pid, process)| {
                        !pids.contains(pid)
                            && process
                                .parent()
                                .map_or(false, |parent| pids.contains(&parent))
                    })
                    .map(|(pid, _)| *pid)
                    .collect();
                if children.is_empty() {
                    break;
                }
                pids.extend(children);
            }
            tracked.pids = pids;
            tracked.last_daemon_pid = daemon_pid;
            tracked.last_topology_scan = Some(Instant::now());
        } else {
            sys.refresh_processes(ProcessesToUpdate::Some(&tracked.pids), true);
        }

        let tauri_mem = sys.process(current_pid).map(|p| p.memory()).unwrap_or(0);
        let daemon_mem = daemon_pid
            .and_then(|p| sys.process(Pid::from_u32(p)).map(|proc| proc.memory()))
            .unwrap_or(0);

        let tauri_rss_mb = (tauri_mem as f64) / (1024.0 * 1024.0);
        let daemon_rss_mb = (daemon_mem as f64) / (1024.0 * 1024.0);
        let worker_mem: u64 = tracked
            .pids
            .iter()
            .filter(|pid| **pid != current_pid && Some(pid.as_u32()) != daemon_pid)
            .filter_map(|pid| sys.process(*pid))
            .map(|p| p.memory())
            .sum();
        let worker_rss_mb = (worker_mem as f64) / (1024.0 * 1024.0);
        let total_rss_mb = tauri_rss_mb + daemon_rss_mb + worker_rss_mb;
        let related_process_count = tracked
            .pids
            .iter()
            .filter(|pid| sys.process(**pid).is_some())
            .count();

        SystemMetrics {
            tauri_rss_mb: (tauri_rss_mb * 10.0).round() / 10.0,
            daemon_rss_mb: (daemon_rss_mb * 10.0).round() / 10.0,
            worker_rss_mb: (worker_rss_mb * 10.0).round() / 10.0,
            related_process_count,
            total_rss_mb: (total_rss_mb * 10.0).round() / 10.0,
            memory_budget_mb: 100.0,
            is_under_budget: total_rss_mb < 100.0,
            os_name: std::env::consts::OS.to_string(),
            target_arch: std::env::consts::ARCH.to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn metrics_collector_tracks_self_across_incremental_ticks() {
        let collector = MetricsCollector::new();
        let first = collector.collect(None);
        let second = collector.collect(None);
        assert!(first.tauri_rss_mb > 0.0);
        assert!(second.tauri_rss_mb > 0.0);
        assert!(second.related_process_count >= 1);
    }
}
