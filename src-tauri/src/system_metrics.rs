use serde::{Deserialize, Serialize};
use sysinfo::{Pid, ProcessesToUpdate, System};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemMetrics {
    pub tauri_rss_mb: f64,
    pub daemon_rss_mb: f64,
    pub total_rss_mb: f64,
    pub memory_budget_mb: f64,
    pub is_under_budget: bool,
    pub os_name: String,
    pub target_arch: String,
}

pub fn collect_metrics(daemon_pid: Option<u32>) -> SystemMetrics {
    let mut sys = System::new();
    let current_pid = Pid::from_u32(std::process::id());
    
    let mut pids_to_check = vec![current_pid];
    if let Some(d_pid) = daemon_pid {
        pids_to_check.push(Pid::from_u32(d_pid));
    }

    sys.refresh_processes(ProcessesToUpdate::Some(&pids_to_check), true);

    let tauri_mem = sys.process(current_pid).map(|p| p.memory()).unwrap_or(0);
    let daemon_mem = daemon_pid
        .and_then(|p| sys.process(Pid::from_u32(p)).map(|proc| proc.memory()))
        .unwrap_or(0);

    let tauri_rss_mb = (tauri_mem as f64) / (1024.0 * 1024.0);
    let daemon_rss_mb = (daemon_mem as f64) / (1024.0 * 1024.0);
    let total_rss_mb = tauri_rss_mb + daemon_rss_mb;

    SystemMetrics {
        tauri_rss_mb: (tauri_rss_mb * 10.0).round() / 10.0,
        daemon_rss_mb: (daemon_rss_mb * 10.0).round() / 10.0,
        total_rss_mb: (total_rss_mb * 10.0).round() / 10.0,
        memory_budget_mb: 100.0,
        is_under_budget: total_rss_mb < 100.0,
        os_name: std::env::consts::OS.to_string(),
        target_arch: std::env::consts::ARCH.to_string(),
    }
}
