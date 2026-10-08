import { ref } from 'vue';

export type LocaleType = 'zh' | 'en';

const LOCALE_STORAGE_KEY = 'ai_hil_app_locale';

export const currentLocale = ref<LocaleType>(
  (localStorage.getItem(LOCALE_STORAGE_KEY) as LocaleType) || 'zh'
);

export function setLocale(lang: LocaleType) {
  currentLocale.value = lang;
  localStorage.setItem(LOCALE_STORAGE_KEY, lang);
}

export const messages: Record<LocaleType, Record<string, string>> = {
  zh: {
    // Top Brand & Nav
    app_title: 'AI-HIL Debugger',
    hardware_online: '硬件在线',
    waiting_hardware: '等待连接硬件',
    ports_connected: '个端口已连接',
    active_sessions_online: '端口会话在线',
    no_active_conn: '无活动连接',
    ram_usage: 'RAM',
    memory_strict_budget: '空载内存: < 100MB 严格受控',
    hardware_scheduler_ok: '硬件调度器正常运行',
    browser_mode_notice: '当前处于 Web 浏览器预览模式 (模拟数据)。访问物理硬件 (DAPLink / COM / SWD) 请运行桌面客户端。',
    pin_management_notice: '多串口及硬件引脚 (DTR/RTS/复位) 均已由标签页独立自主管理',

    // Main Navigation Tabs
    tab_terminal: '串口高速监控',
    tab_plotter: '实时波形示波器',
    tab_flasher: 'SWD 固件烧录',
    tab_merger: 'HEX/BIN 合并器',
    tab_analyzer: '固件资源分析',
    tab_svd: 'SVD 外设寄存器',
    tab_rtos: 'RTOS 任务Trace',
    tab_lcd: '屏幕显存镜像',
    tab_hardfault: 'HardFault 寄存器诊断',
    tab_memory: '内存查看与Dump',
    tab_ai: 'AI 硬件在环助手 (MCP)',
    
    // Floating Toolbar
    toolbar_toggle_expand: '展开快捷工具栏',
    toolbar_toggle_collapse: '收起快捷工具栏',
    toolbar_settings: '设置',
    toolbar_theme: '换肤',
    toolbar_screenshot: '截屏',
    toolbar_screenshot_saved: '已保存',
    toolbar_screenshot_success: '截屏已成功保存或复制！',

    // Settings Modal
    settings_title: '应用设置与偏好',
    settings_appearance: '皮肤与外观',
    settings_mode_label: '显示模式',
    settings_mode_dark: '深色模式',
    settings_mode_light: '浅色模式',
    settings_theme_preset: '皮肤预设与基调',
    settings_language: '界面语言 (Language)',
    settings_typography: '字体与排版',
    settings_font_family: '界面与代码等宽字体',
    settings_font_size: '全局字体缩放',
    settings_reset: '恢复默认设置',
    settings_close: '完成并关闭',

    // Theme Presets
    theme_dark_slate: '极客碳黑 (Cyberpunk Slate)',
    theme_dark_navy: '暗夜深蓝 (Midnight Navy)',
    theme_dark_forest: '极光绿境 (Matrix Emerald)',
    theme_dark_crimson: '黑曜绯红 (Obsidian Crimson)',
    theme_dark_purple: '暗夜紫霓 (Cyberpunk Purple)',
    theme_light_white: '现代象牙白 (Crisp Porcelain)',
    theme_light_warm: '护眼素暖 (Warm Parchment)',
    theme_light_ice: '极简冰川蓝 (Glacier Slate)',
    theme_light_sakura: '柔光粉樱 (Blossom Mist)',

    // Serial Terminal
    term_no_ports_open: '暂无打开的串口设备',
    term_open_new_port: '打开新端口',
    term_concurrent_conns: '并发连接数',
    term_ready_desc: '多设备终端就绪，可点击上方【打开新端口】添加并行串口、DAPLink 或 RTT 监视通道',
    term_log_stream: '日志流',
    term_vt100: 'VT100 终端',
    term_ascii: 'ASCII 文本',
    term_hex: 'HEX',
    term_timestamps: '时间戳',
    term_autoscroll: '自动滚动',
    term_autowrap: '自动换行',
    term_dashboard: '交互操控',
    term_modbus: 'Modbus',
    term_cmd_group: '命令组',
    term_auto_reply: '自动应答',
    term_waveform: '波形曲线',
    term_ing_flasher: 'ING 烧录',
    term_clear: '清屏',
    term_send: '发送',
    term_open: '打开',
    term_close: '关闭',
    term_flashing: '烧录中',
    term_reset: '复位',
    term_boot: 'BOOT',
    term_quick_cmds: '快捷指令',
    term_manage_groups: '管理命令组',
    term_collapse_drawer: '隐藏抽屉',
    term_input_placeholder_str: '输入发送指令，回车直接发送...',
    term_input_placeholder_hex: '输入HEX字节，如: 01 03 00 00 00 02 C4 0B',
    term_copy_all: '复制全部',
    term_export_log: '导出日志',
    term_chk_none: '校验: 无',
    term_chk_modbus: '校验: Modbus CRC16 (低位在前)',
    term_chk_crc16: '校验: CRC16-CCITT / XModem',
    term_chk_sum8: '校验: Checksum-8 (累加和)',
    term_chk_xor8: '校验: XOR-8 (异或和)',
  },
  en: {
    // Top Brand & Nav
    app_title: 'AI-HIL Debugger',
    hardware_online: 'Hardware Online',
    waiting_hardware: 'Waiting for Hardware',
    ports_connected: 'port(s) connected',
    active_sessions_online: 'Sessions Online',
    no_active_conn: 'No Active Connections',
    ram_usage: 'RAM',
    memory_strict_budget: 'Idle RAM: < 100MB strictly budgeted',
    hardware_scheduler_ok: 'Hardware Scheduler Running',
    browser_mode_notice: 'Currently in Web Browser Preview Mode (Mock Data). For physical hardware (DAPLink / COM / SWD), launch the desktop app.',
    pin_management_notice: 'Multiple serial ports & hardware pins (DTR/RTS/Reset) are independently managed by tabs',

    // Main Navigation Tabs
    tab_terminal: 'Serial Terminal',
    tab_plotter: 'Waveform Plotter',
    tab_flasher: 'SWD Flasher',
    tab_merger: 'HEX/BIN Merger',
    tab_analyzer: 'Resource Analyzer',
    tab_svd: 'SVD Registers',
    tab_rtos: 'RTOS Trace',
    tab_lcd: 'LCD Mirror',
    tab_hardfault: 'HardFault Diagnostics',
    tab_memory: 'Memory & Dump',
    tab_ai: 'AI HIL Copilot (MCP)',

    // Floating Toolbar
    toolbar_toggle_expand: 'Expand Quick Toolbar',
    toolbar_toggle_collapse: 'Collapse Quick Toolbar',
    toolbar_settings: 'Settings',
    toolbar_theme: 'Theme',
    toolbar_screenshot: 'Capture',
    toolbar_screenshot_saved: 'Saved',
    toolbar_screenshot_success: 'Screenshot captured and saved!',

    // Settings Modal
    settings_title: 'Settings & Preferences',
    settings_appearance: 'Appearance & Theme',
    settings_mode_label: 'Display Mode',
    settings_mode_dark: 'Dark Mode',
    settings_mode_light: 'Light Mode',
    settings_theme_preset: 'Theme Presets & Palette',
    settings_language: 'Language',
    settings_typography: 'Typography & Fonts',
    settings_font_family: 'UI & Monospace Font',
    settings_font_size: 'Global Font Scaling',
    settings_reset: 'Reset to Defaults',
    settings_close: 'Done & Close',

    // Theme Presets
    theme_dark_slate: 'Cyberpunk Slate',
    theme_dark_navy: 'Midnight Navy',
    theme_dark_forest: 'Matrix Emerald',
    theme_dark_crimson: 'Obsidian Crimson',
    theme_dark_purple: 'Cyberpunk Purple',
    theme_light_white: 'Crisp Porcelain',
    theme_light_warm: 'Warm Parchment',
    theme_light_ice: 'Glacier Slate',
    theme_light_sakura: 'Blossom Mist',

    // Serial Terminal
    term_no_ports_open: 'No active serial ports',
    term_open_new_port: 'Open Port',
    term_concurrent_conns: 'Concurrent Connections',
    term_ready_desc: 'Hardware terminal ready. Click [Open Port] above to add serial ports, DAPLink or RTT channels.',
    term_log_stream: 'Log Stream',
    term_vt100: 'VT100 Terminal',
    term_ascii: 'ASCII',
    term_hex: 'HEX',
    term_timestamps: 'Timestamp',
    term_autoscroll: 'Auto Scroll',
    term_autowrap: 'Auto Wrap',
    term_dashboard: 'Controls',
    term_modbus: 'Modbus',
    term_cmd_group: 'Cmd Groups',
    term_auto_reply: 'Auto Reply',
    term_waveform: 'Waveform',
    term_ing_flasher: 'ING Flash',
    term_clear: 'Clear',
    term_send: 'Send',
    term_open: 'Open',
    term_close: 'Close',
    term_flashing: 'Flashing',
    term_reset: 'Reset',
    term_boot: 'BOOT',
    term_quick_cmds: 'Quick Commands',
    term_manage_groups: 'Manage Groups',
    term_collapse_drawer: 'Collapse',
    term_input_placeholder_str: 'Enter command, press Enter to send...',
    term_input_placeholder_hex: 'Enter HEX bytes, e.g.: 01 03 00 00 00 02 C4 0B',
    term_copy_all: 'Copy All',
    term_export_log: 'Export Log',
    term_chk_none: 'Checksum: None',
    term_chk_modbus: 'Checksum: Modbus CRC16',
    term_chk_crc16: 'Checksum: CRC16-CCITT',
    term_chk_sum8: 'Checksum: Checksum-8',
    term_chk_xor8: 'Checksum: XOR-8',
  }
};

export function t(key: string): string {
  const dict = messages[currentLocale.value] || messages.zh;
  return dict[key] || key;
}
