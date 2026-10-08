<script setup lang="ts">
import { ref } from 'vue';
import {
  ChevronLeft,
  ChevronRight,
  Settings,
  Palette,
  Camera,
  Check
} from '@lucide/vue';
import { t } from '../utils/i18n';
import { cycleNextTheme } from '../utils/themeManager';
import { captureScreenshot } from '../utils/screenshot';

const emit = defineEmits<{
  (e: 'open-settings'): void;
}>();

const isExpanded = ref<boolean>(false);
const screenshotTaken = ref<boolean>(false);

function toggleToolbar() {
  isExpanded.value = !isExpanded.value;
}

function handleCycleTheme() {
  cycleNextTheme();
}

async function handleTakeScreenshot() {
  try {
    screenshotTaken.value = true;
    await captureScreenshot('app-root');
    setTimeout(() => {
      screenshotTaken.value = false;
    }, 2000);
  } catch (err) {
    console.error('Screenshot failed:', err);
    screenshotTaken.value = false;
  }
}
</script>

<template>
  <div class="fixed top-20 right-0 z-40 flex items-center select-none pointer-events-auto">
    <!-- Collapse / Expand Trigger Arrow Button -->
    <button
      @click="toggleToolbar"
      class="h-10 w-5 rounded-l-md bg-zinc-900 hover:bg-zinc-800 border-l border-t border-b border-zinc-700/80 text-zinc-400 hover:text-emerald-400 flex items-center justify-center shadow-lg transition-all cursor-pointer focus:outline-hidden"
      :title="isExpanded ? t('toolbar_toggle_collapse') : t('toolbar_toggle_expand')"
    >
      <ChevronRight v-if="isExpanded" class="w-3.5 h-3.5" />
      <ChevronLeft v-else class="w-3.5 h-3.5" />
    </button>

    <!-- Toolbar Action Buttons (Slide out smoothly) -->
    <div
      v-show="isExpanded"
      class="bg-zinc-900/95 border-l border-t border-b border-zinc-700/80 rounded-l-xl p-1.5 flex items-center gap-1 shadow-2xl backdrop-blur-md transition-all animate-in slide-in-from-right-5 duration-200"
    >
      <!-- 1. Settings Action -->
      <button
        @click="emit('open-settings')"
        class="flex flex-col items-center justify-center w-11 h-11 rounded-lg bg-zinc-800/80 hover:bg-zinc-700/80 text-zinc-300 hover:text-emerald-400 border border-zinc-700/60 hover:border-emerald-500/50 transition-all cursor-pointer group"
        :title="t('toolbar_settings')"
      >
        <Settings class="w-4 h-4 transition-transform group-hover:rotate-45 duration-300" />
        <span class="text-[9px] mt-0.5 font-medium leading-none">{{ t('toolbar_settings') }}</span>
      </button>

      <!-- 2. Theme / Skin Action -->
      <button
        @click="handleCycleTheme"
        class="flex flex-col items-center justify-center w-11 h-11 rounded-lg bg-zinc-800/80 hover:bg-zinc-700/80 text-zinc-300 hover:text-cyan-400 border border-zinc-700/60 hover:border-cyan-500/50 transition-all cursor-pointer group relative"
        :title="t('toolbar_theme')"
      >
        <Palette class="w-4 h-4 transition-transform group-hover:scale-110 duration-200" />
        <span class="text-[9px] mt-0.5 font-medium leading-none">{{ t('toolbar_theme') }}</span>
      </button>

      <!-- 3. Screenshot Action -->
      <button
        @click="handleTakeScreenshot"
        class="flex flex-col items-center justify-center w-11 h-11 rounded-lg transition-all cursor-pointer group"
        :class="screenshotTaken 
          ? 'bg-emerald-950 text-emerald-300 border border-emerald-600' 
          : 'bg-zinc-800/80 hover:bg-zinc-700/80 text-zinc-300 hover:text-amber-400 border border-zinc-700/60 hover:border-amber-500/50'"
        :title="screenshotTaken ? t('toolbar_screenshot_success') : t('toolbar_screenshot')"
      >
        <Check v-if="screenshotTaken" class="w-4 h-4 text-emerald-400 animate-bounce" />
        <Camera v-else class="w-4 h-4 transition-transform group-hover:scale-110 duration-200" />
        <span class="text-[9px] mt-0.5 font-medium leading-none">
          {{ screenshotTaken ? '已保存' : t('toolbar_screenshot') }}
        </span>
      </button>
    </div>
  </div>
</template>
