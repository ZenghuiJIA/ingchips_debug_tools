<script setup lang="ts">
import { ref } from 'vue';
import { safeInvoke, isTauri } from './utils/ipc';
import HeaderBar from './components/HeaderBar.vue';
import SerialTerminal from './components/SerialTerminal.vue';
import WaveformPlotter from './components/WaveformPlotter.vue';
import PyocdFlasher from './components/PyocdFlasher.vue';
import HardFaultInspector from './components/HardFaultInspector.vue';
import AiCopilot from './components/AiCopilot.vue';
import {
  Terminal,
  Activity,
  Zap,
  AlertOctagon,
  Sparkles,
  Info
} from '@lucide/vue';

const isConnected = ref<boolean>(false);
const activePort = ref<string | null>(null);
const currentTab = ref<'terminal' | 'plotter' | 'flasher' | 'hardfault' | 'ai'>('terminal');
const runningInBrowser = ref<boolean>(!isTauri());

async function handleConnect(port: string, baudRate: number) {
  try {
    await safeInvoke('open_serial_port', { portName: port, baudRate });
    isConnected.value = true;
    activePort.value = port;
  } catch (err: any) {
    alert(`打开串口失败: ${err}`);
  }
}

async function handleDisconnect() {
  try {
    await safeInvoke('close_serial_port');
    isConnected.value = false;
    activePort.value = null;
  } catch (err: any) {
    console.error('关闭串口失败:', err);
  }
}

function handleResetTriggered(seq: string) {
  console.log('Reset sequence executed:', seq);
}
</script>

<template>
  <div class="h-screen w-screen flex flex-col bg-zinc-950 text-zinc-100 overflow-hidden font-sans">
    <!-- Web Browser Notice if opened in Chrome/Edge instead of Tauri -->
    <div v-if="runningInBrowser" class="bg-amber-950/80 border-b border-amber-800 text-amber-300 px-4 py-1.5 flex items-center justify-between text-xs">
      <div class="flex items-center gap-2">
        <Info class="w-4 h-4 shrink-0" />
        <span>当前处于 <strong>Web 浏览器预览模式</strong> (模拟数据)。访问物理硬件 (DAPLink / COM / SWD) 请运行 <code>.\src-tauri\target\release\app.exe</code> 或 <code>pnpm tauri dev</code> 桌面客户端。</span>
      </div>
    </div>

    <!-- Top Navigation & Control Bar -->
    <HeaderBar
      :is-connected="isConnected"
      :active-port="activePort"
      @connect="handleConnect"
      @disconnect="handleDisconnect"
      @reset-triggered="handleResetTriggered"
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
            <span>串口高速监控</span>
          </button>

          <button
            @click="currentTab = 'plotter'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'plotter' 
              ? 'border-cyan-500 text-cyan-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Activity class="w-3.5 h-3.5 text-cyan-400" />
            <span>实时波形示波器</span>
          </button>

          <button
            @click="currentTab = 'flasher'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'flasher' 
              ? 'border-emerald-500 text-emerald-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Zap class="w-3.5 h-3.5" />
            <span>SWD 固件烧录</span>
          </button>

          <button
            @click="currentTab = 'hardfault'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'hardfault' 
              ? 'border-emerald-500 text-emerald-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <AlertOctagon class="w-3.5 h-3.5 text-rose-400" />
            <span>HardFault 寄存器诊断</span>
          </button>

          <button
            @click="currentTab = 'ai'"
            class="flex items-center gap-2 px-4 py-2.5 text-xs font-semibold border-b-2 transition-all"
            :class="currentTab === 'ai' 
              ? 'border-emerald-500 text-emerald-400 bg-zinc-800/40' 
              : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Sparkles class="w-3.5 h-3.5 text-emerald-400" />
            <span>AI 硬件在环助手 (MCP)</span>
          </button>
        </div>

        <div class="text-[11px] text-zinc-500 font-mono flex items-center gap-2">
          <span>空载内存: &lt; 100MB 严格受控</span>
        </div>
      </div>

      <!-- Tab Content Area -->
      <div class="flex-1 overflow-hidden relative">
        <KeepAlive>
          <component
            :is="
              currentTab === 'terminal' ? SerialTerminal :
              currentTab === 'plotter' ? WaveformPlotter :
              currentTab === 'flasher' ? PyocdFlasher :
              currentTab === 'hardfault' ? HardFaultInspector :
              AiCopilot
            "
            :is-connected="isConnected"
            @switch-tab="(t: any) => currentTab = t"
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
        <span class="text-emerald-500">● 硬件调度器正常运行</span>
      </div>
    </footer>
  </div>
</template>
