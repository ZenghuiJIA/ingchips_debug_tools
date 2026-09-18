<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { safeInvoke } from '../utils/ipc';
import type { PortInfo, SystemMetrics } from '../types';
import {
  Cpu,
  RefreshCw,
  Power,
  RotateCcw,
  Zap,
  Activity,
  CheckCircle2,
  AlertCircle
} from '@lucide/vue';

const props = defineProps<{
  isConnected: boolean;
  activePort: string | null;
}>();

const emit = defineEmits<{
  (e: 'connect', port: string, baudRate: number): void;
  (e: 'disconnect'): void;
  (e: 'resetTriggered', seq: string): void;
}>();

const ports = ref<PortInfo[]>([]);
const selectedPort = ref<string>('');
const selectedBaud = ref<number>(115200);
const baudRates = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600];

const dtrState = ref<boolean>(false);
const rtsState = ref<boolean>(false);
const isRefreshing = ref<boolean>(false);
const isResetting = ref<boolean>(false);

const currentPortInfo = computed(() => {
  const target = props.isConnected ? props.activePort : selectedPort.value;
  return ports.value.find(p => p.port_name === target);
});

const isDaplinkDevice = computed(() => {
  return currentPortInfo.value?.is_daplink ?? false;
});

const canHardwareReset = computed(() => {
  return props.isConnected && isDaplinkDevice.value;
});

const resetTooltipText = computed(() => {
  if (!props.isConnected) {
    return '请先连接 DAPLink 串口以使用硬件复位';
  }
  if (!isDaplinkDevice.value) {
    return '当前串口设备不是 DAPLink 探针，不支持硬件引脚复位 (仅 DAPLink 具备 RTS/DTR 硬件引脚控制)';
  }
  return '';
});

function getPortBadge(p: PortInfo) {
  if (p.device_type === 'rtt_jlink') {
    return '🚀 [SEGGER RTT]';
  }
  if (p.device_type === 'rtt_daplink') {
    return '🛰️ [DAPLink RTT]';
  }
  if (p.device_type === 'daplink' || p.is_daplink) {
    return '⚡ [DAPLink]';
  }
  if (p.device_type === 'jlink') {
    return '🔗 [J-Link CDC]';
  }
  return '🔌 [通用串口]';
}

const metrics = ref<SystemMetrics>({
  tauri_rss_mb: 0,
  daemon_rss_mb: 0,
  total_rss_mb: 0,
  memory_budget_mb: 100,
  is_under_budget: true,
  os_name: 'windows',
  target_arch: 'x86_64'
});

let metricsTimer: any = null;

async function refreshPorts() {
  isRefreshing.value = true;
  try {
    const list: PortInfo[] = await safeInvoke('list_serial_ports');
    ports.value = list;
    
    // Auto-select DAPLink if available, otherwise first port
    const daplink = list.find(p => p.is_daplink);
    if (daplink) {
      selectedPort.value = daplink.port_name;
    } else if (list.length > 0 && !selectedPort.value) {
      selectedPort.value = list[0].port_name;
    }
  } catch (err) {
    console.error('Failed to list ports:', err);
  } finally {
    isRefreshing.value = false;
  }
}

async function refreshMetrics() {
  try {
    const m: SystemMetrics = await safeInvoke('get_system_metrics');
    metrics.value = m;
  } catch (err) {
    console.error('Failed to fetch metrics:', err);
  }
}

function handleToggleConnect() {
  if (props.isConnected) {
    emit('disconnect');
  } else {
    if (!selectedPort.value) return;
    emit('connect', selectedPort.value, Number(selectedBaud.value));
  }
}

async function toggleDtr() {
  const next = !dtrState.value;
  try {
    await safeInvoke('set_dtr', { level: next });
    dtrState.value = next;
  } catch (err) {
    console.error('Toggle DTR failed:', err);
  }
}

async function toggleRts() {
  const next = !rtsState.value;
  try {
    await safeInvoke('set_rts', { level: next });
    rtsState.value = next;
  } catch (err) {
    console.error('Toggle RTS failed:', err);
  }
}

async function triggerReset(seqType: string) {
  if (!canHardwareReset.value) {
    alert(resetTooltipText.value || '当前设备不支持硬件复位');
    return;
  }
  isResetting.value = true;
  try {
    await safeInvoke('execute_reset_sequence', { seqType });
    emit('resetTriggered', seqType);
    // Refresh pin states
    const [_, __, dtr, rts]: [boolean, string | null, boolean, boolean, boolean] = await safeInvoke('get_serial_status');
    dtrState.value = dtr;
    rtsState.value = rts;
  } catch (err) {
    console.error('Reset sequence failed:', err);
    alert(`复位执行失败: ${err}`);
  } finally {
    isResetting.value = false;
  }
}

onMounted(() => {
  refreshPorts();
  refreshMetrics();
  metricsTimer = setInterval(refreshMetrics, 2000);
});

onUnmounted(() => {
  if (metricsTimer) clearInterval(metricsTimer);
});
</script>

<template>
  <header class="bg-zinc-900 border-b border-zinc-800 px-4 py-2.5 flex items-center justify-between gap-4 select-none">
    <!-- Brand & Status -->
    <div class="flex items-center gap-3">
      <div class="flex items-center gap-2">
        <div class="h-8 w-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 font-bold shadow-inner">
          <Cpu class="w-5 h-5" />
        </div>
        <div>
          <div class="flex items-center gap-1.5">
            <span class="font-bold text-sm tracking-wide text-zinc-100">AI-HIL Debugger</span>
            <span class="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-zinc-800 text-zinc-400 border border-zinc-700">Tauri v2</span>
          </div>
          <div class="text-[11px] text-zinc-400 flex items-center gap-1">
            <span class="inline-block w-1.5 h-1.5 rounded-full" :class="isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-600'"></span>
            <span>{{ isConnected ? `已连接 (${activePort} · ${isDaplinkDevice ? 'DAPLink' : currentPortInfo?.device_type === 'jlink' ? 'J-Link CDC' : '通用串口'})` : '等待连接硬件' }}</span>
          </div>
        </div>
      </div>

      <!-- Live Memory Budget Monitor (< 100MB constraint) -->
      <div class="hidden lg:flex items-center gap-2 pl-3 border-l border-zinc-800">
        <div class="flex items-center gap-1.5 px-2.5 py-1 rounded bg-zinc-950 border border-zinc-800 text-xs font-mono">
          <Activity class="w-3.5 h-3.5" :class="metrics.is_under_budget ? 'text-emerald-400' : 'text-amber-400'" />
          <span class="text-zinc-400">RAM:</span>
          <span :class="metrics.is_under_budget ? 'text-emerald-300 font-semibold' : 'text-amber-300 font-semibold'">
            {{ metrics.total_rss_mb }} MB
          </span>
          <span class="text-zinc-500 text-[10px]">/ 100MB</span>
          <CheckCircle2 v-if="metrics.is_under_budget" class="w-3 h-3 text-emerald-500" />
          <AlertCircle v-else class="w-3 h-3 text-amber-500" />
        </div>
      </div>
    </div>

    <!-- Center: Port & Baud Settings -->
    <div class="flex items-center gap-2">
      <!-- Port Selector -->
      <div class="flex items-center rounded-md bg-zinc-950 border border-zinc-800 p-0.5">
        <select
          v-model="selectedPort"
          class="bg-transparent text-xs text-zinc-200 py-1 px-2.5 outline-none cursor-pointer max-w-[220px]"
          :disabled="isConnected"
        >
          <option v-if="ports.length === 0" value="">未检测到串口</option>
          <option v-for="p in ports" :key="p.port_name" :value="p.port_name" class="bg-zinc-900 text-zinc-200">
            {{ p.port_name }} {{ getPortBadge(p) }} ({{ p.description }})
          </option>
        </select>
        
        <button
          @click="refreshPorts"
          title="刷新端口列表"
          class="p-1 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded transition-colors"
          :disabled="isConnected || isRefreshing"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isRefreshing }" />
        </button>
      </div>

      <!-- Baud Rate Selector (Hidden if RTT) -->
      <select
        v-if="!selectedPort.startsWith('RTT')"
        v-model="selectedBaud"
        class="bg-zinc-950 border border-zinc-800 text-xs text-zinc-200 py-1.5 px-2.5 rounded-md outline-none cursor-pointer"
        :disabled="isConnected"
      >
        <option v-for="b in baudRates" :key="b" :value="b" class="bg-zinc-900 text-zinc-200">
          {{ b }} 波特率 {{ b === 921600 ? '⚡' : '' }}
        </option>
      </select>
      <div
        v-else
        class="px-2.5 py-1.5 rounded-md bg-purple-950/60 border border-purple-800/60 text-purple-300 text-xs font-mono font-semibold"
      >
        SWD 内存高速通道
      </div>

      <!-- Connect/Disconnect Button -->
      <button
        @click="handleToggleConnect"
        class="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all shadow-sm"
        :class="isConnected 
          ? 'bg-rose-500/10 text-rose-400 border border-rose-500/30 hover:bg-rose-500/20' 
          : 'bg-emerald-600 text-white hover:bg-emerald-500'"
      >
        <Power class="w-3.5 h-3.5" />
        <span>{{ isConnected ? '断开连接' : '打开串口' }}</span>
      </button>
    </div>

    <!-- Right: Hardware Pin Controls (RTS/DTR State Machine) -->
    <div class="flex items-center gap-2">
      <!-- Pin Status / Toggles -->
      <div class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded-md p-1">
        <!-- DTR Button: DTR 1 = RESET low, DTR 0 = release -->
        <button
          @click="toggleDtr"
          :disabled="!isConnected"
          title="DTR 控制 (RESET引脚: 1=拉低复位, 0=释放)"
          class="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono transition-colors"
          :class="dtrState ? 'bg-rose-950/80 text-rose-300 border border-rose-800' : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'"
        >
          <span class="w-2 h-2 rounded-full" :class="dtrState ? 'bg-rose-500 animate-pulse' : 'bg-emerald-500'"></span>
          <span>DTR(RST): {{ dtrState ? '1' : '0' }}</span>
        </button>

        <!-- RTS Button: RTS 1 = BOOT mode, RTS 0 = Normal mode -->
        <button
          @click="toggleRts"
          :disabled="!isConnected"
          title="RTS 控制 (BOOT引脚: 1=BOOT模式, 0=正常运行)"
          class="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-mono transition-colors"
          :class="rtsState ? 'bg-amber-950/80 text-amber-300 border border-amber-800' : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'"
        >
          <span class="w-2 h-2 rounded-full" :class="rtsState ? 'bg-amber-500 animate-pulse' : 'bg-emerald-500'"></span>
          <span>RTS(BOOT): {{ rtsState ? '1' : '0' }}</span>
        </button>
      </div>

      <!-- Hardware Action Buttons -->
      <div class="flex items-center gap-1.5">
        <span
          v-if="isConnected && !isDaplinkDevice"
          class="text-[10px] text-amber-400/90 bg-amber-950/40 border border-amber-800/40 px-1.5 py-0.5 rounded cursor-help"
          :title="resetTooltipText"
        >
          复位需DAPLink
        </span>

        <button
          @click="triggerReset('normal_reset')"
          :disabled="!canHardwareReset || isResetting"
          class="flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium border border-zinc-700 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          :title="!canHardwareReset ? resetTooltipText : '普通复位: RTS 0 (正常态) -> DTR 产生 100ms 复位脉冲'"
        >
          <RotateCcw class="w-3.5 h-3.5" :class="{ 'animate-spin': isResetting }" />
          <span>普通复位</span>
        </button>

        <button
          @click="triggerReset('bootloader_reset')"
          :disabled="!canHardwareReset || isResetting"
          class="flex items-center gap-1 px-2.5 py-1.5 rounded-md bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 text-xs font-medium border border-amber-500/40 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          :title="!canHardwareReset ? resetTooltipText : '引导复位: RTS 1 -> 延时 500ms 建立电平 -> DTR 产生 100ms 复位脉冲'"
        >
          <Zap class="w-3.5 h-3.5" />
          <span>进入 BOOT</span>
        </button>
      </div>
    </div>
  </header>
</template>
