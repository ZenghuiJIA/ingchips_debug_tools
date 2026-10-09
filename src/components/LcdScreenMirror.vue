<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import { safeInvoke } from '../utils/ipc';
import { t } from '../utils/i18n';
import type { ProbeInfo } from '../types';
import {
  Monitor,
  Camera,
  Play,
  Square,
  Download,
  AlertTriangle,
  RefreshCw
} from '@lucide/vue';

const probes = ref<ProbeInfo[]>([]);
const selectedProbeId = ref<string>('');
const isScanningProbes = ref<boolean>(false);
const swdFrequencyHz = ref<number>(10000000); // 10MHz default for fast framebuffer transfer
const swdFreqPresets = [
  { label: '1 MHz (兼容)', value: 1000000 },
  { label: '4 MHz (常用)', value: 4000000 },
  { label: '10 MHz (高速推荐)', value: 10000000 },
  { label: '20 MHz (极速传输)', value: 20000000 },
  { label: '30 MHz (J-Link极速)', value: 30000000 }
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
    console.warn('Scan probes failed in LcdScreenMirror:', err);
  } finally {
    isScanningProbes.value = false;
  }
}

onMounted(() => {
  scanProbes();
});

const fbAddress = ref<string>('0x20000000');
const fbWidth = ref<number>(320);
const fbHeight = ref<number>(240);
const pixelFormat = ref<'rgb565' | 'rgb888' | 'argb8888' | 'mono'>('rgb565');

// Symbol Auto-Sniffing from ELF/AXF
const isSniffing = ref<boolean>(false);
const sniffNotice = ref<string>('');

async function handleSniffFromFirmware() {
  isSniffing.value = true;
  sniffNotice.value = '';
  try {
    const file: string | null = await safeInvoke('pick_firmware_file', {
      title: '选择包含 LCD 显存变量的固件符号文件 (.axf / .elf)'
    });
    if (file) {
      const res: any = await safeInvoke('detect_lcd_framebuffer_symbol', {
        filePath: file
      });
      if (res && res.candidates && res.candidates.length > 0) {
        const best = res.candidates[0];
        fbAddress.value = best.address;
        fbWidth.value = best.suggested_width;
        fbHeight.value = best.suggested_height;
        pixelFormat.value = best.suggested_format;
        sniffNotice.value = `已自动匹配显存变量: ${best.name} -> 基地址: ${best.address} (${best.suggested_width}×${best.suggested_height})`;
      } else {
        sniffNotice.value = '未从符号表中识别到包含 lcd/disp/framebuffer 的大块内存变量，请手动输入显存基地址。';
      }
    }
  } catch (e: any) {
    sniffNotice.value = `扫描显存符号异常: ${e}`;
  } finally {
    isSniffing.value = false;
  }
}

const isAutoRefreshing = ref<boolean>(false);
const refreshIntervalMs = ref<number>(500);
let autoTimer: any = null;

const isCapturing = ref<boolean>(false);
const errorMsg = ref<string>('');
const lastCaptureTime = ref<string>('');
const currentImageData = ref<string>('');
const capturedCount = ref<number>(0);

async function captureScreen() {
  if (isCapturing.value) return;
  isCapturing.value = true;
  errorMsg.value = '';

  try {
    const res: any = await safeInvoke('pyocd_capture_framebuffer', {
      address: fbAddress.value.trim(),
      width: fbWidth.value,
      height: fbHeight.value,
      pixelFormat: pixelFormat.value,
      probeId: selectedProbeId.value || null,
      targetOverride: null,
      frequency: swdFrequencyHz.value || 10000000
    });

    if (res && res.status === 'success' && res.image_base64) {
      currentImageData.value = res.image_base64;
      capturedCount.value++;
      lastCaptureTime.value = new Date().toLocaleTimeString();
    } else {
      errorMsg.value = res?.message || t('lcd_err_read');
    }
  } catch (err: any) {
    errorMsg.value = t('lcd_err_capture', { err });
  } finally {
    isCapturing.value = false;
  }
}

function toggleAutoRefresh() {
  if (isAutoRefreshing.value) {
    stopAutoRefresh();
  } else {
    startAutoRefresh();
  }
}

function startAutoRefresh() {
  isAutoRefreshing.value = true;
  captureScreen();
  autoTimer = setInterval(() => {
    captureScreen();
  }, Math.max(200, refreshIntervalMs.value));
}

function stopAutoRefresh() {
  isAutoRefreshing.value = false;
  if (autoTimer) {
    clearInterval(autoTimer);
    autoTimer = null;
  }
}

function downloadImage() {
  if (!currentImageData.value) return;
  const a = document.createElement('a');
  a.href = currentImageData.value;
  a.download = `lcd_screenshot_${new Date().toISOString().replace(/[:.]/g, '-')}.png`;
  a.click();
}

onUnmounted(() => {
  stopAutoRefresh();
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-mono text-xs overflow-hidden select-none">
    <!-- Top Action Toolbar -->
    <div class="bg-zinc-900 border-b border-zinc-800 px-4 py-2 flex items-center justify-between gap-3 shrink-0 flex-wrap">
      <div class="flex items-center gap-2 font-bold text-sm text-cyan-400">
        <Monitor class="w-4 h-4 text-cyan-400" />
        <span>{{ t("lcd_title") }}</span>
      </div>

      <!-- Probe Selector -->
      <div class="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded px-2 py-1">
        <span class="text-[10px] text-zinc-400 font-bold shrink-0">SWD:</span>
        <select
          v-model="selectedProbeId"
          class="bg-transparent text-cyan-300 font-bold outline-none text-xs max-w-[200px] truncate cursor-pointer"
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
          class="text-zinc-400 hover:text-cyan-400 p-0.5 rounded transition"
        >
          <RefreshCw class="w-3 h-3" :class="{ 'animate-spin': isScanningProbes }" />
        </button>

        <!-- SWD Clock Frequency Selector -->
        <span class="text-zinc-600 text-[10px] pl-1 border-l border-zinc-800">CLK:</span>
        <select
          v-model.number="swdFrequencyHz"
          class="bg-transparent text-amber-300 font-bold outline-none text-xs cursor-pointer"
          title="SWD 探针传输时钟速率 (显存推荐 10MHz~20MHz)"
        >
          <option v-for="sp in swdFreqPresets" :key="sp.value" :value="sp.value" class="bg-zinc-900 text-zinc-200">
            {{ sp.label }}
          </option>
        </select>
      </div>

      <!-- Sniff From ELF/AXF Button -->
      <button
        @click="handleSniffFromFirmware"
        :disabled="isSniffing"
        class="flex items-center gap-1 px-2 py-1 bg-zinc-900 hover:bg-zinc-800 text-purple-300 border border-purple-800/60 rounded text-xs transition-colors shrink-0"
        title="导入工程编译生成的 .axf / .elf 文件，自动嗅探 LCD 显存变量并填充基地址"
      >
        <span>{{ isSniffing ? '嗅探中...' : '🔍 嗅探 ELF 显存变量' }}</span>
      </button>

      <!-- Parameters Config -->
      <div class="flex items-center gap-2">
        <div class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1">
          <span class="text-[10px] text-zinc-400">{{ t("lcd_base_addr_label") }}</span>
          <input
            v-model="fbAddress"
            type="text"
            placeholder="0x20000000"
            class="w-24 bg-transparent text-cyan-300 font-bold outline-none text-xs"
          />
        </div>

        <div class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1">
          <span class="text-[10px] text-zinc-400">{{ t("lcd_res_label") }}</span>
          <input
            v-model.number="fbWidth"
            type="number"
            class="w-12 bg-transparent text-zinc-200 outline-none text-center"
          />
          <span class="text-zinc-600">×</span>
          <input
            v-model.number="fbHeight"
            type="number"
            class="w-12 bg-transparent text-zinc-200 outline-none text-center"
          />
        </div>

        <div class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1">
          <span class="text-[10px] text-zinc-400">{{ t("lcd_fmt_label") }}</span>
          <select
            v-model="pixelFormat"
            class="bg-transparent text-zinc-200 outline-none cursor-pointer"
          >
            <option value="rgb565" class="bg-zinc-900">RGB565 (16bit)</option>
            <option value="rgb888" class="bg-zinc-900">RGB888 (24bit)</option>
            <option value="argb8888" class="bg-zinc-900">ARGB8888 (32bit)</option>
            <option value="mono" class="bg-zinc-900">{{ t("lcd_fmt_mono") }}</option>
          </select>
        </div>

        <!-- Single Capture Button -->
        <button
          @click="captureScreen"
          :disabled="isCapturing"
          class="flex items-center gap-1.5 px-3 py-1 bg-cyan-600 hover:bg-cyan-500 text-white rounded font-semibold transition-colors disabled:opacity-40"
        >
          <Camera class="w-3.5 h-3.5" :class="{ 'animate-spin': isCapturing }" />
          <span>{{ t("lcd_btn_single") }}</span>
        </button>

        <!-- Continuous Auto Refresh -->
        <button
          @click="toggleAutoRefresh"
          class="flex items-center gap-1.5 px-3 py-1 rounded font-semibold transition-colors border"
          :class="isAutoRefreshing
            ? 'bg-rose-950 text-rose-300 border-rose-700 animate-pulse'
            : 'bg-zinc-800 text-zinc-200 border-zinc-700 hover:bg-zinc-700'"
        >
          <component :is="isAutoRefreshing ? Square : Play" class="w-3.5 h-3.5" />
          <span>{{ isAutoRefreshing ? t('lcd_btn_auto_stop') : t('lcd_btn_auto_start') }}</span>
        </button>

        <!-- Save PNG -->
        <button
          v-if="currentImageData"
          @click="downloadImage"
          class="flex items-center gap-1.5 px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 rounded transition-colors"
          :title="t('lcd_tip_save_png')"
        >
          <Download class="w-3.5 h-3.5 text-zinc-400" />
          <span>{{ t("lcd_btn_save_png") }}</span>
        </button>
      </div>
    </div>

    <!-- Sniff Status Alert -->
    <div v-if="sniffNotice" class="bg-purple-950/60 border-b border-purple-800 text-purple-300 px-4 py-1.5 text-xs flex items-center justify-between">
      <span>{{ sniffNotice }}</span>
      <button @click="sniffNotice = ''" class="text-zinc-500 hover:text-zinc-300 text-xs">✕</button>
    </div>

    <!-- Error Alert -->
    <div v-if="errorMsg" class="bg-rose-950/60 border-b border-rose-800 text-rose-300 px-4 py-2 text-xs flex items-center gap-2">
      <AlertTriangle class="w-4 h-4 text-rose-400 shrink-0" />
      <span>{{ errorMsg }}</span>
    </div>

    <!-- Screen Preview Canvas / Image Stage -->
    <div class="flex-1 bg-zinc-950 flex flex-col items-center justify-center p-6 overflow-auto">
      <div v-if="currentImageData" class="flex flex-col items-center gap-3">
        <!-- Rendered Display Frame -->
        <div class="p-2.5 bg-zinc-900 border-2 border-zinc-700 rounded-xl shadow-2xl relative">
          <img
            :src="currentImageData"
            alt="LCD FrameBuffer Preview"
            class="rounded border border-zinc-800 object-contain max-h-[70vh] shadow-inner"
            :style="{
              imageRendering: 'pixelated',
              width: `${Math.min(fbWidth * 2, 800)}px`
            }"
          />
          <div class="absolute bottom-4 right-4 bg-black/75 px-2 py-0.5 rounded text-[10px] text-zinc-300 font-mono backdrop-blur border border-zinc-800">
            {{ fbWidth }} × {{ fbHeight }} | {{ pixelFormat.toUpperCase() }}
          </div>
        </div>

        <!-- Meta info -->
        <div class="text-[11px] text-zinc-500 font-mono flex items-center gap-4">
          <span>{{ t("lcd_stat_captured") }} <strong class="text-cyan-400">{{ capturedCount }}</strong></span>
          <span>{{ t("lcd_stat_update_time") }} <strong class="text-zinc-300">{{ lastCaptureTime }}</strong></span>
          <span>{{ t("lcd_stat_fb_addr") }} <strong class="text-emerald-400">{{ fbAddress }}</strong></span>
        </div>
      </div>

      <!-- Empty Guide Placeholder -->
      <div v-else class="text-center space-y-3 max-w-md text-zinc-500">
        <Monitor class="w-12 h-12 mx-auto text-zinc-700 animate-pulse" />
        <div class="text-sm font-semibold text-zinc-300">{{ t("lcd_empty_title") }}</div>
        <div class="text-[11px] text-zinc-500 leading-relaxed">
          {{ t("lcd_empty_body") }}
        </div>
      </div>
    </div>
  </div>
</template>
