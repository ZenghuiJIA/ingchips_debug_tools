#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    std::panic::set_hook(Box::new(|panic_info| {
        let msg = format!("PANIC: {:?}", panic_info);
        let _ = std::fs::write("crash.log", &msg);
        use std::io::Write;
        if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open("app_debug.log") {
            let _ = writeln!(f, "[PANIC] {}", msg);
        }
    }));

    app_lib::run();
}
