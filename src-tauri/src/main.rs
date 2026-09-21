#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    std::panic::set_hook(Box::new(|panic_info| {
        let msg = format!("PANIC: {:?}", panic_info);

        #[cfg(target_os = "windows")]
        {
            let log_dir = app_lib::platform::windows::environment::get_app_log_dir();
            let crash_file = log_dir.join("crash.log");
            let _ = std::fs::write(&crash_file, &msg);
            app_lib::platform::windows::environment::log_to_file(&format!("[PANIC] {}", msg));

            let title_w: Vec<u16> = "AI-HIL Debugger - 发生未捕获异常\0".encode_utf16().collect();
            let err_display = format!(
                "程序发生严重未捕获异常即将退出：\n\n{}\n\n详细崩溃日志已保存至：\n{:?}",
                panic_info, crash_file
            );
            let msg_w: Vec<u16> = err_display.encode_utf16().chain(std::iter::once(0)).collect();
            unsafe {
                windows_sys::Win32::UI::WindowsAndMessaging::MessageBoxW(
                    0 as _,
                    msg_w.as_ptr(),
                    title_w.as_ptr(),
                    windows_sys::Win32::UI::WindowsAndMessaging::MB_ICONERROR | windows_sys::Win32::UI::WindowsAndMessaging::MB_OK,
                );
            }
        }

        #[cfg(not(target_os = "windows"))]
        {
            eprintln!("{}", msg);
        }
    }));

    app_lib::run();
}
