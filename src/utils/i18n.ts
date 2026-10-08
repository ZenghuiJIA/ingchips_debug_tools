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
    // Header & Workspace
    app_title: 'AI-HIL Debugger',
    hardware_online: '硬件在线',
    waiting_hardware: '等待连接硬件',
    ports_connected: '个端口已连接',
    ram_usage: 'RAM',
    tab_terminal: '串口高速监控',
    tab_plotter: '实时波形示波器',
    tab_flasher: '固件在线烧录',
    tab_merger: '固件文件合并',
    tab_analyzer: '固件资源开销分析',
    tab_svd: '外设寄存器 (SVD)',
    tab_rtos: 'RTOS 任务追踪',
    tab_lcd: '屏幕画面回传',
    tab_hardfault: 'HardFault 智能诊断',
    tab_memory: '内存直接读写',
    tab_ai: 'AI 固件助手',
    
    // Floating Toolbar
    toolbar_toggle_expand: '展开快捷工具栏',
    toolbar_toggle_collapse: '收起快捷工具栏',
    toolbar_settings: '系统设置',
    toolbar_theme: '切换皮肤',
    toolbar_screenshot: '屏幕截图',
    toolbar_screenshot_success: '截屏已成功保存或复制！',

    // Settings Modal
    settings_title: '应用设置与偏好',
    settings_appearance: '皮肤与外观',
    settings_mode_label: '显示模式',
    settings_mode_dark: '深色模式',
    settings_mode_light: '浅色模式',
    settings_theme_preset: '皮肤配色预设',
    settings_language: '语言 (Language)',
    settings_language_desc: '选择界面显示语言',
    settings_typography: '字体与排版',
    settings_font_family: '代码与界面字体',
    settings_font_size: '全局字体大小',
    settings_font_default: '系统默认字体',
    settings_reset: '恢复默认设置',
    settings_close: '关闭',
    settings_saved: '设置已自动保存',

    // Themes
    theme_default_dark: '极客黑 (Cyberpunk Slate)',
    theme_ocean_dark: '暗夜深蓝 (Midnight Navy)',
    theme_forest_dark: '极光暗绿 (Forest Matrix)',
    theme_pure_light: '现代亮白 (Crisp White)',
    theme_warm_light: '护眼暖光 (Warm Parchment)',
    theme_ice_light: '极简冰蓝 (Ice Slate)',
  },
  en: {
    // Header & Workspace
    app_title: 'AI-HIL Debugger',
    hardware_online: 'Hardware Online',
    waiting_hardware: 'Waiting for Hardware',
    ports_connected: 'port(s) connected',
    ram_usage: 'RAM',
    tab_terminal: 'Serial Terminal',
    tab_plotter: 'Waveform Plotter',
    tab_flasher: 'Firmware Flasher',
    tab_merger: 'Firmware Merger',
    tab_analyzer: 'Resource Analyzer',
    tab_svd: 'Peripherals (SVD)',
    tab_rtos: 'RTOS Tracer',
    tab_lcd: 'LCD Mirror',
    tab_hardfault: 'HardFault Diagnostics',
    tab_memory: 'Memory Inspector',
    tab_ai: 'AI Copilot',

    // Floating Toolbar
    toolbar_toggle_expand: 'Expand Quick Toolbar',
    toolbar_toggle_collapse: 'Collapse Quick Toolbar',
    toolbar_settings: 'Settings',
    toolbar_theme: 'Switch Theme',
    toolbar_screenshot: 'Take Screenshot',
    toolbar_screenshot_success: 'Screenshot captured successfully!',

    // Settings Modal
    settings_title: 'Settings & Preferences',
    settings_appearance: 'Appearance & Theme',
    settings_mode_label: 'Color Mode',
    settings_mode_dark: 'Dark Mode',
    settings_mode_light: 'Light Mode',
    settings_theme_preset: 'Theme Color Presets',
    settings_language: 'Language',
    settings_language_desc: 'Select application display language',
    settings_typography: 'Typography & Fonts',
    settings_font_family: 'UI & Code Font Family',
    settings_font_size: 'Global Font Size',
    settings_font_default: 'System Default Font',
    settings_reset: 'Reset Defaults',
    settings_close: 'Close',
    settings_saved: 'Settings automatically saved',

    // Themes
    theme_default_dark: 'Cyberpunk Slate',
    theme_ocean_dark: 'Midnight Navy',
    theme_forest_dark: 'Forest Matrix',
    theme_pure_light: 'Crisp White',
    theme_warm_light: 'Warm Parchment',
    theme_ice_light: 'Ice Slate',
  }
};

export function t(key: string): string {
  const dict = messages[currentLocale.value] || messages.zh;
  return dict[key] || key;
}
