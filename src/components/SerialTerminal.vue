<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue';
import { safeInvoke } from '../utils/ipc';
import type { TerminalSessionTab, PortInfo, SvdDevice } from '../types';
import SerialTerminalSession from './SerialTerminalSession.vue';
import {
  Plus,
  X,
  RefreshCw,
  Power,
  Radio,
  FolderArchive
} from '@lucide/vue';

const props = defineProps<{
  // Initial / main connection props from HeaderBar
  isConnected: boolean;
  activePort: string | null;
}>();

const emit = defineEmits<{
  (e: 'switch-tab', tab: string): void;
  (e: 'request-connect', port: string, baud: number): void;
  (e: 'request-disconnect', port?: string): void;
}>();

// Available system ports
const availablePorts = ref<PortInfo[]>([]);
const isRefreshingPorts = ref<boolean>(false);

// Active multi-session tabs
const tabs = ref<TerminalSessionTab[]>([]);
const activeTabId = ref<string>('');

// Modal for opening a new port
const isNewPortModalOpen = ref<boolean>(false);
const newPortSelected = ref<string>('');
const newPortBaud = ref<number>(115200);
const baudRates = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600];

// RTT RAM presets for new tab
const rttRamPresets = [
  { label: 'SRAM 0x20000000 (128KB 常用M4/M3)', start: 0x20000000, size: 0x20000 },
  { label: 'SRAM 0x20000000 (64KB 常用M0/M3)', start: 0x20000000, size: 0x10000 },
  { label: 'SRAM 0x20000000 (256KB 大RAM)', start: 0x20000000, size: 0x40000 },
  { label: 'SRAM 0x20000000 (512KB 高性能M7/M4)', start: 0x20000000, size: 0x80000 },
  { label: 'AXI-SRAM 0x24000000 (512KB H7系列)', start: 0x24000000, size: 0x80000 },
  { label: '自定义 / Pack解析地址', start: -1, size: -1 },
];
const newPortRttRamPreset = ref<number>(0x20000000);
const newPortRttRamSize = ref<number>(0x20000);
const newPortRttCustomStartHex = ref<string>('0x20000000');
const newPortRttCustomSizeHex = ref<string>('0x20000');
const newPortRttBlockAddrHex = ref<string>(''); // Exact RTT CB
const isNewPortImportingPack = ref<boolean>(false);
const newPortImportedPackInfo = ref<string>('');
const newPortPackDevices = ref<SvdDevice[]>([]);
const newPortSelectedPackDevice = ref<string>('');
const newPortPackDeviceSearch = ref<string>('');

const filteredNewPortPackDevices = computed(() => {
  if (!newPortPackDeviceSearch.value.trim()) return newPortPackDevices.value;
  const q = newPortPackDeviceSearch.value.trim().toLowerCase();
  return newPortPackDevices.value.filter(d =>
    d.name.toLowerCase().includes(q) || d.vendor.toLowerCase().includes(q)
  );
});

function applyNewPortDeviceRam(dev: SvdDevice) {
  newPortRttCustomStartHex.value = dev.ram_start || '0x20000000';
  const sizeVal = dev.ram_size || 0x20000;
  newPortRttCustomSizeHex.value = `0x${sizeVal.toString(16).toUpperCase()}`;
}

function handleNewPortPackDeviceChange() {
  const found = newPortPackDevices.value.find(d => d.name === newPortSelectedPackDevice.value);
  if (found) {
    applyNewPortDeviceRam(found);
  }
}

async function importPackForNewPortRtt() {
  try {
    const selected: string | null = await safeInvoke('pick_pack_file', {
      title: '选择芯片 CMSIS-Pack 文件以解析默认 RAM / RTT 地址'
    });
    if (selected) {
      isNewPortImportingPack.value = true;
      const res: any = await safeInvoke('svd_import_pack', { packPath: selected });
      if (res && res.devices && res.devices.length > 0) {
        newPortPackDevices.value = res.devices;
        newPortImportedPackInfo.value = `${res.pack}: 成功解析到 ${res.devices.length} 个芯片型号`;
        const dev = res.devices[0];
        newPortSelectedPackDevice.value = dev.name;
        applyNewPortDeviceRam(dev);
        newPortRttRamPreset.value = -1;
      }
    }
  } catch (err: any) {
    alert(`导入 Pack 解析失败: ${err}`);
  } finally {
    isNewPortImportingPack.value = false;
  }
}

async function toggleTabConnection(tab: TerminalSessionTab) {
  if (tab.isConnected) {
    try {
      await safeInvoke('close_serial_port', { portName: tab.portName });
      tab.isConnected = false;
    } catch (err) {
      console.error(`关闭端口 ${tab.portName} 失败:`, err);
    }
  } else {
    try {
      if (tab.portName.startsWith('RTT')) {
        await safeInvoke('open_serial_port', {
          portName: tab.portName,
          baudRate: tab.baudRate,
          ramStart: newPortRttRamPreset.value !== -1 ? newPortRttRamPreset.value : parseInt(newPortRttCustomStartHex.value.trim(), 16),
          ramSize: newPortRttRamPreset.value !== -1 ? newPortRttRamSize.value : parseInt(newPortRttCustomSizeHex.value.trim(), 16),
          blockAddress: newPortRttBlockAddrHex.value.trim() ? parseInt(newPortRttBlockAddrHex.value.trim(), 16) : null,
        });
      } else {
        await safeInvoke('open_serial_port', {
          portName: tab.portName,
          baudRate: tab.baudRate,
          ramStart: null,
          ramSize: null,
          blockAddress: null,
        });
      }
      tab.isConnected = true;
    } catch (err: any) {
      alert(`打开端口 ${tab.portName} 失败: ${err}`);
    }
  }
}

async function refreshPortList() {
  isRefreshingPorts.value = true;
  try {
    const list: PortInfo[] = await safeInvoke('list_serial_ports');
    availablePorts.value = list;
    if (list.length > 0 && !newPortSelected.value) {
      newPortSelected.value = list[0].port_name;
    }
  } catch (err) {
    console.error('List serial ports failed:', err);
  } finally {
    isRefreshingPorts.value = false;
  }
}

// Synchronize main activePort from HeaderBar
watch([() => props.activePort, () => props.isConnected], ([newPort, connected]) => {
  if (connected && newPort) {
    let existing = tabs.value.find(t => t.portName === newPort);
    if (!existing) {
      const isDap = availablePorts.value.find(p => p.port_name === newPort)?.is_daplink ?? false;
      const newTab: TerminalSessionTab = {
        id: `tab_${Date.now()}_${Math.random().toString(36).slice(2, 5)}`,
        portName: newPort,
        baudRate: 115200,
        isConnected: true,
        isDaplink: isDap,
        rxBytesCount: 0,
        txBytesCount: 0
      };
      tabs.value.push(newTab);
      activeTabId.value = newTab.id;
    } else {
      existing.isConnected = true;
      activeTabId.value = existing.id;
    }
  } else if (!connected && newPort) {
    const existing = tabs.value.find(t => t.portName === newPort);
    if (existing) {
      existing.isConnected = false;
    }
  }
}, { immediate: true });

function openNewPortDialog() {
  refreshPortList();
  isNewPortModalOpen.value = true;
}

async function confirmOpenNewPort() {
  if (!newPortSelected.value) return;

  const targetPort = newPortSelected.value;
  const targetBaud = Number(newPortBaud.value);

  // Check if tab already exists
  let tab = tabs.value.find(t => t.portName === targetPort);
  if (tab && tab.isConnected) {
    activeTabId.value = tab.id;
    isNewPortModalOpen.value = false;
    return;
  }

  try {
    if (targetPort.startsWith('RTT')) {
      const rStart = newPortRttRamPreset.value !== -1 ? newPortRttRamPreset.value : parseInt(newPortRttCustomStartHex.value.trim(), 16);
      const rSize = newPortRttRamPreset.value !== -1 ? newPortRttRamSize.value : parseInt(newPortRttCustomSizeHex.value.trim(), 16);
      const bAddr = newPortRttBlockAddrHex.value.trim() ? parseInt(newPortRttBlockAddrHex.value.trim(), 16) : null;

      await safeInvoke('open_serial_port', {
        portName: targetPort,
        baudRate: targetBaud,
        ramStart: rStart,
        ramSize: rSize,
        blockAddress: bAddr,
      });
    } else {
      await safeInvoke('open_serial_port', {
        portName: targetPort,
        baudRate: targetBaud,
        ramStart: null,
        ramSize: null,
        blockAddress: null,
      });
    }

    const isDap = availablePorts.value.find(p => p.port_name === targetPort)?.is_daplink ?? false;

    if (!tab) {
      tab = {
        id: `tab_${Date.now()}_${Math.random().toString(36).slice(2, 5)}`,
        portName: targetPort,
        baudRate: targetBaud,
        isConnected: true,
        isDaplink: isDap,
        rxBytesCount: 0,
        txBytesCount: 0
      };
      tabs.value.push(tab);
    } else {
      tab.isConnected = true;
      tab.baudRate = targetBaud;
    }

    activeTabId.value = tab.id;
    isNewPortModalOpen.value = false;
  } catch (err: any) {
    alert(`打开端口 ${targetPort} 失败: ${err}`);
  }
}

async function closeTab(tab: TerminalSessionTab, e?: MouseEvent) {
  if (e) e.stopPropagation();

  if (tab.isConnected) {
    try {
      await safeInvoke('close_serial_port', { portName: tab.portName });
    } catch (err) {
      console.error(`关闭端口 ${tab.portName} 失败:`, err);
    }
  }

  const idx = tabs.value.findIndex(t => t.id === tab.id);
  if (idx !== -1) {
    tabs.value.splice(idx, 1);
    if (activeTabId.value === tab.id) {
      if (tabs.value.length > 0) {
        activeTabId.value = tabs.value[Math.max(0, idx - 1)].id;
      } else {
        activeTabId.value = '';
      }
    }
  }
}

function handleTabStatsUpdate(tabId: string, stats: { rx: number; tx: number }) {
  const tab = tabs.value.find(t => t.id === tabId);
  if (tab) {
    tab.rxBytesCount = stats.rx;
    tab.txBytesCount = stats.tx;
  }
}

onMounted(() => {
  refreshPortList();
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 overflow-hidden select-none">
    <!-- Top Tabs Bar (Chrome / VS Code style) -->
    <div class="bg-zinc-900 border-b border-zinc-800 px-2 pt-1.5 flex items-center justify-between gap-2 shrink-0">
      <!-- Left: Tab List -->
      <div class="flex items-center gap-1 overflow-x-auto min-w-0">
        <template v-if="tabs.length > 0">
          <div
            v-for="tab in tabs"
            :key="tab.id"
            @click="activeTabId = tab.id"
            class="flex items-center gap-2 px-3 py-1.5 rounded-t text-xs font-mono border-t-2 transition-all cursor-pointer group"
            :class="activeTabId === tab.id
              ? 'bg-zinc-950 border-emerald-500 text-zinc-100 font-semibold shadow-sm'
              : 'bg-zinc-900/60 hover:bg-zinc-800/80 border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <!-- Port Status Indicator -->
            <span
              class="w-2 h-2 rounded-full shrink-0"
              :class="tab.isConnected ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-600'"
            ></span>

            <!-- Port Label -->
            <span class="truncate max-w-[130px]">{{ tab.portName }}</span>

            <!-- Close Tab Button -->
            <button
              @click="closeTab(tab, $event)"
              class="opacity-0 group-hover:opacity-100 hover:bg-zinc-800 hover:text-rose-400 rounded p-0.5 text-zinc-500 transition-opacity"
              title="关闭该端口会话"
            >
              <X class="w-3 h-3" />
            </button>
          </div>
        </template>

        <!-- No Tabs Open State -->
        <div v-else class="text-xs text-zinc-500 px-2 py-1.5 flex items-center gap-2">
          <span>暂无打开的串口设备</span>
        </div>

        <!-- Add Port Tab Button -->
        <button
          @click="openNewPortDialog"
          class="flex items-center gap-1 px-2.5 py-1.5 rounded text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-300 hover:text-emerald-400 border border-zinc-700/60 transition-colors ml-1"
          title="打开并添加新的并行串口/RTT设备"
        >
          <Plus class="w-3.5 h-3.5" />
          <span>打开新端口</span>
        </button>
      </div>

      <!-- Right: Active Session Quick Controls -->
      <div v-if="tabs.length > 0" class="flex items-center gap-2 shrink-0 pb-1">
        <span class="text-[11px] text-zinc-500 font-mono hidden md:inline">
          并发连接数: <strong class="text-emerald-400">{{ tabs.filter(t => t.isConnected).length }}</strong> / {{ tabs.length }}
        </span>
      </div>
    </div>

    <!-- Active Tab Contents Area (KeepAlive / v-show to preserve background receiving & triggers) -->
    <div class="flex-1 overflow-hidden relative">
      <template v-if="tabs.length > 0">
        <div
          v-for="tab in tabs"
          :key="tab.id"
          v-show="activeTabId === tab.id"
          class="h-full w-full"
        >
          <SerialTerminalSession
            :port-name="tab.portName"
            :baud-rate="tab.baudRate"
            :is-connected="tab.isConnected"
            :is-daplink="tab.isDaplink"
            @switch-tab="(t) => emit('switch-tab', t)"
            @update-stats="(s) => handleTabStatsUpdate(tab.id, s)"
            @toggle-connection="toggleTabConnection(tab)"
          />
        </div>
      </template>

      <!-- Empty State View -->
      <div v-else class="h-full flex flex-col items-center justify-center text-zinc-600 space-y-3">
        <div class="w-14 h-14 rounded-2xl bg-zinc-900 border border-zinc-800 flex items-center justify-center text-zinc-500">
          <Radio class="w-7 h-7 stroke-1" />
        </div>
        <div class="text-center">
          <p class="text-sm font-semibold text-zinc-300">多设备终端就绪</p>
          <p class="text-xs text-zinc-500 mt-1">可在上方点击 <strong>【打开新端口】</strong> 添加并行串口、DAPLink 或 RTT 监视通道</p>
        </div>
        <button
          @click="openNewPortDialog"
          class="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold shadow transition-colors"
        >
          <Plus class="w-4 h-4" />
          <span>添加端口会话</span>
        </button>
      </div>
    </div>

    <!-- Open New Port Modal Dialog -->
    <div
      v-if="isNewPortModalOpen"
      class="fixed inset-0 bg-black/70 backdrop-blur-xs z-50 flex items-center justify-center p-4"
    >
      <div class="bg-zinc-900 border border-zinc-800 rounded-xl w-full max-w-md shadow-2xl overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        <!-- Dialog Header -->
        <div class="px-5 py-4 border-b border-zinc-800 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <Radio class="w-5 h-5 text-emerald-400" />
            <h3 class="font-semibold text-sm text-zinc-100">打开新的串口/RTT设备会话</h3>
          </div>
          <button
            @click="isNewPortModalOpen = false"
            class="p-1 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded transition-colors"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <!-- Dialog Body -->
        <div class="p-5 space-y-4">
          <!-- Port Selection -->
          <div>
            <div class="flex items-center justify-between text-xs text-zinc-300 mb-1.5">
              <label>目标物理串口 / 虚拟通道:</label>
              <button
                @click="refreshPortList"
                class="flex items-center gap-1 text-[11px] text-emerald-400 hover:underline"
              >
                <RefreshCw class="w-3 h-3" :class="{ 'animate-spin': isRefreshingPorts }" />
                <span>刷新</span>
              </button>
            </div>
            <select
              v-model="newPortSelected"
              class="w-full bg-zinc-950 border border-zinc-800 focus:border-emerald-500 rounded-lg px-3 py-2 text-xs text-zinc-200 outline-none cursor-pointer"
            >
              <option v-if="availablePorts.length === 0" value="">暂无可用串口</option>
              <option
                v-for="p in availablePorts"
                :key="p.port_name"
                :value="p.port_name"
                class="bg-zinc-900 text-zinc-200"
              >
                {{ p.port_name }} ({{ p.description }})
              </option>
            </select>
          </div>

          <!-- Baud Rate (if not RTT) -->
          <div v-if="!newPortSelected.startsWith('RTT')">
            <label class="block text-xs text-zinc-300 mb-1.5">波特率 (Baud Rate):</label>
            <select
              v-model="newPortBaud"
              class="w-full bg-zinc-950 border border-zinc-800 focus:border-emerald-500 rounded-lg px-3 py-2 text-xs text-zinc-200 outline-none cursor-pointer"
            >
              <option v-for="b in baudRates" :key="b" :value="b" class="bg-zinc-900 text-zinc-200">
                {{ b }} bps {{ b === 921600 ? '⚡ (极速推荐)' : '' }}
              </option>
            </select>
          </div>

          <!-- RTT Memory Scan Preset & Custom / Pack Options (if RTT) -->
          <div v-else class="space-y-3">
            <div>
              <div class="flex items-center justify-between text-xs text-zinc-300 mb-1.5">
                <label>RTT RAM 扫描预设 / 范围:</label>
                <button
                  @click="importPackForNewPortRtt"
                  :disabled="isNewPortImportingPack"
                  class="text-[11px] text-purple-400 hover:text-purple-300 hover:underline flex items-center gap-1"
                >
                  <FolderArchive class="w-3.5 h-3.5" />
                  <span>导入Pack自动解析</span>
                </button>
              </div>
              <select
                v-model="newPortRttRamPreset"
                @change="(e: any) => {
                  const val = Number(e.target.value);
                  if (val !== -1) {
                    const found = rttRamPresets.find(p => p.start === val);
                    if (found) newPortRttRamSize = found.size;
                  }
                }"
                class="w-full bg-purple-950/70 border border-purple-800 focus:border-purple-500 rounded-lg px-3 py-2 text-xs text-purple-200 outline-none cursor-pointer font-mono"
              >
                <option v-for="p in rttRamPresets" :key="p.label" :value="p.start" class="bg-zinc-900 text-zinc-200">
                  ⚡ {{ p.label }}
                </option>
              </select>
            </div>

            <div v-if="newPortImportedPackInfo" class="text-[11px] text-emerald-400 font-mono bg-emerald-950/60 border border-emerald-800/60 rounded px-2.5 py-1.5">
              ✓ Pack 解析: {{ newPortImportedPackInfo }}
            </div>

            <!-- Model Selection dropdown if Pack imported -->
            <div v-if="newPortPackDevices.length > 0" class="bg-zinc-950 border border-purple-900/60 rounded-lg p-2.5 space-y-2">
              <div class="flex items-center justify-between text-xs text-zinc-300">
                <label class="font-semibold text-purple-300 text-[11px]">选择具体芯片型号 ({{ newPortPackDevices.length }} 个型号):</label>
                <input
                  v-model="newPortPackDeviceSearch"
                  type="text"
                  placeholder="搜索型号，如: GD32F450..."
                  class="bg-zinc-900 border border-zinc-800 focus:border-purple-500 rounded px-2 py-0.5 text-[11px] text-zinc-200 outline-none w-36"
                />
              </div>
              <select
                v-model="newPortSelectedPackDevice"
                @change="handleNewPortPackDeviceChange"
                class="w-full bg-zinc-900 border border-purple-800/80 focus:border-purple-500 rounded px-2.5 py-1.5 text-xs text-purple-200 outline-none font-mono cursor-pointer"
              >
                <option
                  v-for="d in filteredNewPortPackDevices"
                  :key="d.name"
                  :value="d.name"
                  class="bg-zinc-900 text-zinc-200"
                >
                  {{ d.name }} [{{ d.vendor }}] · RAM: {{ d.ram_start }} ({{ (d.ram_size / 1024).toFixed(0) }}KB)
                </option>
              </select>
            </div>

            <!-- Custom RAM / RTT block inputs when custom selected or pack imported -->
            <div v-if="newPortRttRamPreset === -1" class="bg-zinc-950 border border-zinc-800 rounded-lg p-3 space-y-2.5 font-mono text-xs">
              <div class="grid grid-cols-2 gap-2.5">
                <div>
                  <label class="block text-[11px] text-zinc-400 mb-1">RAM 起始地址 (Start):</label>
                  <input
                    v-model="newPortRttCustomStartHex"
                    type="text"
                    placeholder="0x20000000"
                    class="w-full bg-zinc-900 border border-zinc-800 focus:border-purple-500 rounded px-2 py-1 text-purple-300 outline-none"
                  />
                </div>
                <div>
                  <label class="block text-[11px] text-zinc-400 mb-1">RAM 大小 (Size):</label>
                  <input
                    v-model="newPortRttCustomSizeHex"
                    type="text"
                    placeholder="0x20000"
                    class="w-full bg-zinc-900 border border-zinc-800 focus:border-purple-500 rounded px-2 py-1 text-purple-300 outline-none"
                  />
                </div>
              </div>

              <div>
                <label class="block text-[11px] text-zinc-400 mb-1">
                  指定 RTT 控制块地址 (选填，留空则自动扫描):
                </label>
                <input
                  v-model="newPortRttBlockAddrHex"
                  type="text"
                  placeholder="例如 0x20001458 (留空则在RAM内自动扫描)"
                  class="w-full bg-zinc-900 border border-zinc-800 focus:border-purple-500 rounded px-2 py-1 text-zinc-200 outline-none"
                />
              </div>
            </div>
          </div>

          <div class="bg-zinc-950/80 border border-zinc-800 rounded-lg p-3 text-[11px] text-zinc-400 space-y-1">
            <p class="text-zinc-300 font-semibold">💡 并行多设备运行提示：</p>
            <p>• 每个打开的串口拥有独立的后台通信线程、日志缓冲区与触发器应答规则。</p>
            <p>• 切换不同标签页时，后台会话不会断开，数据无损实时接收。</p>
          </div>
        </div>

        <!-- Dialog Footer -->
        <div class="px-5 py-3.5 bg-zinc-950/60 border-t border-zinc-800 flex items-center justify-end gap-2">
          <button
            @click="isNewPortModalOpen = false"
            class="px-3 py-1.5 rounded-lg text-xs text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors"
          >
            取消
          </button>
          <button
            @click="confirmOpenNewPort"
            :disabled="!newPortSelected"
            class="flex items-center gap-1.5 px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold transition-colors disabled:opacity-40"
          >
            <Power class="w-3.5 h-3.5" />
            <span>确认连接打开</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
