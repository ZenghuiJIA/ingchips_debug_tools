use std::path::PathBuf;
use std::process::Command;
use windows_sys::Win32::Foundation::*;
use windows_sys::Win32::System::Registry::*;
use windows_sys::Win32::UI::WindowsAndMessaging::*;

const WEBVIEW2_RUNTIME_GUID: &str = "{F3017226-9E4F-4275-A055-2242004F4E83}";

pub fn get_app_data_dir() -> PathBuf {
    if let Some(local_app_data) = std::env::var_os("LOCALAPPDATA") {
        PathBuf::from(local_app_data).join("AI-HIL-Debugger")
    } else {
        std::env::temp_dir().join("AI-HIL-Debugger")
    }
}

pub fn get_app_log_dir() -> PathBuf {
    let dir = get_app_data_dir().join("logs");
    let _ = std::fs::create_dir_all(&dir);
    dir
}

pub fn log_to_file(msg: &str) {
    use std::io::Write;
    let pid = std::process::id();
    let log_path = get_app_log_dir().join("app_debug.log");
    if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open(&log_path) {
        let _ = writeln!(file, "[PID {}] {}", pid, msg);
    }

    // Also write to current directory if writable
    if let Ok(mut file) = std::fs::OpenOptions::new().create(true).append(true).open("app_debug.log") {
        let _ = writeln!(file, "[PID {}] {}", pid, msg);
    }
}

fn check_registry_key_pv(root: HKEY, subkey: &str, sam: u32) -> Option<String> {
    let subkey_w: Vec<u16> = subkey.encode_utf16().chain(std::iter::once(0)).collect();
    let mut hkey: HKEY = std::ptr::null_mut();

    let status = unsafe {
        RegOpenKeyExW(
            root,
            subkey_w.as_ptr(),
            0,
            sam,
            &mut hkey,
        )
    };

    if status != ERROR_SUCCESS || hkey.is_null() {
        return None;
    }

    let val_name_w: Vec<u16> = "pv".encode_utf16().chain(std::iter::once(0)).collect();
    let mut val_type: u32 = 0;
    let mut buf = [0u8; 128];
    let mut buf_size: u32 = buf.len() as u32;

    let res = unsafe {
        RegQueryValueExW(
            hkey,
            val_name_w.as_ptr(),
            std::ptr::null_mut(),
            &mut val_type,
            buf.as_mut_ptr(),
            &mut buf_size,
        )
    };

    unsafe {
        RegCloseKey(hkey);
    }

    if res == ERROR_SUCCESS && (val_type == REG_SZ || val_type == REG_EXPAND_SZ) {
        let u16_slice: &[u16] = unsafe {
            std::slice::from_raw_parts(buf.as_ptr() as *const u16, (buf_size as usize) / 2)
        };
        let mut s = String::from_utf16_lossy(u16_slice);
        if let Some(null_pos) = s.find('\0') {
            s.truncate(null_pos);
        }
        let s = s.trim().to_string();
        if !s.is_empty() && s != "0.0.0.0" {
            return Some(s);
        }
    }

    None
}

/// Detect whether Microsoft Edge WebView2 runtime is installed on this machine
pub fn is_webview2_installed() -> bool {
    let sam_flags = [KEY_READ, KEY_READ | KEY_WOW64_32KEY, KEY_READ | KEY_WOW64_64KEY];

    let paths = [
        format!(r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{}", WEBVIEW2_RUNTIME_GUID),
        format!(r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{}", WEBVIEW2_RUNTIME_GUID),
    ];

    for path in &paths {
        for &sam in &sam_flags {
            if let Some(ver) = check_registry_key_pv(HKEY_LOCAL_MACHINE, path, sam) {
                log_to_file(&format!("[ENV_CHECK] Found WebView2 (HKLM): {}", ver));
                return true;
            }
            if let Some(ver) = check_registry_key_pv(HKEY_CURRENT_USER, path, sam) {
                log_to_file(&format!("[ENV_CHECK] Found WebView2 (HKCU): {}", ver));
                return true;
            }
        }
    }

    // Fallback disk check: standard Edge WebView directory
    let common_dirs = [
        r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application",
        r"C:\Program Files\Microsoft\EdgeWebView\Application",
    ];
    for dir in &common_dirs {
        if std::path::Path::new(dir).exists() {
            log_to_file(&format!("[ENV_CHECK] Found WebView2 directory on disk: {}", dir));
            return true;
        }
    }

    false
}

/// Configure WebView2 UserDataFolder to a safe, guaranteed-writable path in %LOCALAPPDATA%
pub fn configure_webview_environment() {
    let app_data = get_app_data_dir();
    let eb_dir = app_data.join("EBWebView");
    let _ = std::fs::create_dir_all(&eb_dir);

    // Set WEBVIEW2_USER_DATA_FOLDER if not already explicitly provided
    if std::env::var_os("WEBVIEW2_USER_DATA_FOLDER").is_none() {
        std::env::set_var("WEBVIEW2_USER_DATA_FOLDER", &eb_dir);
        log_to_file(&format!("[ENV] Set WEBVIEW2_USER_DATA_FOLDER = {:?}", eb_dir));
    }

    // Add compatibility flags to prevent GPU / sandbox hangs on restricted Windows profiles
    if std::env::var_os("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS").is_none() {
        std::env::set_var(
            "WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS",
            "--disable-features=msWebOOUI,msPdfOOUI --no-first-run",
        );
    }
}

/// Verify environment, prompt user if WebView2 runtime is missing, and return whether to proceed
pub fn ensure_environment_ready() -> bool {
    configure_webview_environment();

    if !is_webview2_installed() {
        log_to_file("[ENV_CHECK] WebView2 runtime NOT detected! Prompting user...");

        let title_w: Vec<u16> = "AI-HIL Debugger - 缺少系统运行环境\0".encode_utf16().collect();
        let msg_w: Vec<u16> = concat!(
            "检测到当前系统尚未安装 Microsoft Edge WebView2 运行时。\n\n",
            "本软件需要该组件以渲染图形用户界面（微型系统级组件，无需完整 Edge 浏览器）。\n\n",
            "是否立即打开微软官方下载页面？\n",
            "(下载引导安装程序仅约 1.8MB，安装后即可直接正常使用)"
        )
        .encode_utf16()
        .chain(std::iter::once(0))
        .collect();

        let choice = unsafe {
            MessageBoxW(
                0 as _,
                msg_w.as_ptr(),
                title_w.as_ptr(),
                MB_ICONWARNING | MB_YESNO | MB_DEFBUTTON1,
            )
        };

        if choice == IDYES {
            // Open official evergreen bootstrapper download link
            let _ = Command::new("cmd")
                .args(["/c", "start", "https://go.microsoft.com/fwlink/p/?LinkId=2124703"])
                .spawn();
        }

        return false;
    }

    true
}
