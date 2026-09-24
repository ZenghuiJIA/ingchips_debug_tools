<script setup lang="ts">
import { ref, onMounted, watch } from 'vue';
import { safeInvoke } from '../utils/ipc';
import type { ProbeInfo } from '../types';
import {
  Zap,
  RotateCcw,
  Pause,
  RefreshCw,
  Copy,
  Check,
  PieChart,
  FolderOpen,
  Package,
  X
} from '@lucide/vue';

const props = defineProps<{
  initialFilePath?: string;
}>();

const emit = defineEmits<{
  (e: 'switch-tab', tab: string, payload?: any): void;
}>();

const probes = ref<ProbeInfo[]>([]);
const selectedProbeId = ref<string>('');
const isScanningProbes = ref<boolean>(false);
const isCopied = ref<boolean>(false);

// CMSIS-Pack & Download Algorithm State
const selectedPackPath = ref<string>('');
const importedPackName = ref<string>('');
const packDevices = ref<Array<{ name: string; vendor: string; flash_size: number; flash_start: string; ram_size: number }>>([]);
const isImportingPack = ref<boolean>(false);
const swdClockFreq = ref<number>(10000000);

const swdFreqPresets = [
  { label: '50 MHz (极速)', value: 50000000 },
  { label: '20 MHz (高速)', value: 20000000 },
  { label: '10 MHz (推荐)', value: 10000000 },
  { label: '4 MHz (标准)', value: 4000000 },
  { label: '1 MHz (长线/稳定)', value: 1000000 },
];

function formatSize(bytes: number): string {
  if (!bytes) return 'N/A';
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(0)} MB`;
  return `${(bytes / 1024).toFixed(0)} KB`;
}

async function handleImportPack() {
  isImportingPack.value = true;
  try {
    const selected: string | null = await safeInvoke('pick_pack_file', {
      title: '选择 CMSIS-Pack 芯片支持包 (*.pack)'
    });
    if (!selected) {
      isImportingPack.value = false;
      return;
    }
    logMsg(`正在载入 CMSIS-Pack: ${selected} ...`, 'info');
    const res: any = await safeInvoke('svd_import_pack', { packPath: selected });
    if (res && res.status === 'success') {
      selectedPackPath.value = res.pack_path;
      importedPackName.value = res.pack;
      packDevices.value = res.devices || [];
      if (packDevices.value.length > 0) {
        targetMcu.value = packDevices.value[0].name.toLowerCase();
      }
      logMsg(`成功导入 CMSIS-Pack: ${res.pack}，已激活其内置 Flash 下载算法 (.FLM) 与 ${packDevices.value.length} 个芯片目标!`, 'success');
    }
  } catch (err: any) {
    logMsg(`导入 CMSIS-Pack 失败: ${err}`, 'error');
  } finally {
    isImportingPack.value = false;
  }
}

function clearImportedPack() {
  selectedPackPath.value = '';
  importedPackName.value = '';
  packDevices.value = [];
  targetMcu.value = 'ing91800';
  logMsg('已重置并退出外部 CMSIS-Pack 芯片算法', 'info');
}

function copyLogs() {
  if (flashLogs.value.length === 0) return;
  const text = flashLogs.value.map(l => `[${l.time}] ${l.text}`).join('\n');
  navigator.clipboard.writeText(text);
  isCopied.value = true;
  setTimeout(() => {
    isCopied.value = false;
  }, 2000);
}

const targetMcu = ref<string>('ing91800');
const targetPresets = [
  { label: 'ING91800 (ING918xx - 512KB Flash, Cortex-M3)', value: 'ing91800' },
  { label: 'ING91600 (ING916xx - 2MB Flash, Cortex-M4)', value: 'ing91600' },
  { label: 'ING2000 (ING20xx - 2MB Flash, Cortex-M3)', value: 'ing2000' },
  { label: 'ARM Cortex-M (通用)', value: 'cortex_m' },
  { label: 'STM32F103C8 (BluePill)', value: 'stm32f103c8' },
  { label: 'STM32F407VG / ZG', value: 'stm32f407vg' },
  { label: 'STM32H743VI', value: 'stm32h743vi' },
  { label: 'RP2040 (Raspberry Pi Pico)', value: 'rp2040' },
  { label: 'NRF52840', value: 'nrf52840' },
  { label: 'Cortex-M0+ 通用', value: 'cortex_m0p' },
  { label: 'Cortex-M4 通用', value: 'cortex_m4' },
];

const filePath = ref<string>(props.initialFilePath || '');

watch(() => props.initialFilePath, (newVal) => {
  if (newVal) {
    filePath.value = newVal;
    logMsg(`已从外部载入固件: ${newVal}`, 'info');
  }
});
const isFlashing = ref<boolean>(false);
const isResetting = ref<boolean>(false);
const flashLogs = ref<Array<{ time: string; text: string; status: 'info' | 'success' | 'error' }>>([]);

async function handlePickFile() {
  try {
    const selected: string | null = await safeInvoke('pick_firmware_file', {
      title: '选择要烧录的固件文件 (.bin / .hex / .elf)'
    });
    if (selected) {
      filePath.value = selected;
      logMsg(`已选择固件文件: ${selected}`, 'info');
    }
  } catch (err: any) {
    console.error('File pick error:', err);
  }
}

function logMsg(text: string, status: 'info' | 'success' | 'error' = 'info') {
  const time = new Date().toTimeString().split(' ')[0];
  flashLogs.value.unshift({ time, text, status });
  if (flashLogs.value.length > 100) flashLogs.value.pop();
}

function getProbeBadge(p: ProbeInfo) {
  if (p.probe_type === 'jlink' || p.description.toLowerCase().includes('j-link') || p.description.toLowerCase().includes('jlink')) {
    return '🔗 [J-Link]';
  }
  if (p.probe_type === 'daplink' || p.description.toLowerCase().includes('cmsis') || p.description.toLowerCase().includes('dap')) {
    return '⚡ [CMSIS-DAP]';
  }
  return '🔌 [探针]';
}

async function scanProbes() {
  isScanningProbes.value = true;
  logMsg('正在扫描 SWD/JTAG 硬件调试器 (PyOCD CMSIS-DAP / J-Link)...');
  try {
    const list: ProbeInfo[] = await safeInvoke('pyocd_list_probes');
    probes.value = list;
    if (list.length > 0) {
      selectedProbeId.value = list[0].unique_id;
      logMsg(`成功发现 ${list.length} 个调试器探针: ${getProbeBadge(list[0])} ${list[0].description} (ID: ${list[0].unique_id})`, 'success');
    } else {
      logMsg('未检测到 DAPLink / J-Link / CMSIS-DAP 调试器探针，请确认 USB 连接', 'error');
    }
  } catch (err: any) {
    logMsg(`探针扫描异常: ${err}`, 'error');
  } finally {
    isScanningProbes.value = false;
  }
}

async function handleFlash() {
  if (!filePath.value) {
    logMsg('请指定要烧录的固件文件路径 (.bin / .hex / .elf)', 'error');
    return;
  }

  isFlashing.value = true;
  const algoText = selectedPackPath.value ? ` [使用 Pack: ${importedPackName.value} 下载算法]` : ' [使用内置算法]';
  const freqMhz = (swdClockFreq.value / 1000000).toFixed(0);
  logMsg(`开始通过 SWD 烧录: ${filePath.value} (目标: ${targetMcu.value}${algoText} @ ${freqMhz}MHz)...`);

  try {
    const res: any = await safeInvoke('pyocd_flash_firmware', {
      filePath: filePath.value,
      targetOverride: targetMcu.value || null,
      probeId: selectedProbeId.value || null,
      packPath: selectedPackPath.value || null,
      frequency: Number(swdClockFreq.value) || 10000000,
    });
    logMsg(`烧录完成并成功复位运行! ${res.message || ''}`, 'success');
  } catch (err: any) {
    logMsg(`烧录失败: ${err}`, 'error');
  } finally {
    isFlashing.value = false;
  }
}

async function handleReset(halt: boolean = false) {
  isResetting.value = true;
  const actionName = halt ? 'SWD 复位并挂起 (Halt)' : 'SWD 硬件复位运行';
  logMsg(`执行: ${actionName}...`);
  try {
    await safeInvoke('pyocd_reset_target', {
      halt,
      probeId: selectedProbeId.value || null,
      targetOverride: targetMcu.value || null,
    });
    logMsg(`${actionName} 成功!`, 'success');
  } catch (err: any) {
    logMsg(`${actionName} 失败: ${err}`, 'error');
  } finally {
    isResetting.value = false;
  }
}

onMounted(() => {
  scanProbes();
});
</script>

<template>
  <div class="h-full flex flex-col p-4 bg-zinc-950 text-zinc-100 text-xs overflow-y-auto space-y-4">
    <!-- Top Card: Probe & Target Selection -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-4 space-y-3">
      <div class="flex items-center justify-between border-b border-zinc-800 pb-2.5">
        <div class="flex items-center gap-2 font-semibold text-zinc-200">
          <Zap class="w-4 h-4 text-emerald-400" />
          <span>SWD 硬件在环固件烧录器 (PyOCD CMSIS-DAP / J-Link)</span>
        </div>
        <button
          @click="scanProbes"
          :disabled="isScanningProbes"
          class="flex items-center gap-1 px-2.5 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isScanningProbes }" />
          <span>重新检测调试探针</span>
        </button>
      </div>

      <!-- CMSIS-Pack & Download Algorithm Integration -->
      <div class="bg-zinc-950/60 border border-zinc-800/80 rounded-lg p-2.5 flex items-center justify-between gap-3">
        <div class="flex items-center gap-2 flex-wrap">
          <Package class="w-4 h-4 text-amber-400 shrink-0" />
          <span class="font-medium text-zinc-300">CMSIS-Pack 固件下载算法 (.FLM):</span>
          <span v-if="selectedPackPath" class="px-2 py-0.5 rounded text-[11px] bg-amber-950/80 text-amber-300 border border-amber-700/80 flex items-center gap-1.5 font-mono">
            <span>已装载算法包: {{ importedPackName }} (含 {{ packDevices.length }} 款芯片算法)</span>
            <button @click="clearImportedPack" class="hover:text-rose-400 ml-1" title="清除外部 Pack 恢复默认预设"><X class="w-3 h-3" /></button>
          </span>
          <span v-else class="text-[11px] text-zinc-500">
            支持导入厂商 Pack (如 GD32/STM32/NXP) 自动提取芯片专有 Flash 下载算法
          </span>
        </div>
        <button
          @click="handleImportPack"
          :disabled="isImportingPack"
          class="shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded bg-amber-900/40 hover:bg-amber-800/60 text-amber-300 border border-amber-700/60 transition-colors text-xs font-medium"
        >
          <FolderOpen class="w-3.5 h-3.5" :class="{ 'animate-bounce': isImportingPack }" />
          <span>{{ isImportingPack ? '正在解析 Pack...' : '导入 CMSIS-Pack (.pack)' }}</span>
        </button>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
        <!-- Probe Selection -->
        <div>
          <label class="block text-zinc-400 mb-1 text-[11px] font-medium">调试器硬件探针 (DAPLink / J-Link / CMSIS-DAP)</label>
          <select
            v-model="selectedProbeId"
            class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-zinc-200 outline-none focus:border-emerald-500"
          >
            <option v-if="probes.length === 0" value="">(未找到探针)</option>
            <option v-for="p in probes" :key="p.unique_id" :value="p.unique_id">
              {{ getProbeBadge(p) }} {{ p.description }} (ID: {{ p.unique_id }})
            </option>
          </select>
        </div>

        <!-- Target MCU Selection -->
        <div>
          <label class="block text-zinc-400 mb-1 text-[11px] font-medium">
            目标芯片型号
            <span v-if="selectedPackPath" class="text-amber-400 font-normal">(来自已导入 Pack 算法)</span>
          </label>
          <div class="flex gap-2">
            <select
              v-model="targetMcu"
              class="flex-1 bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-zinc-200 outline-none focus:border-emerald-500"
            >
              <optgroup v-if="packDevices.length > 0" :label="`Pack 内置芯片 (使用 ${importedPackName} 下载算法)`">
                <option v-for="d in packDevices" :key="d.name" :value="d.name.toLowerCase()">
                  {{ d.vendor }} {{ d.name }} (Flash: {{ formatSize(d.flash_size) }})
                </option>
              </optgroup>
              <optgroup label="预设常用芯片型号">
                <option v-for="p in targetPresets" :key="p.value" :value="p.value">
                  {{ p.label }}
                </option>
              </optgroup>
            </select>
            <input
              v-model="targetMcu"
              type="text"
              placeholder="自定义型号"
              class="w-24 bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 outline-none focus:border-emerald-500 font-mono"
            />
          </div>
        </div>

        <!-- SWD Clock Frequency Selection -->
        <div>
          <label class="block text-zinc-400 mb-1 text-[11px] font-medium">SWD 烧录通信时钟频率</label>
          <select
            v-model="swdClockFreq"
            class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-zinc-200 outline-none focus:border-emerald-500 font-mono"
          >
            <option v-for="f in swdFreqPresets" :key="f.value" :value="f.value">
              {{ f.label }}
            </option>
          </select>
        </div>
      </div>

      <!-- File Path Selector -->
      <div>
        <label class="block text-zinc-400 mb-1 text-[11px] font-medium">固件文件绝对路径 (.bin / .hex / .elf)</label>
        <div class="flex gap-2">
          <div class="relative flex-1 flex items-center">
            <input
              v-model="filePath"
              type="text"
              placeholder="点击右侧浏览选择固件，或粘贴绝对路径 (.bin / .hex / .elf)"
              class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 pr-24 text-zinc-200 outline-none focus:border-emerald-500 font-mono"
            />
            <button
              @click="handlePickFile"
              type="button"
              class="absolute right-1 px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-emerald-400 rounded text-xs flex items-center gap-1 transition-colors border border-zinc-700/80"
              title="打开系统文件选择对话框"
            >
              <FolderOpen class="w-3.5 h-3.5" />
              <span>浏览选择</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Action Buttons -->
      <div class="flex items-center gap-3 pt-2">
        <button
          @click="handleFlash"
          :disabled="isFlashing || !filePath"
          class="flex items-center gap-2 px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded font-medium transition-colors shadow-sm disabled:opacity-40"
        >
          <Zap class="w-4 h-4" :class="{ 'animate-pulse': isFlashing }" />
          <span>{{ isFlashing ? '正在通过 SWD 烧录中...' : '一键 SWD 快速烧录' }}</span>
        </button>

        <button
          @click="handleReset(false)"
          :disabled="isResetting"
          class="flex items-center gap-1.5 px-3 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded font-medium border border-zinc-700 transition-colors disabled:opacity-40"
        >
          <RotateCcw class="w-3.5 h-3.5" />
          <span>SWD 复位运行</span>
        </button>

        <button
          @click="handleReset(true)"
          :disabled="isResetting"
          class="flex items-center gap-1.5 px-3 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded font-medium border border-zinc-700 transition-colors disabled:opacity-40"
        >
          <Pause class="w-3.5 h-3.5" />
          <span>复位并挂起 (Halt)</span>
        </button>

        <button
          @click="emit('switch-tab', 'analyzer', { filePath })"
          :disabled="!filePath"
          class="flex items-center gap-1.5 px-3 py-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded font-medium border border-zinc-700 transition-colors disabled:opacity-40 ml-auto"
          title="跳转到固件资源分析器，评估 ROM/RAM 模块开销"
        >
          <PieChart class="w-3.5 h-3.5 text-cyan-400" />
          <span>分析固件资源占用</span>
        </button>
      </div>
    </div>

    <!-- Bottom Card: Flash & SWD Execution Logs -->
    <div class="flex-1 bg-zinc-900 border border-zinc-800 rounded-lg p-4 flex flex-col min-h-[220px]">
      <div class="flex items-center justify-between pb-2 border-b border-zinc-800 mb-2">
        <span class="font-semibold text-zinc-300">烧录与调试事务日志</span>
        <div class="flex items-center gap-2">
          <button
            @click="copyLogs"
            :disabled="flashLogs.length === 0"
            class="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors disabled:opacity-40"
            title="复制全部日志到剪贴板"
          >
            <component :is="isCopied ? Check : Copy" class="w-3 h-3 text-emerald-400" />
            <span>{{ isCopied ? '已复制' : '复制日志' }}</span>
          </button>
          <button
            @click="flashLogs = []"
            class="text-[11px] text-zinc-500 hover:text-zinc-300"
          >
            清空日志
          </button>
        </div>
      </div>

      <div class="flex-1 overflow-y-auto space-y-1.5 font-mono text-[11px] p-2 bg-zinc-950 rounded border border-zinc-800/60 select-text">
        <div v-if="flashLogs.length === 0" class="text-zinc-600 text-center py-6">
          暂无烧录日志记录
        </div>
        <div
          v-for="(l, idx) in flashLogs"
          :key="idx"
          class="flex items-start gap-2"
        >
          <span class="text-zinc-600 text-[10px]">[{{ l.time }}]</span>
          <span
            :class="{
              'text-zinc-300': l.status === 'info',
              'text-emerald-400 font-semibold': l.status === 'success',
              'text-rose-400 font-semibold': l.status === 'error'
            }"
          >{{ l.text }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
