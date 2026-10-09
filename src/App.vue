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
import HilTestSequencer from './components/HilTestSequencer.vue';
import BleRfHciConsole from './components/BleRfHciConsole.vue';
import McuProfiler from './components/McuProfiler.vue';
import RadixCalculator from './components/RadixCalculator.vue';
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
  Merge,
  Workflow,
  Radio,
  Gauge,
  Calculator,
  ChevronLeft,
  ChevronRight,
  LayoutGrid,
  Search,
  X
} from '@lucide/vue';

const activeSessionsCount = ref<number>(0);
const currentTab = ref<'terminal' | 'plotter' | 'flasher' | 'merger' | 'analyzer' | 'svd' | 'rtos' | 'lcd' | 'hardfault' | 'memory' | 'sequencer' | 'ble_rf' | 'profiler' | 'calculator' | 'ai'>('terminal');
const sharedFirmwarePath = ref<string>('');
const runningInBrowser = ref<boolean>(!isTauri());
const isSettingsOpen = ref<boolean>(false);
const isNavModalOpen = ref<boolean>(false);
const navFilterText = ref<string>('');
const tabsContainerRef = ref<HTMLElement | null>(null);

interface TabNavItem {
  id: 'terminal' | 'plotter' | 'flasher' | 'merger' | 'analyzer' | 'svd' | 'rtos' | 'lcd' | 'hardfault' | 'memory' | 'sequencer' | 'ble_rf' | 'profiler' | 'calculator' | 'ai';
  titleKey: string;
  icon: any;
  color: string;
  category: 'comm' | 'firmware' | 'swd' | 'tool';
  desc: string;
}

const tabNavCategories = [
  { id: 'comm', title: '通信与无线接口' },
  { id: 'firmware', title: '固件与系统分析' },
  { id: 'swd', title: 'SWD 硬件调试与诊断' },
  { id: 'tool', title: '自动化、工具与 AI' }
];

const allTabNavItems: TabNavItem[] = [
  { id: 'terminal', titleKey: 'tab_terminal', icon: Terminal, color: 'text-emerald-400', category: 'comm', desc: '串口、RTT 与网络调试终端' },
  { id: 'plotter', titleKey: 'tab_plotter', icon: Activity, color: 'text-cyan-400', category: 'comm', desc: '实时波形数据流可视化分析' },
  { id: 'ble_rf', titleKey: 'tab_ble_rf', icon: Radio, color: 'text-blue-400', category: 'comm', desc: 'BLE 射频测试 (DTM) 与 HCI 抓包' },
  { id: 'flasher', titleKey: 'tab_flasher', icon: Zap, color: 'text-amber-400', category: 'firmware', desc: '高速固件烧录与芯片擦除' },
  { id: 'merger', titleKey: 'tab_merger', icon: Merge, color: 'text-emerald-400', category: 'firmware', desc: '多固件 Bin/Hex 拼接与地址偏移合并' },
  { id: 'analyzer', titleKey: 'tab_analyzer', icon: PieChart, color: 'text-teal-400', category: 'firmware', desc: 'ELF / AXF 符号与 RAM/Flash 内存占用' },
  { id: 'svd', titleKey: 'tab_svd', icon: Sliders, color: 'text-indigo-400', category: 'swd', desc: '芯片外设寄存器与位域实时交互' },
  { id: 'rtos', titleKey: 'tab_rtos', icon: Cpu, color: 'text-purple-400', category: 'swd', desc: 'FreeRTOS / RT-Thread 内核状态与任务追踪' },
  { id: 'lcd', titleKey: 'tab_lcd', icon: Monitor, color: 'text-cyan-400', category: 'swd', desc: '屏幕显存实时镜像抓取与截图' },
  { id: 'hardfault', titleKey: 'tab_hardfault', icon: AlertOctagon, color: 'text-rose-400', category: 'swd', desc: 'Cortex-M 崩溃现场定位与智能诊断' },
  { id: 'memory', titleKey: 'tab_memory', icon: Database, color: 'text-emerald-400', category: 'swd', desc: 'RAM/Flash 内存直转储与 HEX 差异对比' },
  { id: 'profiler', titleKey: 'tab_profiler', icon: Gauge, color: 'text-amber-400', category: 'swd', desc: 'DWT 周期计数与函数耗时热点统计' },
  { id: 'sequencer', titleKey: 'tab_sequencer', icon: Workflow, color: 'text-blue-400', category: 'tool', desc: '自动化 HIL 硬件在环测试编排与断言' },
  { id: 'calculator', titleKey: 'tab_calculator', icon: Calculator, color: 'text-emerald-400', category: 'tool', desc: '2/8/10/16 快捷进制转换与位操作计算器' },
  { id: 'ai', titleKey: 'tab_ai', icon: Sparkles, color: 'text-fuchsia-400', category: 'tool', desc: '嵌入式大模型调试协同副驾驶' }
];

function selectTabFromNav(tabId: TabNavItem['id']) {
  currentTab.value = tabId;
  isNavModalOpen.value = false;
  navFilterText.value = '';
}

function scrollTabs(direction: 'left' | 'right') {
  if (!tabsContainerRef.value) return;
  const offset = direction === 'left' ? -220 : 220;
  tabsContainerRef.value.scrollBy({ left: offset, behavior: 'smooth' });
}

function handleTabsWheel(e: WheelEvent) {
  if (!tabsContainerRef.value) return;
  if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
    tabsContainerRef.value.scrollLeft += e.deltaY;
  }
}

function handleGlobalKeydown(e: KeyboardEvent) {
  // Ctrl+K / Cmd+K to open quick tabs navigation modal
  if ((e.ctrlKey || e.metaKey) && (e.key === 'k' || e.key === 'K')) {
    e.preventDefault();
    isNavModalOpen.value = !isNavModalOpen.value;
    return;
  }
  // Esc to close navigation modal
  if (e.key === 'Escape' && isNavModalOpen.value) {
    isNavModalOpen.value = false;
    return;
  }
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
      <!-- Tabs Bar with Scroll Controls -->
      <div class="bg-zinc-900/90 border-b border-zinc-800 px-2 flex items-center justify-between gap-1 select-none">
        <!-- Left Scroll Button -->
        <button
          @click="scrollTabs('left')"
          class="p-1.5 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/80 rounded-sm transition-colors shrink-0"
          title="向左翻页"
        >
          <ChevronLeft class="w-4 h-4" />
        </button>

        <!-- Horizontal Scrollable Tabs Container -->
        <div
          ref="tabsContainerRef"
          @wheel.passive="handleTabsWheel"
          class="flex-1 flex items-center gap-1 overflow-x-auto no-scrollbar scroll-smooth whitespace-nowrap"
        >
          <button
            @click="currentTab = 'terminal'"
            class="flex items-center gap-2 px-3.5 py-2.5 text-xs font-semibold border-b-2 transition-all shrink-0"
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
            @click="currentTab = 'sequencer'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'sequencer' 
              ? 'border-emerald-500 text-emerald-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Workflow class="w-3.5 h-3.5 text-emerald-400" />
            <span>{{ t('tab_sequencer') }}</span>
          </button>

          <button
            @click="currentTab = 'ble_rf'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'ble_rf' 
              ? 'border-blue-500 text-blue-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Radio class="w-3.5 h-3.5 text-blue-400" />
            <span>{{ t('tab_ble_rf') }}</span>
          </button>

          <button
            @click="currentTab = 'profiler'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'profiler' 
              ? 'border-amber-500 text-amber-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Gauge class="w-3.5 h-3.5 text-amber-400" />
            <span>{{ t('tab_profiler') }}</span>
          </button>

          <button
            @click="currentTab = 'calculator'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all shrink-0"
            :class="currentTab === 'calculator' 
              ? 'border-emerald-500 text-emerald-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Calculator class="w-3.5 h-3.5 text-emerald-400" />
            <span>{{ t('tab_calculator') }}</span>
          </button>

          <button
            @click="currentTab = 'ai'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all shrink-0"
            :class="currentTab === 'ai' 
              ? 'border-emerald-500 text-emerald-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Sparkles class="w-3.5 h-3.5 text-emerald-400" />
            <span>{{ t('tab_ai') }}</span>
          </button>
        </div>

        <!-- Right Scroll Button -->
        <button
          @click="scrollTabs('right')"
          class="p-1.5 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/80 rounded-sm transition-colors shrink-0"
          title="向右翻页"
        >
          <ChevronRight class="w-4 h-4" />
        </button>

        <!-- Quick Tabs Navigation Button (弹窗全功能菜单) -->
        <button
          @click="isNavModalOpen = true"
          class="flex items-center gap-1.5 px-2.5 py-1 text-xs font-semibold bg-zinc-800/90 hover:bg-zinc-700/90 text-cyan-400 hover:text-cyan-300 border border-zinc-700/70 rounded shrink-0 shadow-xs transition"
          title="功能标签快捷索引 (Ctrl + K)"
        >
          <LayoutGrid class="w-3.5 h-3.5" />
          <span class="hidden md:inline">功能导航</span>
          <kbd class="hidden lg:inline text-[9px] bg-zinc-900 border border-zinc-700 px-1 py-0.2 rounded text-zinc-400">Ctrl+K</kbd>
        </button>

        <div class="text-[11px] text-zinc-500 font-mono flex items-center gap-2 shrink-0 pr-2 pl-1 border-l border-zinc-800 hidden sm:flex">
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
              currentTab === 'sequencer' ? HilTestSequencer :
              currentTab === 'ble_rf' ? BleRfHciConsole :
              currentTab === 'profiler' ? McuProfiler :
              currentTab === 'calculator' ? RadixCalculator :
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

    <!-- Quick Navigation Modal (全功能标签快捷索引浮层) -->
    <div
      v-if="isNavModalOpen"
      class="fixed inset-0 z-50 bg-black/75 backdrop-blur-xs flex items-center justify-center p-4"
      @click.self="isNavModalOpen = false"
    >
      <div class="bg-zinc-900 border border-zinc-700/80 rounded-xl shadow-2xl w-full max-w-3xl overflow-hidden flex flex-col max-h-[85vh] animate-in fade-in zoom-in-95 duration-150">
        <!-- Modal Header with Search Filter -->
        <div class="p-4 border-b border-zinc-800 bg-zinc-950/60 flex items-center justify-between gap-3">
          <div class="flex items-center gap-2 text-cyan-400 font-bold text-sm">
            <LayoutGrid class="w-5 h-5" />
            <span>全功能快捷索引导航</span>
            <span class="text-xs font-normal text-zinc-500">({{ allTabNavItems.length }} 个调试功能)</span>
          </div>
          <div class="flex items-center gap-2 flex-1 max-w-sm">
            <div class="relative w-full flex items-center">
              <Search class="w-3.5 h-3.5 text-zinc-500 absolute left-2.5 pointer-events-none" />
              <input
                v-model="navFilterText"
                type="text"
                placeholder="搜索标签名称或功能描述..."
                class="w-full bg-zinc-900 border border-zinc-700 rounded-lg pl-8 pr-3 py-1 text-xs text-zinc-200 outline-none focus:border-cyan-500"
                autofocus
              />
            </div>
          </div>
          <button
            @click="isNavModalOpen = false"
            class="text-zinc-400 hover:text-zinc-200 p-1 rounded hover:bg-zinc-800 transition"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <!-- Categorized Grid of Tabs -->
        <div class="p-4 overflow-y-auto space-y-5">
          <div
            v-for="cat in tabNavCategories"
            :key="cat.id"
            class="space-y-2"
            v-show="allTabNavItems.filter(item => item.category === cat.id && (!navFilterText.trim() || t(item.titleKey).toLowerCase().includes(navFilterText.toLowerCase()) || item.desc.toLowerCase().includes(navFilterText.toLowerCase()))).length > 0"
          >
            <div class="text-[11px] font-bold text-zinc-400 uppercase tracking-wider px-1 flex items-center gap-1.5">
              <span class="w-1.5 h-1.5 rounded-full bg-cyan-400"></span>
              <span>{{ cat.title }}</span>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-2.5">
              <button
                v-for="item in allTabNavItems.filter(item => item.category === cat.id && (!navFilterText.trim() || t(item.titleKey).toLowerCase().includes(navFilterText.toLowerCase()) || item.desc.toLowerCase().includes(navFilterText.toLowerCase())))"
                :key="item.id"
                @click="selectTabFromNav(item.id)"
                class="flex items-start gap-2.5 p-3 rounded-lg border text-left transition-all group"
                :class="currentTab === item.id 
                  ? 'bg-zinc-800/90 border-cyan-500/80 shadow-md ring-1 ring-cyan-500/30' 
                  : 'bg-zinc-950/60 border-zinc-800/80 hover:bg-zinc-850 hover:border-zinc-700'"
              >
                <div class="p-2 rounded bg-zinc-900 border border-zinc-800 shrink-0 group-hover:border-zinc-700" :class="item.color">
                  <component :is="item.icon" class="w-4 h-4" />
                </div>
                <div class="min-w-0 flex-1">
                  <div class="font-bold text-xs flex items-center justify-between" :class="currentTab === item.id ? 'text-cyan-300' : 'text-zinc-200 group-hover:text-cyan-400'">
                    <span>{{ t(item.titleKey) }}</span>
                    <span v-if="currentTab === item.id" class="text-[9px] px-1 py-0.2 bg-cyan-950 text-cyan-400 border border-cyan-800 rounded">当前</span>
                  </div>
                  <p class="text-[10.5px] text-zinc-400 mt-1 line-clamp-2 leading-relaxed">
                    {{ item.desc }}
                  </p>
                </div>
              </button>
            </div>
          </div>
        </div>

        <!-- Footer Hint -->
        <div class="px-4 py-2 border-t border-zinc-800 bg-zinc-950/40 text-[11px] text-zinc-500 flex items-center justify-between">
          <span>提示: 点击任意卡片立即切换对应功能界面</span>
          <div class="flex items-center gap-2">
            <span>支持快捷键</span>
            <kbd class="px-1.5 py-0.5 rounded bg-zinc-800 border border-zinc-700 text-zinc-300 text-[10px]">ESC</kbd>
            <span>退出</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
