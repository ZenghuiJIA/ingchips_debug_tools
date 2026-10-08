<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import { isTauri } from './utils/ipc';
import { initTheme } from './utils/themeManager';
import HeaderBar from './components/HeaderBar.vue';
import SerialTerminal from './components/SerialTerminal.vue';
import WaveformPlotter from './components/WaveformPlotter.vue';
import PyocdFlasher from './components/PyocdFlasher.vue';
import HardFaultInspector from './components/HardFaultInspector.vue';
import MemoryInspector from './components/MemoryInspector.vue';
import FirmwareResourceAnalyzer from './components/FirmwareResourceAnalyzer.vue';
import SvdRegisterInspector from './components/SvdRegisterInspector.vue';
import RTOSTracer from './components/RTOSTracer.vue';
import LcdScreenMirror from './components/LcdScreenMirror.vue';
import FirmwareMerger from './components/FirmwareMerger.vue';
import AiCopilot from './components/AiCopilot.vue';
import CollapsibleToolbar from './components/CollapsibleToolbar.vue';
import GlobalSettingsModal from './components/GlobalSettingsModal.vue';
import { t } from './utils/i18n';
import {
  Terminal,
  Activity,
  Zap,
  PieChart,
  AlertOctagon,
  Database,
  Sparkles,
  Info,
  Sliders,
  Cpu,
  Monitor,
  Merge
} from '@lucide/vue';

const activeSessionsCount = ref<number>(0);
const currentTab = ref<'terminal' | 'plotter' | 'flasher' | 'merger' | 'analyzer' | 'svd' | 'rtos' | 'lcd' | 'hardfault' | 'memory' | 'ai'>('terminal');
const sharedFirmwarePath = ref<string>('');
const runningInBrowser = ref<boolean>(!isTauri());
const isSettingsOpen = ref<boolean>(false);

function handleGlobalKeydown(e: KeyboardEvent) {
  // Prevent F5 or Ctrl+R (Cmd+R on Mac) or Ctrl+Shift+R from accidentally reloading the debugging session
  if (
    e.key === 'F5' ||
    ((e.ctrlKey || e.metaKey) && (e.key === 'r' || e.key === 'R'))
  ) {
    e.preventDefault();
  }
}

function handleGlobalContextMenu(e: MouseEvent) {
  // Prevent native browser context menu from triggering page reload
  e.preventDefault();
}

onMounted(() => {
  initTheme();
  window.addEventListener('keydown', handleGlobalKeydown, true);
  window.addEventListener('contextmenu', handleGlobalContextMenu, true);
});

onUnmounted(() => {
  window.removeEventListener('keydown', handleGlobalKeydown, true);
  window.removeEventListener('contextmenu', handleGlobalContextMenu, true);
});
</script>

<template>
  <div id="app-root" class="h-screen w-screen flex flex-col bg-zinc-950 text-zinc-100 overflow-hidden font-sans relative" @contextmenu.prevent>
    <!-- Web Browser Notice if opened in Chrome/Edge instead of Tauri -->
    <div v-if="runningInBrowser" class="bg-amber-950/80 border-b border-amber-800 text-amber-300 px-4 py-1.5 flex items-center justify-between text-xs">
      <div class="flex items-center gap-2">
        <Info class="w-4 h-4 shrink-0" />
        <span>{{ t('browser_mode_notice') }}</span>
      </div>
    </div>

    <!-- Top Navigation & Control Bar -->
    <HeaderBar
      :active-sessions-count="activeSessionsCount"
    />

    <!-- Main Workspace with Tabs -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <!-- Tabs Bar -->
      <div class="bg-zinc-900/90 border-b border-zinc-800 px-4 flex items-center justify-between">
        <div class="flex items-center gap-1">
          <button
            @click="currentTab = 'terminal'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'terminal' 
              ? 'border-emerald-500 text-emerald-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Terminal class="w-3.5 h-3.5" />
            <span>{{ t('tab_terminal') }}</span>
          </button>

          <button
            @click="currentTab = 'plotter'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'plotter' 
              ? 'border-cyan-500 text-cyan-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Activity class="w-3.5 h-3.5 text-cyan-400" />
            <span>{{ t('tab_plotter') }}</span>
          </button>

          <button
            @click="currentTab = 'flasher'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'flasher' 
              ? 'border-emerald-500 text-emerald-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Zap class="w-3.5 h-3.5" />
            <span>{{ t('tab_flasher') }}</span>
          </button>

          <button
            @click="currentTab = 'merger'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'merger' 
              ? 'border-emerald-500 text-emerald-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Merge class="w-3.5 h-3.5 text-emerald-400" />
            <span>{{ t('tab_merger') }}</span>
          </button>

          <button
            @click="currentTab = 'analyzer'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'analyzer' 
              ? 'border-emerald-500 text-emerald-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <PieChart class="w-3.5 h-3.5 text-emerald-400" />
            <span>{{ t('tab_analyzer') }}</span>
          </button>

          <button
            @click="currentTab = 'svd'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'svd' 
              ? 'border-indigo-500 text-indigo-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Sliders class="w-3.5 h-3.5 text-indigo-400" />
            <span>{{ t('tab_svd') }}</span>
          </button>

          <button
            @click="currentTab = 'rtos'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'rtos' 
              ? 'border-purple-500 text-purple-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Cpu class="w-3.5 h-3.5 text-purple-400" />
            <span>{{ t('tab_rtos') }}</span>
          </button>

          <button
            @click="currentTab = 'lcd'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'lcd' 
              ? 'border-cyan-500 text-cyan-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Monitor class="w-3.5 h-3.5 text-cyan-400" />
            <span>{{ t('tab_lcd') }}</span>
          </button>

          <button
            @click="currentTab = 'hardfault'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'hardfault' 
              ? 'border-emerald-500 text-emerald-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <AlertOctagon class="w-3.5 h-3.5 text-rose-400" />
            <span>{{ t('tab_hardfault') }}</span>
          </button>

          <button
            @click="currentTab = 'memory'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'memory' 
              ? 'border-emerald-500 text-emerald-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Database class="w-3.5 h-3.5 text-emerald-400" />
            <span>{{ t('tab_memory') }}</span>
          </button>

          <button
            @click="currentTab = 'ai'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'ai' 
              ? 'border-emerald-500 text-emerald-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Sparkles class="w-3.5 h-3.5 text-emerald-400" />
            <span>{{ t('tab_ai') }}</span>
          </button>
        </div>

        <div class="text-[11px] text-zinc-500 font-mono flex items-center gap-2">
          <span>{{ t('memory_strict_budget') }}</span>
        </div>
      </div>

      <!-- Tab Content Area -->
      <div class="flex-1 overflow-hidden relative">
        <!-- Resource governance: Limit KeepAlive cache to 2 components. Heavy analysis tools (SVD/RTOS/HardFault/LCD) are released when leaving -->
        <KeepAlive :max="2">
          <component
            :is="
              currentTab === 'terminal' ? SerialTerminal :
              currentTab === 'plotter' ? WaveformPlotter :
              currentTab === 'flasher' ? PyocdFlasher :
              currentTab === 'merger' ? FirmwareMerger :
              currentTab === 'analyzer' ? FirmwareResourceAnalyzer :
              currentTab === 'svd' ? SvdRegisterInspector :
              currentTab === 'rtos' ? RTOSTracer :
              currentTab === 'lcd' ? LcdScreenMirror :
              currentTab === 'hardfault' ? HardFaultInspector :
              currentTab === 'memory' ? MemoryInspector :
              AiCopilot
            "
            :is-connected="activeSessionsCount > 0"
            :initial-file-path="sharedFirmwarePath"
            @update-active-count="(cnt: number) => activeSessionsCount = cnt"
            @switch-tab="(t: any, payload?: any) => {
              currentTab = t;
              if (payload && payload.filePath) sharedFirmwarePath = payload.filePath;
            }"
          />
        </KeepAlive>
      </div>
    </div>

    <!-- Bottom Global Status Footer -->
    <footer class="bg-zinc-900 border-t border-zinc-800 px-4 py-1 text-[11px] text-zinc-500 flex items-center justify-between font-mono">
      <div class="flex items-center gap-4">
        <span>Windows x86_64</span>
        <span>•</span>
        <span>PyOCD v0.45.1</span>
        <span>•</span>
        <span>MCP stdio RPC 2.0</span>
      </div>
      <div>
        <span class="text-emerald-500">● {{ t('hardware_scheduler_ok') }}</span>
      </div>
    </footer>

    <!-- Collapsible Float Toolbar (侧边贴靠抽屉式工具栏) -->
    <CollapsibleToolbar @open-settings="isSettingsOpen = true" />

    <!-- Global Settings & Theme Modal (设置 / 皮肤 / 语言 / 字体弹窗) -->
    <GlobalSettingsModal
      :is-open="isSettingsOpen"
      @close="isSettingsOpen = false"
    />
  </div>
</template>
