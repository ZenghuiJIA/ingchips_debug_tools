<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { safeInvoke } from '../utils/ipc';
import type { PortInfo, SystemMetrics, SvdDevice } from '../types';
import {
  Cpu,
  RefreshCw,
  Power,
  Activity,
  CheckCircle2,
  AlertCircle,
  Settings2,
  FolderArchive,
  X
} from '@lucide/vue';

const props = defineProps<{
  isConnected: boolean;
  activePort: string | null;
}>();

const emit = defineEmits<{
  (e: 'connect', port: string, baudRate: number, ramStart?: number, ramSize?: number, blockAddress?: number): void;
  (e: 'disconnect'): void;
  (e: 'resetTriggered', seq: string): void;
}>();

const ports = ref<PortInfo[]>([]);
const selectedPort = ref<string>('');
const selectedBaud = ref<number>(115200);
const baudRates = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600];

// RTT RAM Scan Range presets & custom address/size support
const rttRamPresets = [
  { label: 'SRAM 0x20000000 (128KB 常用M4/M3)', start: 0x20000000, size: 0x20000 },
  { label: 'SRAM 0x20000000 (64KB 常用M0/M3)', start: 0x20000000, size: 0x10000 },
  { label: 'SRAM 0x20000000 (256KB 大RAM)', start: 0x20000000, size: 0x40000 },
  { label: 'SRAM 0x20000000 (512KB 高性能M7/M4)', start: 0x20000000, size: 0x80000 },
  { label: 'DTCM 0x20000000 (128KB Cortex-M7)', start: 0x20000000, size: 0x20000 },
  { label: 'ITCM/RAM 0x00000000 (64KB Cortex-M0)', start: 0x00000000, size: 0x10000 },
  { label: 'AXI-SRAM 0x24000000 (512KB H7系列)', start: 0x24000000, size: 0x80000 },
  { label: '自定义 / Pack解析地址', start: -1, size: -1 },
];
const selectedRttRamPreset = ref<number>(0x20000000);
const selectedRttRamSize = ref<number>(0x20000);
const isCustomRttOpen = ref<boolean>(false);
const customRttStartHex = ref<string>('0x20000000');
const customRttSizeHex = ref<string>('0x20000');
const customRttBlockAddrHex = ref<string>(''); // Exact RTT Control Block address
const isImportingPack = ref<boolean>(false);
const importedPackInfo = ref<string>('');
const packDevices = ref<SvdDevice[]>([]);
const selectedPackDevice = ref<string>('');
const packDeviceSearch = ref<string>('');

const filteredPackDevices = computed(() => {
  if (!packDeviceSearch.value.trim()) return packDevices.value;
  const kw = packDeviceSearch.value.trim().toLowerCase();
  return packDevices.value.filter(d => d.name.toLowerCase().includes(kw));
});

const isRefreshing = ref<boolean>(false);

const currentPortInfo = computed(() => {
  const target = props.isConnected ? props.activePort : selectedPort.value;
  return ports.value.find(p => p.port_name === target);
});

const isDaplinkDevice = computed(() => {
  return currentPortInfo.value?.is_daplink ?? false;
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

async function importPackForRtt() {
  try {
    const selected: string | null = await safeInvoke('pick_pack_file', {
      title: '选择芯片 CMSIS-Pack 文件以解析默认 RAM / RTT 地址'
    });
    if (selected) {
      isImportingPack.value = true;
      const res: any = await safeInvoke('svd_import_pack', { packPath: selected });
      if (res && res.devices && res.devices.length > 0) {
        packDevices.value = res.devices;
        importedPackInfo.value = `${res.pack}: 成功解析到 ${res.devices.length} 个芯片型号`;
        // Select first device by default
        const dev = res.devices[0];
        selectedPackDevice.value = dev.name;
        applyDeviceRam(dev);
        selectedRttRamPreset.value = -1;
      }
    }
  } catch (err: any) {
    alert(`导入 Pack 解析失败: ${err}`);
  } finally {
    isImportingPack.value = false;
  }
}

function applyDeviceRam(dev: SvdDevice) {
  customRttStartHex.value = dev.ram_start || '0x20000000';
  const sizeVal = dev.ram_size || 0x20000;
  customRttSizeHex.value = `0x${sizeVal.toString(16).toUpperCase()}`;
}

function handlePackDeviceChange() {
  const found = packDevices.value.find(d => d.name === selectedPackDevice.value);
  if (found) {
    applyDeviceRam(found);
  }
}

function handleToggleConnect() {
  if (props.isConnected) {
    emit('disconnect');
  } else {
    if (!selectedPort.value) return;
    if (selectedPort.value.startsWith('RTT')) {
      let rStart = selectedRttRamPreset.value;
      let rSize = selectedRttRamSize.value;
      let bAddr: number | undefined = undefined;

      if (selectedRttRamPreset.value === -1 || isCustomRttOpen.value) {
        rStart = parseInt(customRttStartHex.value.trim(), 16);
        rSize = parseInt(customRttSizeHex.value.trim(), 16);
        if (customRttBlockAddrHex.value.trim()) {
          bAddr = parseInt(customRttBlockAddrHex.value.trim(), 16);
        }
      }

      emit('connect', selectedPort.value, Number(selectedBaud.value), rStart, rSize, bAddr);
    } else {
      emit('connect', selectedPort.value, Number(selectedBaud.value));
    }
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
        class="flex items-center gap-1.5"
      >
        <select
          v-model="selectedRttRamPreset"
          @change="(e: any) => {
            const val = Number(e.target.value);
            if (val === -1) {
              isCustomRttOpen = true;
            } else {
              const found = rttRamPresets.find(p => p.start === val);
              if (found) selectedRttRamSize = found.size;
            }
          }"
          class="bg-purple-950/70 border border-purple-800 text-xs text-purple-200 py-1.5 px-2.5 rounded-md outline-none cursor-pointer font-mono"
          :disabled="isConnected"
          title="SWD RTT 通道 RAM 扫描基地址与范围"
        >
          <option v-for="p in rttRamPresets" :key="p.label" :value="p.start" class="bg-zinc-900 text-zinc-200">
            ⚡ {{ p.label }}
          </option>
        </select>

        <!-- Custom RTT / Pack Button -->
        <button
          @click="isCustomRttOpen = !isCustomRttOpen"
          :disabled="isConnected"
          class="p-1.5 rounded-md bg-purple-950/80 hover:bg-purple-900 border border-purple-800 text-purple-300 transition-colors"
          title="自定义 RTT 扫描基地址、大小、指定 RTT 控制块，或导入外部 Pack 解析"
        >
          <Settings2 class="w-3.5 h-3.5" />
        </button>
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

    <!-- Right: System Info & Global Session Counter -->
    <div class="flex items-center gap-3">
      <div v-if="isConnected" class="flex items-center gap-2 bg-emerald-950/40 border border-emerald-800/40 px-2.5 py-1 rounded-md text-xs font-mono">
        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
        <span class="text-emerald-300">活跃串口: {{ activePort }}</span>
        <span v-if="isDaplinkDevice" class="text-[10px] bg-emerald-900/60 text-emerald-200 px-1 py-0.2 rounded border border-emerald-700/60">DAPLink</span>
      </div>

      <div class="text-[11px] text-zinc-500 font-sans hidden sm:flex items-center gap-1">
        <span>多串口与硬件引脚已在各标签页独立管理</span>
      </div>
    </div>
  </header>

  <!-- Custom RTT / CMSIS-Pack RAM Configuration Modal -->
  <div
    v-if="isCustomRttOpen"
    class="fixed inset-0 bg-black/75 backdrop-blur-xs z-50 flex items-center justify-center p-4 select-none font-sans"
  >
    <div class="bg-zinc-900 border border-purple-800/80 rounded-xl w-full max-w-lg shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
      <div class="px-5 py-4 border-b border-zinc-800 flex items-center justify-between bg-purple-950/40">
        <div class="flex items-center gap-2">
          <Settings2 class="w-5 h-5 text-purple-400" />
          <h3 class="font-semibold text-sm text-zinc-100">自定义 RTT 内存扫描 / 导入外部 Pack</h3>
        </div>
        <button
          @click="isCustomRttOpen = false"
          class="p-1 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded transition-colors"
        >
          <X class="w-4 h-4" />
        </button>
      </div>

      <div class="p-5 space-y-4">
        <!-- Pack import option -->
        <div class="bg-zinc-950 border border-zinc-800 rounded-lg p-3">
          <div class="flex items-center justify-between mb-2">
            <span class="text-xs text-zinc-300 font-semibold flex items-center gap-1.5">
              <FolderArchive class="w-4 h-4 text-purple-400" />
              <span>方式一：导入外部 CMSIS-Pack (.pack) 解析芯片 RAM</span>
            </span>
            <button
              @click="importPackForRtt"
              :disabled="isImportingPack"
              class="px-2.5 py-1 rounded bg-purple-600 hover:bg-purple-500 text-white text-xs font-medium transition-colors flex items-center gap-1"
            >
              <RefreshCw v-if="isImportingPack" class="w-3.5 h-3.5 animate-spin" />
              <span>浏览并导入Pack</span>
            </button>
          </div>
          <p v-if="importedPackInfo" class="text-[11px] text-emerald-400 font-mono bg-emerald-950/60 border border-emerald-800/60 rounded px-2 py-1">
            ✓ 已解析: {{ importedPackInfo }}
          </p>
          <p v-else class="text-[11px] text-zinc-500">
            支持 Keil DFP 芯片包，自动读取内部设备定义中的 RAM 起始地址与长度
          </p>

          <!-- Device Model Selector inside Pack -->
          <div v-if="packDevices.length > 0" class="mt-3 pt-2.5 border-t border-zinc-800 space-y-2">
            <div class="flex items-center justify-between text-xs text-zinc-300">
              <label class="font-semibold text-purple-300">选择具体芯片型号 ({{ packDevices.length }} 个型号):</label>
              <input
                v-model="packDeviceSearch"
                type="text"
                placeholder="搜索型号，如: GD32F450..."
                class="bg-zinc-900 border border-zinc-800 focus:border-purple-500 rounded px-2 py-0.5 text-[11px] text-zinc-200 outline-none w-44"
              />
            </div>
            <select
              v-model="selectedPackDevice"
              @change="handlePackDeviceChange"
              class="w-full bg-zinc-900 border border-purple-800/80 focus:border-purple-500 rounded px-2.5 py-1.5 text-xs text-purple-200 outline-none font-mono cursor-pointer"
            >
              <option
                v-for="d in filteredPackDevices"
                :key="d.name"
                :value="d.name"
                class="bg-zinc-900 text-zinc-200"
              >
                {{ d.name }} [{{ d.vendor }}] · RAM: {{ d.ram_start }} ({{ (d.ram_size / 1024).toFixed(0) }}KB)
              </option>
            </select>
          </div>
        </div>

        <!-- Manual input option -->
        <div class="bg-zinc-950 border border-zinc-800 rounded-lg p-3 space-y-3">
          <span class="text-xs text-zinc-300 font-semibold block">
            方式二：手动指定 RTT 扫描地址与范围
          </span>

          <div class="grid grid-cols-2 gap-3 font-mono text-xs">
            <div>
              <label class="block text-[11px] text-zinc-400 mb-1">RAM 起始地址 (Start):</label>
              <input
                v-model="customRttStartHex"
                type="text"
                placeholder="0x20000000"
                class="w-full bg-zinc-900 border border-zinc-800 focus:border-purple-500 rounded px-2.5 py-1.5 text-purple-300 outline-none"
              />
            </div>
            <div>
              <label class="block text-[11px] text-zinc-400 mb-1">RAM 扫描大小 (Size):</label>
              <input
                v-model="customRttSizeHex"
                type="text"
                placeholder="0x20000 (128KB)"
                class="w-full bg-zinc-900 border border-zinc-800 focus:border-purple-500 rounded px-2.5 py-1.5 text-purple-300 outline-none"
              />
            </div>
          </div>

          <div>
            <label class="block text-[11px] text-zinc-400 mb-1 font-mono">
              精确 RTT 控制块地址 (选填，留空则在 RAM 范围内自动扫描):
            </label>
            <input
              v-model="customRttBlockAddrHex"
              type="text"
              placeholder="例如 0x20001458 (MAP 文件中的 _SEGGER_RTT 地址)"
              class="w-full bg-zinc-900 border border-zinc-800 focus:border-purple-500 rounded px-2.5 py-1.5 text-xs text-zinc-200 outline-none font-mono"
            />
          </div>
        </div>
      </div>

      <div class="px-5 py-3 bg-zinc-950/80 border-t border-zinc-800 flex items-center justify-end gap-2">
        <button
          @click="isCustomRttOpen = false"
          class="px-4 py-1.5 rounded-lg text-xs bg-purple-600 hover:bg-purple-500 text-white font-semibold transition-colors"
        >
          保存并应用
        </button>
      </div>
    </div>
  </div>
</template>
