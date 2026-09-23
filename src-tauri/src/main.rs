#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    // Optimization: Constrain Edge WebView2 GPU & Renderer memory footprint
    #[cfg(target_os = "windows")]
    {
        if std::env::var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS").is_err() {
            // --disable-features=AudioServiceOutOfProcess: save dedicated audio subprocess
            // --disable-background-networking: stop Edge background telemetries
            // --disable-gpu-memory-buffer-compositor-resources: stop allocating multiple swapchain GPU surfaces
            // --gpu-memory-buffer-compositor-resources=1: minimize frame buffer memory
            // --disable-breakpad: save crash reporting worker overhead
            std::env::set_var(
                "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
                "--disable-features=AudioServiceOutOfProcess,MediaRouter,OptimizationHints \
                 --disable-background-networking \
                 --disable-breakpad \
                 --disable-gpu-memory-buffer-compositor-resources \
                 --gpu-memory-buffer-compositor-resources=1 \
                 --js-flags=--max-old-space-size=256"
            );
        }
    }

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
