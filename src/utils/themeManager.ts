import { ref } from 'vue';

export type ThemeMode = 'dark' | 'light';

export type ThemeId = 
  | 'dark-slate' 
  | 'dark-navy' 
  | 'dark-forest'
  | 'dark-crimson'
  | 'dark-purple'
  | 'light-white' 
  | 'light-warm' 
  | 'light-ice'
  | 'light-sakura';

export interface ThemeOption {
  id: ThemeId;
  nameKey: string;
  mode: ThemeMode;
  accentColor: string;
  bgColor: string;
  cardColor: string;
  tagColor: string;
}

export const THEME_PRESETS: ThemeOption[] = [
  // --- Dark Themes ---
  {
    id: 'dark-slate',
    nameKey: 'theme_dark_slate',
    mode: 'dark',
    accentColor: '#10b981', // Emerald
    bgColor: '#09090b',
    cardColor: '#141417',
    tagColor: '#27272a',
  },
  {
    id: 'dark-navy',
    nameKey: 'theme_dark_navy',
    mode: 'dark',
    accentColor: '#38bdf8', // Sky Blue
    bgColor: '#060d17',
    cardColor: '#0b1626',
    tagColor: '#17253b',
  },
  {
    id: 'dark-forest',
    nameKey: 'theme_dark_forest',
    mode: 'dark',
    accentColor: '#4ade80', // Mint Green
    bgColor: '#051109',
    cardColor: '#091c10',
    tagColor: '#12331f',
  },
  {
    id: 'dark-crimson',
    nameKey: 'theme_dark_crimson',
    mode: 'dark',
    accentColor: '#f43f5e', // Rose
    bgColor: '#12070a',
    cardColor: '#1c0c11',
    tagColor: '#36141e',
  },
  {
    id: 'dark-purple',
    nameKey: 'theme_dark_purple',
    mode: 'dark',
    accentColor: '#c084fc', // Purple Neon
    bgColor: '#0c0714',
    cardColor: '#150d21',
    tagColor: '#2a1a42',
  },

  // --- Light Themes (Modern, clean, and elegant) ---
  {
    id: 'light-white',
    nameKey: 'theme_light_white',
    mode: 'light',
    accentColor: '#059669', // Emerald Teal
    bgColor: '#f4f6f8',
    cardColor: '#ffffff',
    tagColor: '#e2e8f0',
  },
  {
    id: 'light-warm',
    nameKey: 'theme_light_warm',
    mode: 'light',
    accentColor: '#d97706', // Amber Amber
    bgColor: '#fbf9f4',
    cardColor: '#ffffff',
    tagColor: '#faeedb',
  },
  {
    id: 'light-ice',
    nameKey: 'theme_light_ice',
    mode: 'light',
    accentColor: '#0284c7', // Cyan Blue
    bgColor: '#eef3f8',
    cardColor: '#ffffff',
    tagColor: '#dbeafe',
  },
  {
    id: 'light-sakura',
    nameKey: 'theme_light_sakura',
    mode: 'light',
    accentColor: '#e11d48', // Sakura Pink
    bgColor: '#faf3f5',
    cardColor: '#ffffff',
    tagColor: '#ffe4e6',
  },
];

export const FONT_PRESETS = [
  { id: 'default', label: '系统原生推荐 (System Default)', family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif' },
  { id: 'jetbrains', label: 'JetBrains Mono (开发者最爱)', family: '"JetBrains Mono", Consolas, "Courier New", monospace' },
  { id: 'firacode', label: 'Fira Code (连字特性)', family: '"Fira Code", Consolas, monospace' },
  { id: 'cascadia', label: 'Cascadia Code (微软现代等宽)', family: '"Cascadia Code", Consolas, monospace' },
  { id: 'consolas', label: 'Consolas (经典工业标准)', family: 'Consolas, monospace' },
];

const STORAGE_THEME_ID = 'ai_hil_theme_id';
const STORAGE_FONT_FAMILY = 'ai_hil_font_family';
const STORAGE_FONT_SIZE = 'ai_hil_font_size';

export const currentThemeId = ref<ThemeId>(
  (localStorage.getItem(STORAGE_THEME_ID) as ThemeId) || 'dark-slate'
);

export const currentFontFamily = ref<string>(
  localStorage.getItem(STORAGE_FONT_FAMILY) || 'default'
);

export const currentFontSize = ref<number>(
  Number(localStorage.getItem(STORAGE_FONT_SIZE)) || 13
);

export function applyTheme(themeId: ThemeId) {
  currentThemeId.value = themeId;
  localStorage.setItem(STORAGE_THEME_ID, themeId);
  const theme = THEME_PRESETS.find(t => t.id === themeId) || THEME_PRESETS[0];

  const root = document.documentElement;
  root.setAttribute('data-theme', theme.id);
  root.setAttribute('data-mode', theme.mode);
  
  if (theme.mode === 'light') {
    root.classList.add('light-mode');
    root.classList.remove('dark-mode');
  } else {
    root.classList.add('dark-mode');
    root.classList.remove('light-mode');
  }
}

export function setMode(mode: ThemeMode) {
  const current = THEME_PRESETS.find(t => t.id === currentThemeId.value);
  if (current && current.mode === mode) return;

  const next = THEME_PRESETS.find(t => t.mode === mode);
  if (next) {
    applyTheme(next.id);
  }
}

export function cycleNextTheme() {
  const currentIndex = THEME_PRESETS.findIndex(t => t.id === currentThemeId.value);
  const nextIndex = (currentIndex + 1) % THEME_PRESETS.length;
  applyTheme(THEME_PRESETS[nextIndex].id);
}

export function applyFontFamily(fontId: string) {
  currentFontFamily.value = fontId;
  localStorage.setItem(STORAGE_FONT_FAMILY, fontId);
  const preset = FONT_PRESETS.find(f => f.id === fontId);
  if (preset) {
    document.documentElement.style.setProperty('--app-font-family', preset.family);
  }
}

export function applyFontSize(size: number) {
  currentFontSize.value = size;
  localStorage.setItem(STORAGE_FONT_SIZE, String(size));
  document.documentElement.style.setProperty('--app-font-size', `${size}px`);
}

export function initTheme() {
  applyTheme(currentThemeId.value);
  applyFontFamily(currentFontFamily.value);
  applyFontSize(currentFontSize.value);
}
