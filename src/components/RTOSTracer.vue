<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { safeInvoke } from '../utils/ipc';
import { t } from '../utils/i18n';
import type { ProbeInfo } from '../types';
import {
  Cpu,
  RefreshCw,
  FolderOpen,
  CheckCircle,
  AlertTriangle,
  Layers,
  Activity
} from '@lucide/vue';

const probes = ref<ProbeInfo[]>([]);
const selectedProbeId = ref<string>('');
const isScanningProbes = ref<boolean>(false);
const swdFrequencyHz = ref<number>(4000000); // 4MHz default
const swdFreqPresets = [
  { label: '500 kHz', value: 500000 },
  { label: '1 MHz', value: 1000000 },
  { label: '4 MHz (常用)', value: 4000000 },
  { label: '10 MHz (高速)', value: 10000000 },
  { label: '20 MHz (极速)', value: 20000000 }
];

function formatProbeLabel(p: ProbeInfo): string {
  const typeLabel = p.probe_type === 'jlink' || p.description.toLowerCase().includes('jlink') || p.description.toLowerCase().includes('j-link')
    ? '🔗 [J-Link]' : (p.probe_type === 'daplink' || p.description.toLowerCase().includes('dap') || p.description.toLowerCase().includes('cmsis')
    ? '⚡ [CMSIS-DAP]' : '🔌 [Probe]');
  return `${typeLabel} ${p.product_name || p.description} (SN: ${p.unique_id})`;
}

async function scanProbes() {
  isScanningProbes.value = true;
  try {
    const list: ProbeInfo[] = await safeInvoke('pyocd_list_probes');
    probes.value = list;
    if (list.length > 0 && !selectedProbeId.value) {
      selectedProbeId.value = list[0].unique_id;
    }
  } catch (err) {
    console.warn('Scan probes failed in RTOSTracer:', err);
  } finally {
    isScanningProbes.value = false;
  }
}

onMounted(() => {
  scanProbes();
});

const firmwarePath = ref<string>('');
const isScanning = ref<boolean>(false);
const errorMsg = ref<string>('');
const detectionResult = ref<any>(null);

async function handlePickFirmware() {
  try {
    const selected: string | null = await safeInvoke('pick_firmware_file', {
      title: t('rtos_pick_elf_title')
    });
    if (selected) {
      firmwarePath.value = selected;
      await runRtosDetection();
    }
  } catch (err: any) {
    errorMsg.value = t('rtos_err_pick_file', { err });
  }
}

async function runRtosDetection() {
  if (!firmwarePath.value.trim()) return;
  isScanning.value = true;
  errorMsg.value = '';
  detectionResult.value = null;

  try {
    const res: any = await safeInvoke('pyocd_detect_rtos', {
      elfPath: firmwarePath.value.trim()
    });
    detectionResult.value = res;
  } catch (err: any) {
    errorMsg.value = t('rtos_err_exec', { err });
  } finally {
    isScanning.value = false;
  }
}
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-mono text-xs overflow-hidden select-none">
    <!-- Top Action Bar -->
    <div class="bg-zinc-900 border-b border-zinc-800 px-4 py-2.5 flex items-center justify-between gap-4 shrink-0">
      <div class="flex items-center gap-2 text-zinc-100 font-bold text-sm">
        <Cpu class="w-4 h-4 text-purple-400" />
        <span>{{ t("rtos_title") }}</span>
      </div>

      <!-- Probe Selector -->
      <div class="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded px-2 py-1.5 shrink-0">
        <span class="text-[10px] text-zinc-400 font-bold shrink-0">SWD:</span>
        <select
          v-model="selectedProbeId"
          class="bg-transparent text-purple-300 font-bold outline-none text-xs max-w-[200px] truncate cursor-pointer"
        >
          <option v-if="probes.length === 0" value="" class="bg-zinc-900 text-zinc-400">
            {{ isScanningProbes ? '正在搜索探针...' : '未检测到探针 (自动选默认)' }}
          </option>
          <option
            v-for="p in probes"
            :key="p.unique_id"
            :value="p.unique_id"
            class="bg-zinc-900 text-zinc-200"
          >
            {{ formatProbeLabel(p) }}
          </option>
        </select>
        <button
          @click="scanProbes"
          :disabled="isScanningProbes"
          title="刷新探针列表"
          class="text-zinc-400 hover:text-purple-400 p-0.5 rounded transition"
        >
          <RefreshCw class="w-3 h-3" :class="{ 'animate-spin': isScanningProbes }" />
        </button>

        <!-- SWD Clock Frequency Selector -->
        <span class="text-zinc-600 text-[10px] pl-1 border-l border-zinc-800">CLK:</span>
        <select
          v-model.number="swdFrequencyHz"
          class="bg-transparent text-purple-300 font-bold outline-none text-xs cursor-pointer"
          title="SWD 探针通信时钟频率"
        >
          <option v-for="sp in swdFreqPresets" :key="sp.value" :value="sp.value" class="bg-zinc-900 text-zinc-200">
            {{ sp.label }}
          </option>
        </select>
      </div>

      <div class="flex items-center gap-2 flex-1 max-w-xl">
        <div class="relative flex-1 flex items-center">
          <input
            v-model="firmwarePath"
            type="text"
            :placeholder="t('rtos_placeholder_file')"
            class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 pr-24 text-zinc-200 text-xs outline-none focus:border-purple-500 font-mono"
            @keyup.enter="runRtosDetection"
          />
          <button
            @click="handlePickFirmware"
            type="button"
            class="absolute right-1 px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-purple-400 rounded text-xs flex items-center gap-1 transition-colors border border-zinc-700/80"
          >
            <FolderOpen class="w-3.5 h-3.5" />
            <span>{{ t("rtos_btn_browse") }}</span>
          </button>
        </div>

        <button
          @click="runRtosDetection"
          :disabled="isScanning || !firmwarePath.trim()"
          class="flex items-center gap-1.5 px-3 py-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded text-xs font-semibold transition-colors disabled:opacity-40 shrink-0"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isScanning }" />
          <span>{{ t("rtos_btn_detect") }}</span>
        </button>
      </div>
    </div>

    <!-- Error Alert -->
    <div v-if="errorMsg" class="bg-rose-950/60 border-b border-rose-800 text-rose-300 px-4 py-2 text-xs flex items-center gap-2">
      <AlertTriangle class="w-4 h-4 text-rose-400 shrink-0" />
      <span>{{ errorMsg }}</span>
    </div>

    <!-- Main Content Area -->
    <div class="flex-1 p-4 overflow-y-auto space-y-4">
      <!-- Status Card -->
      <div v-if="detectionResult" class="grid grid-cols-3 gap-3">
        <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div class="text-[10px] text-zinc-400 mb-1">{{ t("rtos_type_label") }}</div>
          <div class="text-base font-bold flex items-center gap-2" :class="detectionResult.detected ? 'text-purple-400' : 'text-amber-400'">
            <CheckCircle v-if="detectionResult.detected" class="w-4 h-4 text-emerald-400" />
            <AlertTriangle v-else class="w-4 h-4 text-amber-400" />
            <span>{{ detectionResult.rtos_type }}</span>
          </div>
        </div>

        <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div class="text-[10px] text-zinc-400 mb-1">{{ t("rtos_conf_label") }}</div>
          <div class="text-base font-bold text-zinc-200">
            {{ detectionResult.confidence || '0/0' }}
          </div>
        </div>

        <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div class="text-[10px] text-zinc-400 mb-1">{{ t("rtos_state_label") }}</div>
          <div class="text-base font-bold text-emerald-400">
            {{ detectionResult.detected ? t('rtos_state_detected') : t('rtos_state_undetected') }}
          </div>
        </div>
      </div>

      <!-- Matched Symbols Table -->
      <div v-if="detectionResult?.matched_symbols && Object.keys(detectionResult.matched_symbols).length > 0" class="border border-zinc-800 rounded-lg overflow-hidden bg-zinc-900/60">
        <div class="bg-zinc-900 px-3 py-2 border-b border-zinc-800 flex items-center justify-between text-xs font-semibold text-zinc-200">
          <div class="flex items-center gap-1.5">
            <Layers class="w-3.5 h-3.5 text-purple-400" />
            <span>{{ t("rtos_symbols_title") }}</span>
          </div>
          <span class="text-[10px] text-zinc-500 font-normal">{{ t("rtos_symbols_sub") }}</span>
        </div>

        <table class="w-full text-left text-xs font-mono">
          <thead class="bg-zinc-950/60 text-zinc-400 text-[10px] border-b border-zinc-800">
            <tr>
              <th class="p-2.5">{{ t("rtos_th_sym") }}</th>
              <th class="p-2.5">{{ t("rtos_th_addr") }}</th>
              <th class="p-2.5">{{ t("rtos_th_desc") }}</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-zinc-800/60">
            <tr v-for="(addr, symName) in detectionResult.matched_symbols" :key="symName" class="hover:bg-zinc-900/80">
              <td class="p-2.5 font-bold text-zinc-200">{{ symName }}</td>
              <td class="p-2.5 text-emerald-400">{{ addr }}</td>
              <td class="p-2.5 text-zinc-400 text-[11px]">
                <span v-if="String(symName).includes('Ready') || String(symName).includes('ready')">{{ t("rtos_desc_ready") }}</span>
                <span v-else-if="String(symName).includes('Current') || String(symName).includes('Cur') || String(symName).includes('curr')">{{ t("rtos_desc_current") }}</span>
                <span v-else-if="String(symName).includes('Config') || String(symName).includes('config')">{{ t("rtos_desc_config") }}</span>
                <span v-else-if="String(symName).includes('Info') || String(symName).includes('info')">{{ t("rtos_desc_info") }}</span>
                <span v-else-if="String(symName).includes('Tick') || String(symName).includes('clock')">{{ t("rtos_desc_tick") }}</span>
                <span v-else-if="String(symName).includes('created') || String(symName).includes('Tbl')">{{ t("rtos_desc_created") }}</span>
                <span v-else>{{ t("rtos_desc_default") }}</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- No Selection Prompt -->
      <div v-else-if="!isScanning" class="p-12 text-center text-zinc-500 space-y-3">
        <Activity class="w-10 h-10 mx-auto text-zinc-700 animate-pulse" />
        <div class="text-sm font-medium text-zinc-400">{{ t("rtos_guide_title") }}</div>
        <div class="text-[11px] text-zinc-600 max-w-md mx-auto">
          {{ t("rtos_guide_body") }}
        </div>
      </div>
    </div>
  </div>
</template>
