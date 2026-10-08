<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue';
import { safeInvoke } from '../utils/ipc';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import type { IngIniConfig, IngFlashProgressPayload } from '../types';
import {
  FolderOpen,
  Play,
  Square,
  RefreshCw,
  Cpu,
  FileCode,
  HardDrive,
  CheckCircle2,
  XCircle,
  Clock,
  Trash2,
  X
} from '@lucide/vue';

const props = defineProps<{
  portName: string;
  isOpen: boolean;
}>();

const emit = defineEmits<{
  (e: 'close'): void;
}>();

// Helper function to get port-specific storage key
function getPortKey(baseKey: string): string {
  const cleanPort = props.portName ? props.portName.replace(/[^a-zA-Z0-9_-]/g, '_') : 'default';
  return `${baseKey}_${cleanPort}`;
}

// Persistent storage base keys
const BASE_KEY_INI_PATH = 'ing_flasher_last_ini_path';
const BASE_KEY_SINGLE_PATH = 'ing_flasher_last_single_path';
const BASE_KEY_SINGLE_ADDR = 'ing_flasher_last_single_address';
const BASE_KEY_FAMILY = 'ing_flasher_last_family';
const BASE_KEY_MODE = 'ing_flasher_last_mode';
const BASE_KEY_BAUD = 'ing_flasher_last_baud';
const BASE_KEY_MANUAL_BOOT = 'ing_flasher_last_manual_boot';

// State initialized per port with fallback to global default
const mode = ref<'ini' | 'single'>(
  (localStorage.getItem(getPortKey(BASE_KEY_MODE)) || localStorage.getItem(BASE_KEY_MODE) || 'ini') as 'ini' | 'single'
);
const iniPath = ref<string>(
  localStorage.getItem(getPortKey(BASE_KEY_INI_PATH)) || localStorage.getItem(BASE_KEY_INI_PATH) || ''
);
const singlePath = ref<string>(
  localStorage.getItem(getPortKey(BASE_KEY_SINGLE_PATH)) || localStorage.getItem(BASE_KEY_SINGLE_PATH) || ''
);
const singleAddress = ref<string>(
  localStorage.getItem(getPortKey(BASE_KEY_SINGLE_ADDR)) || localStorage.getItem(BASE_KEY_SINGLE_ADDR) || '0x02002000'
);
const selectedFamily = ref<string>(
  localStorage.getItem(getPortKey(BASE_KEY_FAMILY)) || localStorage.getItem(BASE_KEY_FAMILY) || 'auto'
);
const selectedBaud = ref<number>(
  Number(localStorage.getItem(getPortKey(BASE_KEY_BAUD)) || localStorage.getItem(BASE_KEY_BAUD)) || 115200
);
const manualBoot = ref<boolean>(
  (localStorage.getItem(getPortKey(BASE_KEY_MANUAL_BOOT)) || localStorage.getItem(BASE_KEY_MANUAL_BOOT)) === 'true'
);

const baudRates = [115200, 230400, 460800, 921600];

// Parsed INI data
const parsedIni = ref<IngIniConfig | null>(null);
const isParsingIni = ref<boolean>(false);
const iniError = ref<string | null>(null);

// Flashing status
const isFlashing = ref<boolean>(false);
const progressPct = ref<number>(0);
const progressSpeed = ref<number>(0);
const progressStage = ref<string>('idle');
const progressMsg = ref<string>('就绪');
const logs = ref<Array<{ id: number; time: string; text: string; type: 'info' | 'success' | 'error' | 'warn' }>>([]);
let nextLogId = 1;

let unlistenProgress: UnlistenFn | null = null;

// Switch & reload configuration whenever portName prop changes
watch(() => props.portName, (newPort) => {
  if (!newPort) return;
  mode.value = (localStorage.getItem(getPortKey(BASE_KEY_MODE)) || localStorage.getItem(BASE_KEY_MODE) || 'ini') as 'ini' | 'single';
  iniPath.value = localStorage.getItem(getPortKey(BASE_KEY_INI_PATH)) || localStorage.getItem(BASE_KEY_INI_PATH) || '';
  singlePath.value = localStorage.getItem(getPortKey(BASE_KEY_SINGLE_PATH)) || localStorage.getItem(BASE_KEY_SINGLE_PATH) || '';
  singleAddress.value = localStorage.getItem(getPortKey(BASE_KEY_SINGLE_ADDR)) || localStorage.getItem(BASE_KEY_SINGLE_ADDR) || '0x02002000';
  selectedFamily.value = localStorage.getItem(getPortKey(BASE_KEY_FAMILY)) || localStorage.getItem(BASE_KEY_FAMILY) || 'auto';
  selectedBaud.value = Number(localStorage.getItem(getPortKey(BASE_KEY_BAUD)) || localStorage.getItem(BASE_KEY_BAUD)) || 115200;
  manualBoot.value = (localStorage.getItem(getPortKey(BASE_KEY_MANUAL_BOOT)) || localStorage.getItem(BASE_KEY_MANUAL_BOOT)) === 'true';

  if (iniPath.value && mode.value === 'ini') {
    loadAndParseIni(iniPath.value);
  } else {
    parsedIni.value = null;
  }
});

// Watchers for persistence: save to port-scoped key as well as global last-used fallback
watch(mode, (v) => {
  localStorage.setItem(getPortKey(BASE_KEY_MODE), v);
  localStorage.setItem(BASE_KEY_MODE, v);
});
watch(iniPath, (v) => {
  localStorage.setItem(getPortKey(BASE_KEY_INI_PATH), v);
  localStorage.setItem(BASE_KEY_INI_PATH, v);
});
watch(singlePath, (v) => {
  localStorage.setItem(getPortKey(BASE_KEY_SINGLE_PATH), v);
  localStorage.setItem(BASE_KEY_SINGLE_PATH, v);
});
watch(singleAddress, (v) => {
  localStorage.setItem(getPortKey(BASE_KEY_SINGLE_ADDR), v);
  localStorage.setItem(BASE_KEY_SINGLE_ADDR, v);
});
watch(selectedFamily, (v) => {
  localStorage.setItem(getPortKey(BASE_KEY_FAMILY), v);
  localStorage.setItem(BASE_KEY_FAMILY, v);
});
watch(selectedBaud, (v) => {
  localStorage.setItem(getPortKey(BASE_KEY_BAUD), String(v));
  localStorage.setItem(BASE_KEY_BAUD, String(v));
});
watch(manualBoot, (v) => {
  localStorage.setItem(getPortKey(BASE_KEY_MANUAL_BOOT), String(v));
  localStorage.setItem(BASE_KEY_MANUAL_BOOT, String(v));
});

function addLog(text: string, type: 'info' | 'success' | 'error' | 'warn' = 'info') {
  const d = new Date();
  const time = d.toTimeString().split(' ')[0] + '.' + d.getMilliseconds().toString().padStart(3, '0');
  logs.value.push({ id: nextLogId++, time, text, type });
  if (logs.value.length > 500) {
    logs.value = logs.value.slice(logs.value.length - 500);
  }
}

function clearFlasherLogs() {
  logs.value = [];
}

function formatBytes(bytes?: number | null): string {
  if (bytes === undefined || bytes === null) return '-';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function formatHexAddr(addr: number): string {
  return '0x' + addr.toString(16).toUpperCase().padStart(8, '0');
}

// Parse INI file
async function loadAndParseIni(path: string) {
  if (!path) return;
  isParsingIni.value = true;
  iniError.value = null;
  try {
    const res: IngIniConfig = await safeInvoke('ing_parse_ini', { iniPath: path });
    parsedIni.value = res;
    if (selectedFamily.value === 'auto') {
      selectedFamily.value = res.family;
    }
    addLog(`成功解析方案: ${path} (芯片: ${res.family.toUpperCase()}, 固件项: ${res.items.length})`, 'info');
  } catch (err: any) {
    iniError.value = String(err);
    parsedIni.value = null;
    addLog(`解析 INI 失败: ${err}`, 'error');
  } finally {
    isParsingIni.value = false;
  }
}

// File Pickers
async function pickIniFile() {
  try {
    const currentDir = iniPath.value ? iniPath.value.replace(/\\/g, '/').replace(/\/[^\/]+$/, '') : undefined;
    const selected: string | null = await safeInvoke('ing_pick_ini_file', { startingDir: currentDir });
    if (selected) {
      iniPath.value = selected;
      await loadAndParseIni(selected);
    }
  } catch (err: any) {
    addLog(`选择文件失败: ${err}`, 'error');
  }
}

async function pickSingleFile() {
  try {
    const currentDir = singlePath.value ? singlePath.value.replace(/\\/g, '/').replace(/\/[^\/]+$/, '') : undefined;
    const selected: string | null = await safeInvoke('ing_pick_firmware_file', { startingDir: currentDir });
    if (selected) {
      singlePath.value = selected;
      addLog(`已选择固件: ${selected}`, 'info');
    }
  } catch (err: any) {
    addLog(`选择文件失败: ${err}`, 'error');
  }
}

// Start Flashing
async function startFlash() {
  if (isFlashing.value) return;

  if (mode.value === 'ini') {
    if (!iniPath.value) {
      alert('请先选择 INI 烧录方案文件！');
      return;
    }
    if (!parsedIni.value || parsedIni.value.items.filter(i => i.checked).length === 0) {
      alert('当前方案未勾选任何有效固件或方案未成功解析！');
      return;
    }
  } else {
    if (!singlePath.value) {
      alert('请先选择待烧录的 BIN 或 HEX 固件文件！');
      return;
    }
  }

  isFlashing.value = true;
  progressPct.value = 0;
  progressSpeed.value = 0;
  progressStage.value = 'init';
  progressMsg.value = '开始准备烧录...';
  addLog(`[烧录启动] 目标串口: ${props.portName}, 模式: ${mode.value === 'ini' ? 'INI方案' : '单固件'}, 波特率: ${selectedBaud.value}`, 'info');

  try {
    await safeInvoke('ing_start_flash', {
      request: {
        port_name: props.portName,
        mode: mode.value,
        ini_path: mode.value === 'ini' ? iniPath.value : null,
        single_file_path: mode.value === 'single' ? singlePath.value : null,
        single_address: mode.value === 'single' ? singleAddress.value : null,
        family: selectedFamily.value,
        target_baud: selectedBaud.value,
        manual_boot: manualBoot.value,
        timeout_sec: manualBoot.value ? 15 : 2
      }
    });
  } catch (err: any) {
    isFlashing.value = false;
    progressStage.value = 'error';
    progressMsg.value = `启动失败: ${err}`;
    addLog(`烧录启动异常: ${err}`, 'error');
  }
}

async function cancelFlash() {
  if (!isFlashing.value) return;
  try {
    await safeInvoke('ing_cancel_flash');
    addLog('已向底层发送中止信号...', 'warn');
  } catch (err: any) {
    addLog(`中止失败: ${err}`, 'error');
  }
}

// Setup progress listener
onMounted(async () => {
  try {
    unlistenProgress = await listen<IngFlashProgressPayload>('ing-flash-progress', (event) => {
      const p = event.payload;
      progressStage.value = p.stage;
      progressPct.value = Math.min(100, Math.max(0, p.percentage));
      progressSpeed.value = p.speed_kbps;
      progressMsg.value = p.message;

      if (p.stage === 'error') {
        isFlashing.value = false;
        addLog(`[错误] ${p.message}`, 'error');
      } else if (p.stage === 'success') {
        isFlashing.value = false;
        progressPct.value = 100;
        addLog(`[成功] ${p.message}`, 'success');
      } else {
        if (p.message) {
          addLog(p.message, p.stage === 'burn' ? 'info' : 'warn');
        }
      }
    });
  } catch (err) {
    console.error('Failed to register flash progress listener:', err);
  }

  // Auto-load last saved INI on mount (Path memory!)
  if (iniPath.value && mode.value === 'ini') {
    loadAndParseIni(iniPath.value);
  }
});

onUnmounted(() => {
  if (unlistenProgress) {
    unlistenProgress();
    unlistenProgress = null;
  }
});
</script>

<template>
  <div v-if="isOpen" class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4">
    <div class="bg-zinc-900 border border-zinc-700/80 rounded-xl shadow-2xl w-full max-w-4xl max-h-[92vh] flex flex-col overflow-hidden text-zinc-200">
      
      <!-- Modal Header -->
      <div class="flex items-center justify-between px-5 py-3.5 border-b border-zinc-800 bg-zinc-950/80">
        <div class="flex items-center gap-2.5">
          <div class="w-8 h-8 rounded-lg bg-indigo-950/80 border border-indigo-700/80 flex items-center justify-center text-indigo-400">
            <Cpu class="w-4 h-4" />
          </div>
          <div>
            <div class="flex items-center gap-2">
              <h2 class="text-sm font-bold text-zinc-100">INGChips 串口芯片高速烧录器</h2>
              <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-indigo-950/90 text-indigo-300 border border-indigo-800">
                ING916 / ING918 原生协议
              </span>
            </div>
            <p class="text-[11px] text-zinc-400 mt-0.5 flex items-center gap-2">
              <span>当前烧录端口:</span>
              <strong class="text-emerald-400 font-mono">{{ portName }}</strong>
              <span class="text-zinc-500">(忽略 INI 中的 COM 设定，直接烧录到当前选定端口)</span>
            </p>
          </div>
        </div>

        <button
          @click="emit('close')"
          class="p-1.5 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 rounded-lg transition-colors cursor-pointer"
          title="关闭烧录面板"
        >
          <X class="w-4 h-4" />
        </button>
      </div>

      <!-- Mode Switcher & Global Config Bar -->
      <div class="px-5 py-2.5 bg-zinc-950/40 border-b border-zinc-800/80 flex items-center justify-between flex-wrap gap-3">
        <!-- Mode Tabs -->
        <div class="flex items-center bg-zinc-900 border border-zinc-800 rounded-lg p-0.5">
          <button
            @click="mode = 'ini'"
            class="px-3 py-1 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer"
            :class="mode === 'ini' ? 'bg-indigo-600 text-white shadow-xs font-semibold' : 'text-zinc-400 hover:text-zinc-200'"
          >
            <FileCode class="w-3.5 h-3.5" />
            <span>INI 方案批量烧录</span>
          </button>
          <button
            @click="mode = 'single'"
            class="px-3 py-1 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5 cursor-pointer"
            :class="mode === 'single' ? 'bg-indigo-600 text-white shadow-xs font-semibold' : 'text-zinc-400 hover:text-zinc-200'"
          >
            <HardDrive class="w-3.5 h-3.5" />
            <span>单个固件 (BIN / HEX)</span>
          </button>
        </div>

        <!-- Target Chip Architecture & Baud Selection -->
        <div class="flex items-center gap-3 text-xs">
          <div class="flex items-center gap-1.5">
            <span class="text-zinc-400">芯片系列:</span>
            <select
              v-model="selectedFamily"
              class="bg-zinc-900 border border-zinc-700/80 rounded px-2 py-1 text-xs text-zinc-200 focus:outline-hidden focus:border-indigo-500 font-mono"
            >
              <option value="auto">自动判定 (跟随方案)</option>
              <option value="ing916">ING916 / ING9168xx</option>
              <option value="ing918">ING918 / ING9188xx</option>
            </select>
          </div>

          <div class="flex items-center gap-1.5">
            <span class="text-zinc-400">烧录波特率:</span>
            <select
              v-model="selectedBaud"
              class="bg-zinc-900 border border-zinc-700/80 rounded px-2 py-1 text-xs text-zinc-200 focus:outline-hidden focus:border-indigo-500 font-mono"
            >
              <option v-for="b in baudRates" :key="b" :value="b">{{ b }} bps</option>
            </select>
          </div>

          <!-- Manual Boot Listening Mode Checkbox -->
          <label class="flex items-center gap-1.5 text-xs cursor-pointer select-none ml-1 text-zinc-300 hover:text-zinc-100" title="不发送 RTS/DTR 脉冲，直接持续监听串口（最长15秒），等待用户手动按板载按键或上电进入 BOOT">
            <input
              type="checkbox"
              v-model="manualBoot"
              class="rounded bg-zinc-950 border-zinc-700 text-indigo-500 focus:ring-0 cursor-pointer"
            />
            <span :class="manualBoot ? 'text-amber-300 font-semibold' : 'text-zinc-400'">监听等待手动进入BOOT</span>
          </label>
        </div>
      </div>

      <!-- Main Config Body (Scrollable) -->
      <div class="flex-1 overflow-y-auto p-5 space-y-4">
        
        <!-- INI Mode Panel -->
        <div v-if="mode === 'ini'" class="space-y-3">
          <!-- INI File Path Row -->
          <div class="flex items-center gap-2">
            <div class="flex-1 relative">
              <input
                v-model="iniPath"
                type="text"
                placeholder="请选择或粘贴 INGChips .ini 方案配置文件绝对路径..."
                class="w-full bg-zinc-950 border border-zinc-700/80 rounded-lg px-3 py-1.5 text-xs text-zinc-100 font-mono focus:border-indigo-500 focus:outline-hidden"
              />
            </div>
            <button
              @click="pickIniFile"
              class="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-600/80 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer"
              title="弹出窗口选择 INI 文件 (自动记忆上次目录)"
            >
              <FolderOpen class="w-3.5 h-3.5 text-indigo-400" />
              <span>选择 INI 文件</span>
            </button>
            <button
              @click="loadAndParseIni(iniPath)"
              :disabled="!iniPath || isParsingIni"
              class="px-2.5 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 rounded-lg text-xs transition-colors disabled:opacity-40 cursor-pointer"
              title="重新读取解析方案内容"
            >
              <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isParsingIni }" />
            </button>
          </div>

          <!-- Parsed INI Bin Items Table -->
          <div v-if="parsedIni" class="border border-zinc-800 rounded-lg overflow-hidden bg-zinc-950/60">
            <div class="px-3 py-2 bg-zinc-950 border-b border-zinc-800 flex items-center justify-between text-xs">
              <span class="font-semibold text-zinc-300">方案固件烧录列表 (勾选项将按序烧录)</span>
              <div class="flex items-center gap-3 text-zinc-400 text-[11px] font-mono">
                <span>系列: <strong class="text-indigo-300">{{ parsedIni.family.toUpperCase() }}</strong></span>
                <span>复位启动: <strong class="text-emerald-400">{{ parsedIni.launch ? '是' : '否' }}</strong></span>
                <span v-if="parsedIni.set_entry && parsedIni.entry_address">入口地址: <strong class="text-amber-400">{{ formatHexAddr(parsedIni.entry_address) }}</strong></span>
              </div>
            </div>

            <div class="divide-y divide-zinc-800/80 text-xs">
              <div
                v-for="item in parsedIni.items"
                :key="item.index"
                class="px-3 py-2 flex items-center justify-between hover:bg-zinc-900/60 transition-colors"
                :class="{ 'opacity-50': !item.checked }"
              >
                <div class="flex items-center gap-2.5 min-w-0 flex-1 mr-4">
                  <input
                    type="checkbox"
                    v-model="item.checked"
                    class="rounded bg-zinc-800 border-zinc-700 text-indigo-600 focus:ring-0 cursor-pointer"
                  />
                  <div class="min-w-0 flex-1">
                    <div class="flex items-center gap-2">
                      <span class="font-medium text-zinc-200">{{ item.name || `bin-${item.index}` }}</span>
                      <span class="font-mono text-[11px] text-amber-400 bg-amber-950/50 px-1.5 py-0.2 rounded border border-amber-900/50">
                        {{ formatHexAddr(item.address) }}
                      </span>
                      <span class="text-[11px] text-zinc-400 font-mono">({{ formatBytes(item.size_bytes) }})</span>
                    </div>
                    <div class="text-[11px] text-zinc-500 font-mono truncate mt-0.5" :title="item.resolved_path">
                      {{ item.resolved_path }}
                    </div>
                  </div>
                </div>

                <div>
                  <span
                    v-if="item.file_exists"
                    class="inline-flex items-center gap-1 text-[11px] text-emerald-400 bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-900/50"
                  >
                    <CheckCircle2 class="w-3 h-3" />
                    <span>文件就绪</span>
                  </span>
                  <span
                    v-else
                    class="inline-flex items-center gap-1 text-[11px] text-rose-400 bg-rose-950/40 px-2 py-0.5 rounded border border-rose-900/50"
                  >
                    <XCircle class="w-3 h-3" />
                    <span>文件未找到</span>
                  </span>
                </div>
              </div>
            </div>
          </div>

          <div v-else-if="iniError" class="p-3 bg-rose-950/30 border border-rose-800/60 rounded-lg text-xs text-rose-300">
            方案解析错误: {{ iniError }}
          </div>
          <div v-else class="p-6 text-center border border-dashed border-zinc-800 rounded-lg text-zinc-500 text-xs">
            请点击上方“选择 INI 文件”按钮加载您的 INGChips 烧录方案配置。
          </div>
        </div>

        <!-- Single File Mode Panel -->
        <div v-else class="space-y-4">
          <!-- File selection -->
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-zinc-300 flex items-center gap-1.5">
              <span>待烧录固件文件 (.bin 原始固件 或 .hex Intel HEX 格式):</span>
            </label>
            <div class="flex items-center gap-2">
              <input
                v-model="singlePath"
                type="text"
                placeholder="请选择或粘贴固件绝对路径 (.bin / .hex)..."
                class="flex-1 bg-zinc-950 border border-zinc-700/80 rounded-lg px-3 py-1.5 text-xs text-zinc-100 font-mono focus:border-indigo-500 focus:outline-hidden"
              />
              <button
                @click="pickSingleFile"
                class="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-600/80 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-colors cursor-pointer"
              >
                <FolderOpen class="w-3.5 h-3.5 text-indigo-400" />
                <span>导入 BIN / HEX</span>
              </button>
            </div>
          </div>

          <!-- Target Address Row (for raw BIN) -->
          <div class="bg-zinc-950/60 border border-zinc-800 rounded-lg p-3.5 space-y-2">
            <div class="flex items-center justify-between">
              <label class="text-xs font-medium text-zinc-300">
                <span>烧录目标物理地址 (HEX 自动从文件内解析，BIN 文件需指定):</span>
              </label>
              <div class="flex items-center gap-1 text-[11px] text-zinc-400">
                <span>快速预设:</span>
                <button
                  type="button"
                  @click="singleAddress = '0x02002000'"
                  class="text-indigo-400 hover:underline px-1"
                >ING916 (0x02002000)</button>
                <button
                  type="button"
                  @click="singleAddress = '0x00004000'"
                  class="text-indigo-400 hover:underline px-1"
                >ING918 (0x00004000)</button>
              </div>
            </div>

            <div class="flex items-center gap-3">
              <input
                v-model="singleAddress"
                type="text"
                placeholder="例如 0x02002000 或 33562624"
                class="w-64 bg-zinc-900 border border-zinc-700/80 rounded-lg px-3 py-1.5 text-xs text-amber-300 font-mono font-bold focus:border-indigo-500 focus:outline-hidden"
              />
              <span class="text-zinc-500 text-[11px]">
                提示：支持十六进制 0x 前缀或十进制数字
              </span>
            </div>
          </div>
        </div>

        <!-- Flashing Real-Time Progress Bar & Controls -->
        <div class="bg-zinc-950 border border-zinc-800 rounded-lg p-4 space-y-3">
          <div class="flex items-center justify-between text-xs">
            <div class="flex items-center gap-2">
              <span class="font-bold text-zinc-200">烧录进度:</span>
              <span class="font-mono font-bold" :class="isFlashing ? 'text-indigo-400' : (progressStage === 'success' ? 'text-emerald-400' : 'text-zinc-400')">
                {{ progressPct.toFixed(1) }}%
              </span>
              <span v-if="progressSpeed > 0" class="text-zinc-400 font-mono text-[11px]">
                ({{ progressSpeed.toFixed(1) }} KB/s)
              </span>
            </div>

            <div class="text-xs font-mono">
              <span
                class="px-2 py-0.5 rounded text-[11px] font-semibold"
                :class="{
                  'bg-zinc-800 text-zinc-400': progressStage === 'idle',
                  'bg-amber-950 text-amber-300 border border-amber-800': isFlashing && progressStage !== 'burn',
                  'bg-indigo-950 text-indigo-300 border border-indigo-800 animate-pulse': progressStage === 'burn',
                  'bg-emerald-950 text-emerald-300 border border-emerald-800': progressStage === 'success',
                  'bg-rose-950 text-rose-300 border border-rose-800': progressStage === 'error',
                }"
              >
                {{ progressMsg }}
              </span>
            </div>
          </div>

          <!-- Progress Bar Track -->
          <div class="w-full bg-zinc-800 rounded-full h-2.5 overflow-hidden">
            <div
              class="h-full transition-all duration-200 rounded-full"
              :class="progressStage === 'error' ? 'bg-rose-500' : (progressStage === 'success' ? 'bg-emerald-500' : 'bg-gradient-to-r from-indigo-500 to-cyan-400')"
              :style="{ width: `${progressPct}%` }"
            ></div>
          </div>

          <!-- Action Buttons Bar -->
          <div class="flex items-center justify-between pt-1">
            <div class="text-[11px] text-zinc-500 flex items-center gap-2">
              <span>上次烧录路径已由系统自动记忆</span>
            </div>

            <div class="flex items-center gap-2">
              <button
                v-if="isFlashing"
                @click="cancelFlash"
                class="px-4 py-1.5 bg-rose-950 hover:bg-rose-900 text-rose-300 border border-rose-800 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition-colors cursor-pointer"
              >
                <Square class="w-3.5 h-3.5 fill-current" />
                <span>中止烧录</span>
              </button>

              <button
                v-else
                @click="startFlash"
                class="px-5 py-1.5 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-xs font-bold flex items-center gap-1.5 shadow-md hover:shadow-indigo-500/20 transition-all cursor-pointer"
              >
                <Play class="w-3.5 h-3.5 fill-current" />
                <span>执行一键烧录</span>
              </button>
            </div>
          </div>
        </div>

        <!-- Flasher Real-time Logs Console -->
        <div class="border border-zinc-800 rounded-lg overflow-hidden bg-zinc-950">
          <div class="px-3 py-1.5 bg-zinc-900 border-b border-zinc-800 flex items-center justify-between text-xs text-zinc-400">
            <div class="flex items-center gap-1.5 font-medium">
              <Clock class="w-3 h-3 text-zinc-500" />
              <span>底层通信与烧录日志</span>
            </div>
            <button
              @click="clearFlasherLogs"
              class="text-zinc-500 hover:text-zinc-300 transition-colors p-0.5"
              title="清空日志"
            >
              <Trash2 class="w-3 h-3" />
            </button>
          </div>

          <div class="p-2.5 h-32 overflow-y-auto font-mono text-[11px] space-y-1 select-text">
            <div
              v-for="l in logs"
              :key="l.id"
              class="leading-relaxed flex items-start gap-1.5"
              :class="{
                'text-zinc-400': l.type === 'info',
                'text-emerald-400 font-semibold': l.type === 'success',
                'text-rose-400 font-semibold': l.type === 'error',
                'text-amber-400': l.type === 'warn',
              }"
            >
              <span class="text-zinc-600 select-none">[{{ l.time }}]</span>
              <span>{{ l.text }}</span>
            </div>
            <div v-if="logs.length === 0" class="text-zinc-600 italic">
              暂无日志输出，点击“执行一键烧录”后将实时打印时序与进度...
            </div>
          </div>
        </div>

      </div>

    </div>
  </div>
</template>
