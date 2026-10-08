<template>
  <div v-if="isOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 animate-in fade-in duration-200">
    <div class="bg-zinc-900 border border-zinc-700/80 rounded-xl shadow-2xl w-full max-w-lg overflow-hidden flex flex-col max-h-[90vh]">
      <!-- Header -->
      <div class="flex items-center justify-between px-6 py-4 border-b border-zinc-800 bg-zinc-950/50">
        <div class="flex items-center gap-2.5">
          <div class="w-8 h-8 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
          </div>
          <div>
            <h3 class="text-sm font-semibold text-zinc-100">{{ t('settings_title') }}</h3>
            <p class="text-xs text-zinc-400">{{ t('settings_appearance') }}</p>
          </div>
        </div>
        <button
          @click="close"
          class="text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/80 p-1.5 rounded-lg transition-colors"
        >
          <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <!-- Content -->
      <div class="px-6 py-5 overflow-y-auto space-y-6 flex-1 text-xs">
        <!-- 1. 语言设置 -->
        <div class="space-y-2">
          <label class="block font-medium text-zinc-300">{{ t('settings_language') }}</label>
          <div class="grid grid-cols-2 gap-2">
            <button
              type="button"
              @click="changeLocale('zh')"
              class="flex items-center justify-center gap-2 py-2 px-3 rounded-lg border text-xs font-medium transition-all"
              :class="currentLocale === 'zh'
                ? 'bg-blue-600/20 border-blue-500 text-blue-300'
                : 'bg-zinc-800/50 border-zinc-700/60 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200'"
            >
              <span>🇨🇳</span>
              <span>简体中文 (Chinese)</span>
            </button>
            <button
              type="button"
              @click="changeLocale('en')"
              class="flex items-center justify-center gap-2 py-2 px-3 rounded-lg border text-xs font-medium transition-all"
              :class="currentLocale === 'en'
                ? 'bg-blue-600/20 border-blue-500 text-blue-300'
                : 'bg-zinc-800/50 border-zinc-700/60 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200'"
            >
              <span>🇺🇸</span>
              <span>English (US)</span>
            </button>
          </div>
        </div>

        <!-- 2. 显示模式与皮肤预设 -->
        <div class="space-y-3">
          <div class="flex items-center justify-between">
            <label class="block font-medium text-zinc-300">{{ t('settings_appearance') }}</label>
            <!-- 模式切换：深色 / 浅色 -->
            <div class="flex items-center bg-zinc-950/70 p-0.5 rounded-lg border border-zinc-800">
              <button
                type="button"
                @click="toggleMode('dark')"
                class="px-2.5 py-1 rounded text-[11px] font-medium transition-all flex items-center gap-1.5"
                :class="currentMode === 'dark' ? 'bg-blue-600 text-white shadow' : 'text-zinc-400 hover:text-zinc-200'"
              >
                <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
                </svg>
                <span>{{ t('settings_mode_dark') }}</span>
              </button>
              <button
                type="button"
                @click="toggleMode('light')"
                class="px-2.5 py-1 rounded text-[11px] font-medium transition-all flex items-center gap-1.5"
                :class="currentMode === 'light' ? 'bg-blue-600 text-white shadow' : 'text-zinc-400 hover:text-zinc-200'"
              >
                <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
                </svg>
                <span>{{ t('settings_mode_light') }}</span>
              </button>
            </div>
          </div>

          <!-- 皮肤预设网格 -->
          <div class="grid grid-cols-3 gap-2.5">
            <button
              v-for="preset in themePresets"
              :key="preset.id"
              type="button"
              @click="selectPreset(preset.id)"
              class="flex flex-col items-start p-2.5 rounded-lg border text-left transition-all relative overflow-hidden group"
              :class="currentThemeId === preset.id
                ? 'border-blue-500 ring-1 ring-blue-500 bg-zinc-800/80 shadow-md'
                : 'border-zinc-800 bg-zinc-950/40 hover:border-zinc-700 hover:bg-zinc-800/40'"
            >
              <div class="flex items-center gap-2 w-full mb-1.5">
                <div class="w-3.5 h-3.5 rounded-full border border-white/20 shadow-sm" :style="{ backgroundColor: preset.accentColor }"></div>
                <span class="font-medium text-[11px] text-zinc-200 truncate">{{ t(preset.nameKey) }}</span>
              </div>
              <span class="text-[10px] text-zinc-500 truncate w-full">
                {{ preset.mode === 'dark' ? t('settings_mode_dark') : t('settings_mode_light') }}
              </span>
              <div v-if="currentThemeId === preset.id" class="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-blue-500"></div>
            </button>
          </div>
        </div>

        <!-- 3. 字体选择 -->
        <div class="space-y-2">
          <label class="block font-medium text-zinc-300">{{ t('settings_font_family') }}</label>
          <div class="relative">
            <select
              :value="currentFontFamily"
              @change="onFontChange"
              class="w-full bg-zinc-950/70 border border-zinc-700 rounded-lg px-3 py-2 text-zinc-200 text-xs focus:outline-none focus:border-blue-500 transition-colors cursor-pointer appearance-none"
            >
              <option v-for="font in fontPresets" :key="font.id" :value="font.id">
                {{ font.label }}
              </option>
            </select>
            <div class="pointer-events-none absolute inset-y-0 right-0 flex items-center px-2 text-zinc-400">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
              </svg>
            </div>
          </div>
        </div>

        <!-- 4. 字体大小调节 -->
        <div class="space-y-2">
          <div class="flex items-center justify-between">
            <label class="font-medium text-zinc-300">{{ t('settings_font_size') }}</label>
            <span class="text-xs text-blue-400 font-mono font-semibold">{{ currentFontSize }}px</span>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-[11px] text-zinc-500">11px</span>
            <input
              type="range"
              min="11"
              max="18"
              step="1"
              :value="currentFontSize"
              @input="onFontSizeInput"
              class="flex-1 h-1.5 bg-zinc-800 rounded-lg appearance-none cursor-pointer accent-blue-500"
            />
            <span class="text-[11px] text-zinc-500">18px</span>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <div class="flex items-center justify-between px-6 py-3.5 border-t border-zinc-800 bg-zinc-950/50">
        <button
          type="button"
          @click="resetDefaults"
          class="text-xs text-zinc-400 hover:text-zinc-200 transition-colors underline decoration-dotted underline-offset-4"
        >
          {{ t('settings_reset') }}
        </button>
        <button
          type="button"
          @click="close"
          class="px-4 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-xs font-medium transition-colors shadow-sm"
        >
          {{ t('settings_close') }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import {
  currentThemeId,
  currentFontFamily,
  currentFontSize,
  THEME_PRESETS,
  FONT_PRESETS,
  applyTheme,
  setMode,
  applyFontFamily,
  applyFontSize,
  type ThemeId,
  type ThemeMode
} from '../utils/themeManager';
import { currentLocale, setLocale, t, type LocaleType } from '../utils/i18n';

defineProps<{
  isOpen: boolean;
}>();

const emit = defineEmits<{
  (e: 'close'): void;
}>();

const themePresets = THEME_PRESETS;
const fontPresets = FONT_PRESETS;

const currentMode = computed<ThemeMode>(() => {
  const t = THEME_PRESETS.find(p => p.id === currentThemeId.value);
  return t ? t.mode : 'dark';
});

function close() {
  emit('close');
}

function changeLocale(loc: LocaleType) {
  setLocale(loc);
}

function toggleMode(mode: ThemeMode) {
  setMode(mode);
}

function selectPreset(presetId: ThemeId) {
  applyTheme(presetId);
}

function onFontChange(event: Event) {
  const target = event.target as HTMLSelectElement;
  if (target) {
    applyFontFamily(target.value);
  }
}

function onFontSizeInput(event: Event) {
  const target = event.target as HTMLInputElement;
  if (target) {
    applyFontSize(Number(target.value));
  }
}

function resetDefaults() {
  applyTheme('dark-slate');
  applyFontFamily('default');
  applyFontSize(13);
  setLocale('zh');
}
</script>
