use serde::{Deserialize, Serialize};
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

pub fn collect_metrics(daemon_pid: Option<u32>) -> SystemMetrics {
    let mut sys = System::new();
    let current_pid = Pid::from_u32(std::process::id());
    
    let mut pids_to_check = vec![current_pid];
    if let Some(d_pid) = daemon_pid {
        pids_to_check.push(Pid::from_u32(d_pid));
    }

    sys.refresh_processes(ProcessesToUpdate::All, true);
    loop {
        let children:Vec<_>=sys.processes().iter().filter(|(pid,process)|!pids_to_check.contains(pid)&&process.parent().map_or(false,|parent|pids_to_check.contains(&parent))).map(|(pid,_)|*pid).collect();
        if children.is_empty(){break;}pids_to_check.extend(children);
    }

    let tauri_mem = sys.process(current_pid).map(|p| p.memory()).unwrap_or(0);
    let daemon_mem = daemon_pid
        .and_then(|p| sys.process(Pid::from_u32(p)).map(|proc| proc.memory()))
        .unwrap_or(0);

    let tauri_rss_mb = (tauri_mem as f64) / (1024.0 * 1024.0);
    let daemon_rss_mb = (daemon_mem as f64) / (1024.0 * 1024.0);
    let worker_mem:u64=pids_to_check.iter().filter(|pid|**pid!=current_pid&&Some(pid.as_u32())!=daemon_pid).filter_map(|pid|sys.process(*pid)).map(|p|p.memory()).sum();
    let worker_rss_mb=worker_mem as f64/(1024.0*1024.0);
    let total_rss_mb = tauri_rss_mb + daemon_rss_mb + worker_rss_mb;

    SystemMetrics {
        tauri_rss_mb: (tauri_rss_mb * 10.0).round() / 10.0,
        daemon_rss_mb: (daemon_rss_mb * 10.0).round() / 10.0,
        worker_rss_mb: (worker_rss_mb*10.0).round()/10.0,
        related_process_count:pids_to_check.iter().filter(|pid|sys.process(**pid).is_some()).count(),
        total_rss_mb: (total_rss_mb * 10.0).round() / 10.0,
        memory_budget_mb: 100.0,
        is_under_budget: total_rss_mb < 100.0,
        os_name: std::env::consts::OS.to_string(),
        target_arch: std::env::consts::ARCH.to_string(),
    }
}
