import { ref } from 'vue';

export type ThemeMode = 'dark' | 'light';
export type ThemeId = 
  | 'dark-slate' 
  | 'dark-navy' 
  | 'dark-forest'
  | 'light-white' 
  | 'light-warm' 
  | 'light-ice';

export interface ThemeOption {
  id: ThemeId;
  nameKey: string;
  mode: ThemeMode;
  accentColor: string;
  bgColor: string;
}

export const THEME_PRESETS: ThemeOption[] = [
  {
    id: 'dark-slate',
    nameKey: 'theme_default_dark',
    mode: 'dark',
    accentColor: '#10b981',
    bgColor: '#09090b',
  },
  {
    id: 'dark-navy',
    nameKey: 'theme_ocean_dark',
    mode: 'dark',
    accentColor: '#38bdf8',
    bgColor: '#070d19',
  },
  {
    id: 'dark-forest',
    nameKey: 'theme_forest_dark',
    mode: 'dark',
    accentColor: '#4ade80',
    bgColor: '#08120c',
  },
  {
    id: 'light-white',
    nameKey: 'theme_pure_light',
    mode: 'light',
    accentColor: '#059669',
    bgColor: '#f8fafc',
  },
  {
    id: 'light-warm',
    nameKey: 'theme_warm_light',
    mode: 'light',
    accentColor: '#d97706',
    bgColor: '#fdfbf7',
  },
  {
    id: 'light-ice',
    nameKey: 'theme_ice_light',
    mode: 'light',
    accentColor: '#0284c7',
    bgColor: '#f0f4f8',
  },
];

export const FONT_PRESETS = [
  { id: 'default', label: '系统默认 (System Default)', family: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif' },
  { id: 'jetbrains', label: 'JetBrains Mono', family: '"JetBrains Mono", Consolas, monospace' },
  { id: 'firacode', label: 'Fira Code', family: '"Fira Code", Consolas, monospace' },
  { id: 'cascadia', label: 'Cascadia Code / Consolas', family: '"Cascadia Code", Consolas, "Courier New", monospace' },
  { id: 'consolas', label: 'Consolas (经典等宽)', family: 'Consolas, monospace' },
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
  // If current theme matches the mode, keep it; otherwise switch to first preset of that mode
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
