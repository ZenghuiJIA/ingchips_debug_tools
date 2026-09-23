<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, onActivated, onDeactivated, nextTick } from 'vue';
import { isTauri, safeInvoke } from '../utils/ipc';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import type { SerialRxPayload, PlotterChannel, JScopeSymbol, WaveformPointsPayload } from '../types';
import { parseTelemetryLine, PRESET_CHANNEL_COLORS } from '../utils/telemetryParser';
import {
  Activity,
  Play,
  Pause,
  Trash2,
  Download,
  Dices,
  Eye,
  EyeOff,
  Crosshair,
  Search,
  RefreshCw,
  RotateCcw,
  X,
  FolderOpen,
  Zap,
  Gauge,
  AlertTriangle,
  FileCode,
  Copy,
  Check,
  Sliders
} from '@lucide/vue';

defineProps<{
  isConnected: boolean;
}>();

// --- Rust Protocol Engine State ---
const isProtocolModalOpen = ref<boolean>(false);
const activeProtocolTab = ref<'firewater' | 'justfloat' | 'custom_json' | 'rawdata'>('custom_json');
const isCopied = ref<boolean>(false);
const isRustEngineActive = ref<boolean>(false);
const activeProtocolName = ref<string>('通用默认解析 (内置)');
const protocolApplySuccess = ref<string>('');
const protocolApplyError = ref<string>('');

// Preset JSON protocol configurations
const presetCustomJsonBinary = JSON.stringify({
  name: "Custom_IMU_Binary",
  description: "6轴传感器二进制协议 (0xAA 0x55 帧头 + 16字节定长帧)",
  type: "binary",
  endian: "little",
  frame: {
    header: [170, 85], // 0xAA, 0x55
    fixed_length: 16,
    checksum: {
      type: "sum8",
      offset: 15
    }
  },
  channels: [
    { name: "roll", offset: 2, type: "float32", scale: 1.0, bias: 0.0 },
    { name: "pitch", offset: 6, type: "float32", scale: 1.0, bias: 0.0 },
    { name: "yaw", offset: 10, type: "float32", scale: 1.0, bias: 0.0 },
    { name: "temp", offset: 14, type: "int8", scale: 0.5, bias: 20.0 }
  ]
}, null, 2);

const presetCustomJsonFirewater = JSON.stringify({
  name: "FireWater_Text",
  description: "文本行模式: 逗号分隔浮点/整数或 key:value 键值对",
  type: "firewater",
  endian: "little",
  channels: []
}, null, 2);

const presetCustomJsonJustFloat = JSON.stringify({
  name: "JustFloat_Binary",
  description: "VOFA+ 标准 JustFloat: N个float32 + 固定尾标 00 00 80 7F",
  type: "justfloat",
  endian: "little",
  channels: [
    { name: "CH0", offset: 0, type: "float32", scale: 1.0, bias: 0.0 },
    { name: "CH1", offset: 4, type: "float32", scale: 1.0, bias: 0.0 },
    { name: "CH2", offset: 8, type: "float32", scale: 1.0, bias: 0.0 },
    { name: "CH3", offset: 12, type: "float32", scale: 1.0, bias: 0.0 }
  ]
}, null, 2);

const customProtocolJsonText = ref<string>(presetCustomJsonBinary);

async function applyRustProtocolConfig() {
  protocolApplyError.value = '';
  protocolApplySuccess.value = '';
  try {
    const parsed = JSON.parse(customProtocolJsonText.value);
    await safeInvoke('set_waveform_protocol', { configJson: customProtocolJsonText.value });
    isRustEngineActive.value = true;
    activeProtocolName.value = `Rust后端引擎: ${parsed.name || '自定义协议'}`;
    protocolApplySuccess.value = `已成功下发至 Rust 后端解析器！当前协议: ${parsed.name}`;
    setTimeout(() => {
      protocolApplySuccess.value = '';
    }, 3000);
  } catch (err: any) {
    protocolApplyError.value = `协议配置下发失败: ${err}`;
  }
}

async function resetToDefaultProtocol() {
  try {
    await safeInvoke('clear_waveform_protocol');
    isRustEngineActive.value = false;
    activeProtocolName.value = '通用默认解析 (内置)';
    protocolApplySuccess.value = '已恢复内置默认解析 (ASCII/JustFloat 自动识别)';
    setTimeout(() => {
      protocolApplySuccess.value = '';
    }, 3000);
  } catch (err: any) {
    protocolApplyError.value = `恢复默认失败: ${err}`;
  }
}

// --- Multi-Device Waveform Source Binding State ---
const boundWaveformSource = ref<string>('');
const activePortList = ref<string[]>([]);

async function refreshActivePortList() {
  try {
    const serialList: string[] = await safeInvoke('list_active_serial_sessions') || [];
    let netList: string[] = [];
    try {
      const netSessions: any[] = await safeInvoke('list_network_streams') || [];
      netList = netSessions.filter(s => s.is_connected).map(s => `[NET] ${s.name} (${s.host}:${s.port})`);
    } catch (_) {}

    const combined = [...serialList, ...netList];
    activePortList.value = combined;
    const currentBound: string | null = await safeInvoke('get_waveform_source');
    if (currentBound) {
      boundWaveformSource.value = currentBound;
    } else if (combined.length > 0 && !boundWaveformSource.value) {
      boundWaveformSource.value = combined[0];
      await handleWaveformSourceChange();
    }
  } catch (err) {
    console.error('Failed to list active sessions for waveform binding:', err);
  }
}

async function handleWaveformSourceChange() {
  try {
    await safeInvoke('set_waveform_source', { portName: boundWaveformSource.value || null });
  } catch (err) {
    console.error('Failed to bind waveform source:', err);
  }
}

// --- J-Scope State ---
const isJScopeModalOpen = ref<boolean>(false);
const axfFilePath = ref<string>('');
const isParsingAxf = ref<boolean>(false);
const axfSymbols = ref<JScopeSymbol[]>([]);
const searchKeyword = ref<string>('');
const isSampling = ref<boolean>(false);
const jscopeError = ref<string>('');
const selectedCoreTarget = ref<string>('cortex_m');

const coreTargetOptions = [
  { label: '通用 ARM Cortex-M (PyOCD cortex_m/推荐)', value: 'cortex_m' },
  { label: 'Cortex-M4 (STM32F4/GD32F4/nRF52)', value: 'cortex_m4' },
  { label: 'Cortex-M3 (STM32F1/GD32F1)', value: 'cortex_m3' },
  { label: 'Cortex-M0 / M0+ (STM32F0/RP2040)', value: 'cortex_m0' },
  { label: 'Cortex-M7 (STM32H7/i.MX RT)', value: 'cortex_m7' },
];

// SWD Frequency & Microsecond Sampling Configuration
const swdClockFreq = ref<number>(10000000); // 10 MHz default
const samplePeriodUs = ref<number>(20000); // 20 ms default
const sampleRateWarning = ref<string>('');

const swdFreqOptions = [
  { label: '50 MHz (极速硬件)', value: 50000000 },
  { label: '40 MHz (高速)', value: 40000000 },
  { label: '25 MHz', value: 25000000 },
  { label: '20 MHz', value: 20000000 },
  { label: '10 MHz (推荐标准)', value: 10000000 },
  { label: '5 MHz', value: 5000000 },
  { label: '2 MHz', value: 2000000 },
  { label: '1 MHz (常用稳定)', value: 1000000 },
  { label: '500 kHz', value: 500000 },
  { label: '200 kHz', value: 200000 },
  { label: '100 kHz (长线抗干扰)', value: 100000 },
];

const samplingPeriodPresets = [
  { label: '1 MHz (1 µs 极速采样)', us: 1, rateHz: 1000000 },
  { label: '500 kHz (2 µs)', us: 2, rateHz: 500000 },
  { label: '200 kHz (5 µs)', us: 5, rateHz: 200000 },
  { label: '100 kHz (10 µs)', us: 10, rateHz: 100000 },
  { label: '50 kHz (20 µs)', us: 20, rateHz: 50000 },
  { label: '20 kHz (50 µs)', us: 50, rateHz: 20000 },
  { label: '10 kHz (100 µs)', us: 100, rateHz: 10000 },
  { label: '5 kHz (200 µs)', us: 200, rateHz: 5000 },
  { label: '2 kHz (500 µs)', us: 500, rateHz: 2000 },
  { label: '1 kHz (1 ms)', us: 1000, rateHz: 1000 },
  { label: '500 Hz (2 ms)', us: 2000, rateHz: 500 },
  { label: '200 Hz (5 ms)', us: 5000, rateHz: 200 },
  { label: '100 Hz (10 ms)', us: 10000, rateHz: 100 },
  { label: '50 Hz (20 ms 推荐)', us: 20000, rateHz: 50 },
  { label: '20 Hz (50 ms)', us: 50000, rateHz: 20 },
  { label: '10 Hz (100 ms)', us: 100000, rateHz: 10 },
  { label: '1 Hz (1000 ms)', us: 1000000, rateHz: 1 },
];

function formatFreq(hz: number): string {
  if (hz >= 1000000) return `${(hz / 1000000).toFixed(1)} MHz`;
  if (hz >= 1000) return `${(hz / 1000).toFixed(1)} kHz`;
  return `${hz} Hz`;
}

// Theoretical maximum sampling rate deduced from SWD Clock Frequency and variable count
const maxHardwareSampleRate = computed(() => {
  const selectedCount = Math.max(1, axfSymbols.value.filter(s => s.selected).length);
  const swdHz = Number(swdClockFreq.value) || 10000000;
  // SWD protocol: ~80 cycles per 32-bit transaction + ~1.5us USB packet turnaround overhead
  const singleVarSec = (80 / swdHz) + 1.5e-6;
  const totalScanSec = selectedCount * singleVarSec;
  const maxRateHz = Math.min(1000000, Math.floor(1 / totalScanSec));
  const minPeriodUs = Math.max(1, Math.ceil(totalScanSec * 1000000));

  return {
    maxRateHz,
    minPeriodUs,
    totalScanUs: (totalScanSec * 1000000).toFixed(1),
    selectedCount,
    swdFreqMhz: swdHz >= 1000000 ? `${(swdHz / 1000000).toFixed(1)} MHz` : `${(swdHz / 1000).toFixed(0)} kHz`
  };
});

// Watch SWD clock and variable count: auto-limit sampling rate if it exceeds physical capability
watch([swdClockFreq, () => axfSymbols.value.filter(s => s.selected).length], () => {
  const limit = maxHardwareSampleRate.value;
  const currentRateHz = Math.floor(1000000 / Math.max(1, samplePeriodUs.value));
  if (currentRateHz > limit.maxRateHz) {
    const validPresets = samplingPeriodPresets.filter(p => p.rateHz <= limit.maxRateHz);
    const fallback = validPresets.length > 0 ? validPresets[0] : samplingPeriodPresets[samplingPeriodPresets.length - 1];
    samplePeriodUs.value = fallback.us;
    sampleRateWarning.value = `低 SWD 频率 (${limit.swdFreqMhz}) 无法支持过高采样率，已根据物理总线带宽自动限制为安全采样率: ${formatFreq(fallback.rateHz)} (周期 ${fallback.us >= 1000 ? (fallback.us / 1000) + 'ms' : fallback.us + 'µs'})`;
  } else {
    sampleRateWarning.value = '';
  }
});

async function handlePickAxfFile() {
  try {
    const selected: string | null = await safeInvoke('pick_firmware_file', {
      title: '选择 ARM 固件可执行文件 (.axf / .elf)'
    });
    if (selected) {
      axfFilePath.value = selected;
      await handleParseAxf();
    }
  } catch (err: any) {
    console.error('Pick AXF file error:', err);
  }
}

async function handleParseAxf() {
  if (!axfFilePath.value.trim()) return;
  isParsingAxf.value = true;
  jscopeError.value = '';
  try {
    const res: any = await safeInvoke('jscope_parse_axf', {
      filePath: axfFilePath.value.trim(),
      filterKeyword: searchKeyword.value.trim() || null,
      maxResults: 300
    });
    axfSymbols.value = (res.symbols || []).map((s: any) => ({
      ...s,
      selected: false
    }));
  } catch (err: any) {
    jscopeError.value = `解析 AXF 失败: ${err}`;
  } finally {
    isParsingAxf.value = false;
  }
}

function selectAllSymbols(select: boolean) {
  axfSymbols.value.forEach(s => s.selected = select);
}

async function handleToggleJScopeSampling() {
  if (isSampling.value) {
    // Stop
    try {
      await safeInvoke('jscope_stop_sampling');
    } catch (err) {
      console.error('Stop sampling error:', err);
    }
    isSampling.value = false;
  } else {
    // Start
    const selected = axfSymbols.value.filter(s => s.selected);
    if (selected.length === 0) {
      alert('请至少勾选一个变量进行采样监视');
      return;
    }
    jscopeError.value = '';
    const us = Number(samplePeriodUs.value) || 20000;
    const ms = Math.max(1, Math.round(us / 1000));
    try {
      await safeInvoke('jscope_start_sampling', {
        variables: selected,
        intervalMs: ms,
        intervalUs: us,
        swdFrequencyHz: Number(swdClockFreq.value) || 10000000,
        probeId: null,
        targetOverride: selectedCoreTarget.value || 'cortex_m',
        probeType: null
      });
      isSampling.value = true;
      isJScopeModalOpen.value = false;
    } catch (err: any) {
      jscopeError.value = `启动 J-Scope 采样失败: ${err}`;
    }
  }
}

// --- Plotter State ---
const canvasRef = ref<HTMLCanvasElement | null>(null);
const containerRef = ref<HTMLDivElement | null>(null);

const isPaused = ref<boolean>(false);
const isSimulating = ref<boolean>(false);
const maxPoints = ref<number>(500);
const yAxisMode = ref<'auto' | 'fixed'>('auto');
const fixedMinY = ref<number>(-50);
const fixedMaxY = ref<number>(50);

// Zoom & Pan state
const MAX_BUFFER_POINTS = 50000;
const viewportSpan = ref<number>(500);
const viewportOffset = ref<number>(0);
const autoFollow = ref<boolean>(true);
const yZoomFactor = ref<number>(1.0);
const yPanOffset = ref<number>(0);
const isDragging = ref<boolean>(false);
let dragStartX = 0;
let dragStartY = 0;
let dragStartOffset = 0;
let dragStartYPan = 0;
let lastYRange = 10;

function onMaxPointsChange() {
  viewportSpan.value = Number(maxPoints.value);
  autoFollow.value = true;
}

const channels = ref<PlotterChannel[]>([]);
const receivedSamplesCount = ref<number>(0);
const fps = ref<number>(60);

// --- Real-time Measurement & FFT Spectrum State (Powered by Rust Native DSP) ---
export interface WaveformMeasurements {
  max: number;
  min: number;
  vpp: number;
  mean: number;
  rms: number;
  frequency: number | null;
  period_sec: number | null;
  duty_cycle_percent: number | null;
}

export interface FftPoint {
  freq_hz: number;
  magnitude: number;
  db: number;
}

export interface HarmonicInfo {
  order: number;
  freq_hz: number;
  magnitude: number;
  dbc: number;
}

export interface FftAnalysisResult {
  spectrum: FftPoint[];
  fundamental_freq: number | null;
  fundamental_mag: number | null;
  harmonics: HarmonicInfo[];
  thd_percent: number | null;
  nyquist_hz: number;
  resolution_hz: number;
}

const plotterDisplayMode = ref<'time' | 'fft'>('time');
const selectedMeasureChannelId = ref<string>('');
const selectedWindowFunction = ref<string>('hanning');
const fftSizeOption = ref<number>(1024);

const liveMeasurements = ref<WaveformMeasurements>({
  max: 0,
  min: 0,
  vpp: 0,
  mean: 0,
  rms: 0,
  frequency: null,
  period_sec: null,
  duty_cycle_percent: null,
});

const liveFftResult = ref<FftAnalysisResult | null>(null);
let dspTimer: any = null;

// Hover tooltip
const mouseX = ref<number | null>(null);
const mouseY = ref<number | null>(null);
const hoveredData = ref<{ x: number; y: number; values: { name: string; color: string; val: number }[] } | null>(null);

// High Refresh Rate & Downsampling State
const fpsTarget = ref<'vsync' | '120hz' | '60hz' | '30hz'>('vsync');
const downsampleMode = ref<'none' | 'smart_minmax' | '2x' | '5x' | '10x'>('smart_minmax');

let unlistenRx: UnlistenFn | null = null;
let unlistenPoints: UnlistenFn | null = null;
let simTimer: any = null;
let animFrameId: number | null = null;
let renderTimerId: any = null;
let lastFpsTime = performance.now();
let framesRendered = 0;

// --- Color Allocation ---
function getChannelColor(index: number): string {
  return PRESET_CHANNEL_COLORS[index % PRESET_CHANNEL_COLORS.length];
}

// --- Data Ingestion ---
function ingestDataPoint(record: Record<string, number>, timestamp: number) {
  receivedSamplesCount.value++;
  lastDataIngestTime = performance.now();

  for (const [key, val] of Object.entries(record)) {
    let ch = channels.value.find(c => c.name === key);
    if (!ch) {
      if (channels.value.length >= 8) continue; // Limit to 8 channels
      ch = {
        id: `ch_${Date.now()}_${Math.random().toString(36).slice(2, 5)}`,
        name: key,
        color: getChannelColor(channels.value.length),
        visible: true,
        points: [],
        lastValue: val,
        minValue: val,
        maxValue: val,
        avgValue: val
      };
      channels.value.push(ch);
    }

    ch.lastValue = val;
    ch.minValue = Math.min(ch.minValue, val);
    ch.maxValue = Math.max(ch.maxValue, val);

    if (!isPaused.value) {
      ch.points.push({ t: timestamp, v: val });
      // Batch slice rather than calling shift() on each incoming point (O(1) amortized vs O(N) memory copy)
      if (ch.points.length > MAX_BUFFER_POINTS + 1000) {
        ch.points = ch.points.slice(ch.points.length - MAX_BUFFER_POINTS);
      }
    }
  }
}

// Partial text and binary buffer from serial stream
let partialLineBuffer = '';
let rawByteAccumulator = new Uint8Array(0);

// Helper to copy C demo code
function copyDemoCode(code: string) {
  navigator.clipboard.writeText(code);
  isCopied.value = true;
  setTimeout(() => {
    isCopied.value = false;
  }, 2000);
}

// C Demo implementations for protocols
const cDemoFireWater = `#include <stdio.h>

// VOFA+ FireWater 格式: 支持打印逗号分隔浮点/整数，或 key:value 键值对
// 注意: 必须以 \\n 换行符作为帧结束标志!

void Send_Waveform_FireWater(float ch0, float ch1, int ch2) {
    // 格式1: 纯 CSV 模式 (自动对应 CH0, CH1, CH2)
    printf("%.2f,%.2f,%d\\r\\n", ch0, ch1, ch2);

    // 格式2: 自定义通道名称键值对模式
    // printf("speed:%.2f,current:%.2f,rpm:%d\\r\\n", ch0, ch1, ch2);
}
`;

const cDemoJustFloat = `#include <stdint.h>
#include <string.h>

// VOFA+ JustFloat 极速二进制协议:
// 数据帧格式: 小端 float32 数组 + 4 字节固定帧尾 {0x00, 0x00, 0x80, 0x7F} (IEEE-754 +Inf)
// 优点: 零格式化开销，直接 DMA 发送，极大减轻 MCU CPU 负担与串口带宽消耗

#define CH_COUNT 4

typedef struct __attribute__((packed)) {
    float channels[CH_COUNT];
    uint8_t tail[4];
} JustFloatFrame_t;

void Send_Waveform_JustFloat(float ch0, float ch1, float ch2, float ch3) {
    JustFloatFrame_t frame;
    frame.channels[0] = ch0;
    frame.channels[1] = ch1;
    frame.channels[2] = ch2;
    frame.channels[3] = ch3;

    // VOFA+ JustFloat 标准 4-byte 帧尾: 0x00, 0x00, 0x80, 0x7F
    frame.tail[0] = 0x00;
    frame.tail[1] = 0x00;
    frame.tail[2] = 0x80;
    frame.tail[3] = 0x7F;

    // 调用底层串口/RTT发送:
    // HAL_UART_Transmit(&huart1, (uint8_t*)&frame, sizeof(frame), 100);
    // SEGGER_RTT_Write(0, &frame, sizeof(frame));
}
`;

const cDemoRawData = `// RawData 纯字节流透传模式:
// 不做波形数学解析，直接在终端中显示原始 HEX 字节或 ASCII 打印。
`;

// Handle raw bytes coming from Serial (Supports ASCII FireWater & Binary JustFloat)
function processIncomingBytes(raw: Uint8Array) {
  const now = performance.now();

  // 1. Check for JustFloat binary frame tail: 0x00 0x00 0x80 0x7F
  let combined: Uint8Array;
  if (rawByteAccumulator.length > 0) {
    combined = new Uint8Array(rawByteAccumulator.length + raw.length);
    combined.set(rawByteAccumulator, 0);
    combined.set(raw, rawByteAccumulator.length);
  } else {
    combined = raw;
  }

  let tailIdx = -1;
  for (let i = 0; i <= combined.length - 4; i++) {
    if (combined[i] === 0x00 && combined[i + 1] === 0x00 && combined[i + 2] === 0x80 && combined[i + 3] === 0x7f) {
      tailIdx = i;
      break;
    }
  }

  if (tailIdx >= 4 && (tailIdx % 4 === 0)) {
    // Found JustFloat frame!
    const floatCount = tailIdx / 4;
    const view = new DataView(combined.buffer, combined.byteOffset, tailIdx);
    const point: Record<string, number> = {};
    for (let c = 0; c < floatCount && c < 8; c++) {
      const fVal = view.getFloat32(c * 4, true); // Little-endian
      if (!isNaN(fVal) && isFinite(fVal)) {
        point[`CH${c}`] = parseFloat(fVal.toFixed(3));
      }
    }
    if (Object.keys(point).length > 0) {
      ingestDataPoint(point, now);
    }
    // Slice past the tail
    rawByteAccumulator = new Uint8Array(combined.subarray(tailIdx + 4));
    return;
  }

  // Prevent memory unbounded growth if no tail found
  if (combined.length > 4096) {
    rawByteAccumulator = new Uint8Array(combined.subarray(combined.length - 128));
  } else {
    rawByteAccumulator = new Uint8Array(combined);
  }

  // 2. Fall back to ASCII Line-based parsing (FireWater / CSV / Key-Value / JSON)
  const text = new TextDecoder('utf-8', { fatal: false }).decode(raw);
  partialLineBuffer += text;

  const lines = partialLineBuffer.split('\n');
  partialLineBuffer = lines.pop() || '';

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const parsed = parseTelemetryLine(trimmed);
    if (parsed) {
      ingestDataPoint(parsed, now);
    }
  }
}

// --- Simulation Mode for Regression Verification ---
let simStep = 0;
function toggleSimulation() {
  if (isSimulating.value) {
    if (simTimer) clearInterval(simTimer);
    simTimer = null;
    isSimulating.value = false;
  } else {
    isSimulating.value = true;
    simTimer = setInterval(() => {
      simStep += 0.05;
      const now = performance.now();
      const sineVal = Math.sin(simStep) * 40 + Math.cos(simStep * 0.5) * 10;
      const cosVal = Math.cos(simStep * 0.8) * 30;
      const noise = (Math.random() - 0.5) * 6;
      const triangle = ((simStep % (Math.PI * 2)) / (Math.PI * 2) * 50) - 25;

      ingestDataPoint({
        'SinWave': parseFloat(sineVal.toFixed(2)),
        'CosWave': parseFloat(cosVal.toFixed(2)),
        'TriWave': parseFloat((triangle + noise).toFixed(2))
      }, now);
    }, 20); // 50 Hz
  }
}

// --- Clear & Export ---
function clearPlot() {
  for (const ch of channels.value) {
    ch.points = [];
    ch.minValue = 0;
    ch.maxValue = 0;
  }
  receivedSamplesCount.value = 0;
  liveFftResult.value = null;
}

/**
 * Periodically compute high-precision waveform measurements & FFT in Rust backend
 */
async function triggerDspCalculations() {
  if (channels.value.length === 0) return;

  // Determine active target channel
  let targetCh = channels.value.find(c => c.id === selectedMeasureChannelId.value);
  if (!targetCh) {
    targetCh = channels.value.find(c => c.visible) || channels.value[0];
    if (targetCh) selectedMeasureChannelId.value = targetCh.id;
  }
  if (!targetCh || targetCh.points.length < 16) return;

  // Extract raw values slice
  const sliceLen = Math.min(targetCh.points.length, fftSizeOption.value);
  const rawValues = targetCh.points.slice(targetCh.points.length - sliceLen).map(p => p.v);

  // Estimate sample rate from time intervals or configured period
  let sampleRateHz = 50.0; // Fallback
  if (isSampling.value && samplePeriodUs.value > 0) {
    sampleRateHz = 1000000.0 / samplePeriodUs.value;
  } else if (targetCh.points.length >= 2) {
    const p1 = targetCh.points[targetCh.points.length - 1].t;
    const p0 = targetCh.points[targetCh.points.length - 2].t;
    const dt = (p1 - p0) / 1000.0;
    if (dt > 1e-4) {
      sampleRateHz = 1.0 / dt;
    }
  }

  try {
    // 1. Rust Time-domain measurements
    const meas: WaveformMeasurements = await safeInvoke('dsp_measure_waveform', {
      samples: rawValues,
      sampleRateHz
    });
    liveMeasurements.value = meas;

    // 2. Rust FFT Spectrum calculation (if in FFT view or visible)
    if (plotterDisplayMode.value === 'fft' || rawValues.length >= 64) {
      const fftRes: FftAnalysisResult = await safeInvoke('dsp_compute_fft', {
        samples: rawValues,
        sampleRateHz,
        fftSize: fftSizeOption.value,
        windowType: selectedWindowFunction.value
      });
      liveFftResult.value = fftRes;
    }
  } catch (err) {
    // Graceful degradation
  }
}

function exportCsv() {
  if (channels.value.length === 0) {
    alert('暂无通道数据可导出');
    return;
  }

  // Find max points
  const maxLen = Math.max(...channels.value.map(c => c.points.length));
  if (maxLen === 0) {
    alert('暂无采样点数据');
    return;
  }

  const header = ['SampleIndex', ...channels.value.map(c => c.name)].join(',');
  const rows: string[] = [header];

  for (let i = 0; i < maxLen; i++) {
    const row = [i.toString()];
    for (const ch of channels.value) {
      const pt = ch.points[i];
      row.push(pt !== undefined ? pt.v.toString() : '');
    }
    rows.push(row.join(','));
  }

  const blob = new Blob([rows.join('\n')], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `telemetry_data_${new Date().toISOString().replace(/[:.]/g, '-')}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// Dirty check & rendering activity timestamp to save GPU and CPU resources
let lastDataIngestTime = performance.now();

// --- Canvas Rendering Loop ---
function scheduleNextRender() {
  const now = performance.now();
  const isIdle = (now - lastDataIngestTime > 1500) && !isSimulating.value && !isDragging.value && !isSampling.value;

  if (isIdle) {
    // When idle (no new data & no user interaction), throttle to 10 FPS (~100ms) to let GPU rest
    renderTimerId = setTimeout(() => {
      animFrameId = requestAnimationFrame(renderCanvas);
    }, 100);
    return;
  }

  if (fpsTarget.value === '120hz') {
    // 120 FPS target: ~8.33ms
    renderTimerId = setTimeout(() => {
      animFrameId = requestAnimationFrame(renderCanvas);
    }, 4);
  } else if (fpsTarget.value === '60hz') {
    renderTimerId = setTimeout(() => {
      animFrameId = requestAnimationFrame(renderCanvas);
    }, 12);
  } else if (fpsTarget.value === '30hz') {
    renderTimerId = setTimeout(() => {
      animFrameId = requestAnimationFrame(renderCanvas);
    }, 28);
  } else {
    // Native VSync (60Hz ~ 144Hz+ depending on monitor)
    animFrameId = requestAnimationFrame(renderCanvas);
  }
}

function renderCanvas() {
  framesRendered++;
  const now = performance.now();
  if (now - lastFpsTime >= 1000) {
    fps.value = framesRendered;
    framesRendered = 0;
    lastFpsTime = now;
  }

  const canvas = canvasRef.value;
  if (!canvas) {
    scheduleNextRender();
    return;
  }

  const ctx = canvas.getContext('2d');
  if (!ctx) {
    scheduleNextRender();
    return;
  }

  const width = canvas.width;
  const height = canvas.height;
  const dpr = window.devicePixelRatio || 1;

  ctx.clearRect(0, 0, width, height);

  // Background
  ctx.fillStyle = '#09090b';
  ctx.fillRect(0, 0, width, height);

  // Padding
  const padLeft = 60 * dpr;
  const padRight = 20 * dpr;
  const padTop = 20 * dpr;
  const padBottom = 30 * dpr;

  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  if (plotW <= 0 || plotH <= 0) {
    scheduleNextRender();
    return;
  }

  // Calculate max channel length
  let maxChannelLen = 0;
  for (const ch of channels.value) {
    if (ch.points.length > maxChannelLen) maxChannelLen = ch.points.length;
  }

  // Update viewport offset
  if (autoFollow.value) {
    viewportOffset.value = Math.max(0, maxChannelLen - viewportSpan.value);
  } else {
    const maxPossibleOffset = Math.max(0, maxChannelLen - 5);
    if (viewportOffset.value > maxPossibleOffset) {
      viewportOffset.value = maxPossibleOffset;
    }
  }

  const curOffset = viewportOffset.value;
  const curSpan = Math.max(10, viewportSpan.value);

  // Determine Y range from currently visible points
  let minY = Infinity;
  let maxY = -Infinity;

  if (yAxisMode.value === 'fixed') {
    minY = fixedMinY.value;
    maxY = fixedMaxY.value;
  } else {
    for (const ch of channels.value) {
      if (!ch.visible || ch.points.length === 0) continue;
      const pStart = Math.max(0, Math.floor(curOffset));
      const pEnd = Math.min(ch.points.length, Math.ceil(curOffset + curSpan));
      for (let i = pStart; i < pEnd; i++) {
        const v = ch.points[i].v;
        if (v < minY) minY = v;
        if (v > maxY) maxY = v;
      }
    }
    if (minY === Infinity || maxY === -Infinity) {
      minY = -10;
      maxY = 10;
    } else if (minY === maxY) {
      minY -= 1;
      maxY += 1;
    } else {
      // Add 8% padding
      const diff = maxY - minY;
      minY -= diff * 0.08;
      maxY += diff * 0.08;
    }
  }

  const rawYDiff = maxY - minY || 2;
  const yCenter = (minY + maxY) / 2 + yPanOffset.value;
  const halfRange = (rawYDiff / 2) / yZoomFactor.value;
  const curMinY = yCenter - halfRange;
  const curMaxY = yCenter + halfRange;
  const yRange = curMaxY - curMinY || 1;
  lastYRange = yRange;

  // 1. Draw Grid Lines (Horizontal)
  const numGridLines = 6;
  ctx.strokeStyle = '#27272a';
  ctx.lineWidth = 1 * dpr;
  ctx.font = `${10 * dpr}px monospace`;
  ctx.fillStyle = '#71717a';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';

  for (let i = 0; i <= numGridLines; i++) {
    const ratio = i / numGridLines;
    const y = padTop + ratio * plotH;
    const val = curMaxY - ratio * yRange;

    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(width - padRight, y);
    ctx.stroke();

    ctx.fillText(val.toFixed(1), padLeft - 8 * dpr, y);
  }

  // Zero-line if visible
  if (curMinY < 0 && curMaxY > 0) {
    const zeroY = padTop + (curMaxY / yRange) * plotH;
    ctx.strokeStyle = '#52525b';
    ctx.lineWidth = 1.5 * dpr;
    ctx.setLineDash([4 * dpr, 4 * dpr]);
    ctx.beginPath();
    ctx.moveTo(padLeft, zeroY);
    ctx.lineTo(width - padRight, zeroY);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // Vertical Grid Lines (Time / Sample Index)
  const numXGridLines = 5;
  ctx.strokeStyle = '#1e1e24';
  ctx.lineWidth = 1 * dpr;
  ctx.fillStyle = '#71717a';
  ctx.font = `${9 * dpr}px monospace`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';

  for (let i = 0; i <= numXGridLines; i++) {
    const ratio = i / numXGridLines;
    const x = padLeft + ratio * plotW;
    const sampleIdx = Math.round(curOffset + ratio * curSpan);

    ctx.beginPath();
    ctx.moveTo(x, padTop);
    ctx.lineTo(x, height - padBottom);
    ctx.stroke();

    ctx.fillText(`#${sampleIdx}`, x, height - padBottom + 6 * dpr);
  }

  const visibleChannels = channels.value.filter(c => c.visible && c.points.length > 1);

  // 2. Draw Waveforms or FFT Spectrum (Clipped to plot area)
  ctx.save();
  ctx.beginPath();
  ctx.rect(padLeft, padTop, plotW, plotH);
  ctx.clip();

  if (plotterDisplayMode.value === 'fft') {
    // --- Draw FFT Spectrum ---
    if (liveFftResult.value && liveFftResult.value.spectrum.length > 0) {
      const spec = liveFftResult.value.spectrum;
      const maxMag = Math.max(0.1, ...spec.map(p => p.magnitude));

      // Draw Spectrum Curve
      ctx.strokeStyle = '#38bdf8';
      ctx.lineWidth = 1.5 * dpr;
      ctx.beginPath();

      for (let i = 0; i < spec.length; i++) {
        const px = padLeft + (i / (spec.length - 1)) * plotW;
        const py = padTop + (1.0 - (spec[i].magnitude / maxMag)) * (plotH * 0.9);
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.stroke();

      // Highlight Fundamental and Harmonics
      for (const h of liveFftResult.value.harmonics) {
        const binRatio = h.freq_hz / liveFftResult.value.nyquist_hz;
        if (binRatio >= 0 && binRatio <= 1) {
          const hx = padLeft + binRatio * plotW;
          const hy = padTop + (1.0 - (h.magnitude / maxMag)) * (plotH * 0.9);

          // Marker Point
          ctx.fillStyle = h.order === 1 ? '#f59e0b' : '#a855f7';
          ctx.beginPath();
          ctx.arc(hx, hy, 4 * dpr, 0, Math.PI * 2);
          ctx.fill();

          // Label
          ctx.font = `${9 * dpr}px monospace`;
          ctx.textAlign = 'center';
          ctx.fillText(h.order === 1 ? `f0:${Math.round(h.freq_hz)}Hz` : `${h.order}f`, hx, hy - 6 * dpr);
        }
      }
    } else {
      ctx.fillStyle = '#71717a';
      ctx.font = `${12 * dpr}px monospace`;
      ctx.textAlign = 'center';
      ctx.fillText('FFT 计算中，需采集至少 16 个点...', padLeft + plotW / 2, padTop + plotH / 2);
    }
  } else {
    // --- Normal Time-Domain Waveforms with Downsampling Support ---
    for (const ch of visibleChannels) {
      ctx.strokeStyle = ch.color;
      ctx.lineWidth = 2 * dpr;
      ctx.lineJoin = 'round';
      ctx.beginPath();

      const pts = ch.points;
      const pStart = Math.max(0, Math.floor(curOffset) - 1);
      const pEnd = Math.min(pts.length - 1, Math.ceil(curOffset + curSpan) + 1);
      const totalVisiblePts = pEnd - pStart + 1;

      // Decide downsampling strategy
      const mode = downsampleMode.value;
      const step = mode === '2x' ? 2 : mode === '5x' ? 5 : mode === '10x' ? 10 : 1;

      if (mode === 'smart_minmax' && totalVisiblePts > (plotW / dpr) * 2) {
        // High-density: Min-Max Pixel Bucket Decimation (Preserves spikes & envelopes at 120Hz)
        const numBuckets = Math.min(Math.floor(plotW / dpr), totalVisiblePts);
        const ptsPerBucket = totalVisiblePts / numBuckets;

        let isFirst = true;
        for (let b = 0; b < numBuckets; b++) {
          const bStart = pStart + Math.floor(b * ptsPerBucket);
          const bEnd = Math.min(pEnd, pStart + Math.floor((b + 1) * ptsPerBucket));

          let minVal = pts[bStart].v;
          let maxVal = pts[bStart].v;
          for (let k = bStart + 1; k < bEnd; k++) {
            const v = pts[k].v;
            if (v < minVal) minVal = v;
            if (v > maxVal) maxVal = v;
          }

          const midIdx = (bStart + bEnd) / 2;
          const px = padLeft + ((midIdx - curOffset) / (curSpan - 1)) * plotW;
          const pyMin = padTop + ((curMaxY - minVal) / yRange) * plotH;
          const pyMax = padTop + ((curMaxY - maxVal) / yRange) * plotH;

          if (isFirst) {
            ctx.moveTo(px, pyMin);
            if (pyMin !== pyMax) ctx.lineTo(px, pyMax);
            isFirst = false;
          } else {
            ctx.lineTo(px, pyMin);
            ctx.lineTo(px, pyMax);
          }
        }
      } else {
        // Standard or Stepped Downsampling
        let isFirst = true;
        for (let i = pStart; i <= pEnd; i += step) {
          const px = padLeft + ((i - curOffset) / (curSpan - 1)) * plotW;
          const py = padTop + ((curMaxY - pts[i].v) / yRange) * plotH;

          if (isFirst) {
            ctx.moveTo(px, py);
            isFirst = false;
          } else {
            ctx.lineTo(px, py);
          }
        }
        // Always connect the absolute final point
        if (pEnd > pStart && ((pEnd - pStart) % step !== 0)) {
          const px = padLeft + ((pEnd - curOffset) / (curSpan - 1)) * plotW;
          const py = padTop + ((curMaxY - pts[pEnd].v) / yRange) * plotH;
          ctx.lineTo(px, py);
        }
      }
      ctx.stroke();
    }
  }
  ctx.restore();

  // 3. Draw Hover Crosshair & Values
  if (mouseX.value !== null && mouseX.value >= padLeft && mouseX.value <= width - padRight) {
    const hoverX = mouseX.value;
    ctx.strokeStyle = '#06b6d4';
    ctx.lineWidth = 1 * dpr;
    ctx.setLineDash([2 * dpr, 2 * dpr]);
    ctx.beginPath();
    ctx.moveTo(hoverX, padTop);
    ctx.lineTo(hoverX, height - padBottom);
    ctx.stroke();
    ctx.setLineDash([]);

    // Calculate nearest index in visible data
    const relX = (hoverX - padLeft) / plotW;
    const targetIdx = Math.round(curOffset + relX * (curSpan - 1));

    const hoverVals: { name: string; color: string; val: number }[] = [];
    for (const ch of visibleChannels) {
      if (targetIdx >= 0 && targetIdx < ch.points.length) {
        hoverVals.push({
          name: ch.name,
          color: ch.color,
          val: ch.points[targetIdx].v
        });
      }
    }

    if (hoverVals.length > 0) {
      hoveredData.value = {
        x: hoverX / dpr,
        y: (mouseY.value || padTop) / dpr,
        values: hoverVals
      };
    } else {
      hoveredData.value = null;
    }
  } else {
    hoveredData.value = null;
  }

  scheduleNextRender();
}

// --- Canvas Resizing & Mouse Interaction ---
function resizeCanvas() {
  const canvas = canvasRef.value;
  const container = containerRef.value;
  if (!canvas || !container) return;

  const rect = container.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
}

function handleWheel(e: WheelEvent) {
  e.preventDefault();
  const canvas = canvasRef.value;
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const padLeft = 60 * dpr;
  const padRight = 20 * dpr;
  const plotW = (rect.width * dpr) - padLeft - padRight;
  if (plotW <= 0) return;

  const mouseCanvasX = (e.clientX - rect.left) * dpr;
  const mouseRelX = mouseCanvasX - padLeft;
  const ratio = Math.max(0, Math.min(1, mouseRelX / plotW));

  if (e.shiftKey) {
    // Shift + Wheel = Zoom Y axis
    const factor = e.deltaY < 0 ? 1.2 : 0.833;
    yZoomFactor.value = Math.max(0.05, Math.min(50, yZoomFactor.value * factor));
    return;
  }

  // Normal Wheel = Zoom X axis (time) centered at mouse cursor!
  const zoomFactor = e.deltaY < 0 ? 0.8 : 1.25;
  const oldSpan = viewportSpan.value;
  const newSpan = Math.max(10, Math.min(MAX_BUFFER_POINTS, Math.round(oldSpan * zoomFactor)));

  if (newSpan !== oldSpan) {
    const newOffset = viewportOffset.value + ratio * (oldSpan - newSpan);
    viewportSpan.value = newSpan;
    viewportOffset.value = Math.max(0, Math.round(newOffset));
    autoFollow.value = false;
  }
}

function handleMouseDown(e: MouseEvent) {
  if (e.button !== 0 && e.button !== 1) return;
  const canvas = canvasRef.value;
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const padLeft = 60 * dpr;
  const padRight = 20 * dpr;
  const mouseCanvasX = (e.clientX - rect.left) * dpr;

  if (mouseCanvasX >= padLeft && mouseCanvasX <= (rect.width * dpr) - padRight) {
    isDragging.value = true;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    dragStartOffset = viewportOffset.value;
    dragStartYPan = yPanOffset.value;
    autoFollow.value = false;
  }
}

function handleMouseMove(e: MouseEvent) {
  const canvas = canvasRef.value;
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  mouseX.value = (e.clientX - rect.left) * dpr;
  mouseY.value = (e.clientY - rect.top) * dpr;

  if (isDragging.value) {
    const deltaX = e.clientX - dragStartX;
    const deltaY = e.clientY - dragStartY;
    const padLeft = 60 * dpr;
    const padRight = 20 * dpr;
    const padTop = 20 * dpr;
    const padBottom = 30 * dpr;
    const plotW = (rect.width * dpr) - padLeft - padRight;
    const plotH = (rect.height * dpr) - padTop - padBottom;

    if (plotW > 0) {
      const pointsShift = (deltaX * dpr / plotW) * viewportSpan.value;
      viewportOffset.value = Math.max(0, Math.round(dragStartOffset - pointsShift));
    }

    if (plotH > 0 && lastYRange > 0) {
      const valShift = (deltaY * dpr / plotH) * (lastYRange / yZoomFactor.value);
      yPanOffset.value = dragStartYPan + valShift;
    }
  }
}

function handleMouseUp() {
  isDragging.value = false;
}

function handleMouseLeave() {
  isDragging.value = false;
  mouseX.value = null;
  mouseY.value = null;
  hoveredData.value = null;
}

function handleDoubleClick() {
  resetView();
}

function resumeAutoFollow() {
  autoFollow.value = true;
  yPanOffset.value = 0;
}

function resetView() {
  viewportSpan.value = maxPoints.value;
  yPanOffset.value = 0;
  yZoomFactor.value = 1.0;
  autoFollow.value = true;
}

// --- Lifecycle ---
onMounted(async () => {
  nextTick(() => {
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);
    animFrameId = requestAnimationFrame(renderCanvas);
  });

  await refreshActivePortList();

  if (isTauri()) {
    try {
      unlistenRx = await listen<SerialRxPayload>('serial-rx', (event) => {
        // Filter by bound waveform port if set
        if (boundWaveformSource.value && event.payload.port && event.payload.port !== boundWaveformSource.value) {
          return;
        }
        // Only run frontend fallback parsing if Rust engine is not already doing it
        if (!isRustEngineActive.value) {
          const raw = new Uint8Array(event.payload.data);
          processIncomingBytes(raw);
        }
      });

      unlistenPoints = await listen<WaveformPointsPayload>('waveform-points', (event) => {
        // Filter by bound waveform port if set
        if (boundWaveformSource.value && event.payload.port && event.payload.port !== boundWaveformSource.value) {
          return;
        }
        const now = performance.now();
        for (const pt of event.payload.points) {
          ingestDataPoint(pt, now);
        }
      });
    } catch (err) {
      console.warn('Failed to listen to serial events in Plotter:', err);
    }
  }

  // Periodic background DSP trigger (200ms interval) for real-time measurements & FFT
  dspTimer = setInterval(() => {
    triggerDspCalculations();
  }, 200);
});

// Resource governance: Suspend GPU Canvas rendering and DSP computations when tab is inactive
onDeactivated(() => {
  if (dspTimer) {
    clearInterval(dspTimer);
    dspTimer = null;
  }
  if (renderTimerId) {
    clearTimeout(renderTimerId);
    renderTimerId = null;
  }
  if (animFrameId) {
    cancelAnimationFrame(animFrameId);
    animFrameId = null;
  }
});

onActivated(() => {
  nextTick(() => {
    resizeCanvas();
    if (!animFrameId) {
      animFrameId = requestAnimationFrame(renderCanvas);
    }
    if (!dspTimer) {
      dspTimer = setInterval(() => {
        triggerDspCalculations();
      }, 200);
    }
  });
});

onUnmounted(() => {
  if (dspTimer) clearInterval(dspTimer);
  if (renderTimerId) clearTimeout(renderTimerId);
  if (unlistenRx) unlistenRx();
  if (unlistenPoints) unlistenPoints();
  if (simTimer) clearInterval(simTimer);
  if (animFrameId) cancelAnimationFrame(animFrameId);
  window.removeEventListener('resize', resizeCanvas);
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-mono text-xs overflow-hidden select-none">
    <!-- Top Plotter Control Toolbar -->
    <div class="bg-zinc-900 border-b border-zinc-800 px-4 py-2 flex items-center justify-between gap-3 shrink-0">
      <!-- Left: Title & Simulation -->
      <div class="flex items-center gap-3">
        <div class="flex items-center gap-1.5 text-zinc-200 font-semibold">
          <Activity class="w-4 h-4 text-cyan-400" />
          <span>实时波形示波器</span>
        </div>

        <!-- Waveform Source Binding Selector -->
        <div class="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded px-2 py-0.5">
          <span class="text-[11px] text-zinc-400">数据源:</span>
          <select
            v-model="boundWaveformSource"
            @focus="refreshActivePortList"
            @change="handleWaveformSourceChange"
            class="bg-transparent text-cyan-300 text-xs font-semibold outline-none cursor-pointer max-w-[150px]"
            title="选择要绘制波形的目标串口或RTT通道"
          >
            <option value="" class="bg-zinc-900 text-zinc-400">自动监听全部活跃流</option>
            <option
              v-for="p in activePortList"
              :key="p"
              :value="p"
              class="bg-zinc-900 text-zinc-200"
            >
              {{ p }}
            </option>
          </select>
        </div>

        <div class="h-4 w-px bg-zinc-800"></div>

        <!-- Run / Pause Button -->
        <button
          @click="isPaused = !isPaused"
          class="px-2.5 py-1 rounded text-xs font-semibold flex items-center gap-1.5 transition-colors border shadow-sm"
          :class="isPaused 
            ? 'bg-amber-950 text-amber-300 border-amber-800 hover:bg-amber-900' 
            : 'bg-emerald-950 text-emerald-300 border-emerald-800 hover:bg-emerald-900'"
        >
          <component :is="isPaused ? Play : Pause" class="w-3.5 h-3.5" />
          <span>{{ isPaused ? '恢复采集' : '暂停画面' }}</span>
        </button>

        <!-- Simulation Signal Generator (Regression Test) -->
        <button
          @click="toggleSimulation"
          class="px-2.5 py-1 rounded text-xs font-semibold flex items-center gap-1.5 transition-colors border shadow-sm"
          :class="isSimulating 
            ? 'bg-cyan-950 text-cyan-300 border-cyan-700 animate-pulse' 
            : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
          title="启动/停止内置虚拟信号源，验证波形解析与丝滑渲染"
        >
          <Dices class="w-3.5 h-3.5 text-cyan-400" />
          <span>{{ isSimulating ? '仿真测试中 (50Hz)' : '🎲 启动仿真信号' }}</span>
        </button>

        <!-- J-Scope Variable Sampling Button -->
        <button
          @click="isJScopeModalOpen = true"
          class="px-2.5 py-1 rounded text-xs font-semibold flex items-center gap-1.5 transition-colors border shadow-sm"
          :class="isSampling
            ? 'bg-purple-950 text-purple-300 border-purple-600 animate-pulse'
            : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
          title="导入 Keil MDK .axf 符号表，周期无侵入读取单片机 RAM 变量绘制波形"
        >
          <Crosshair class="w-3.5 h-3.5 text-purple-400" />
          <span>{{ isSampling ? '🎯 采样中...' : '🎯 变量自动捕获' }}</span>
        </button>

        <!-- Protocol Engine & C Demo Button -->
        <button
          @click="isProtocolModalOpen = true"
          class="px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-cyan-300 border border-zinc-700 rounded text-xs flex items-center gap-1 transition-colors"
          title="查看波形示波器支持的数据协议规范及 C 语言单片机驱动 Demo (兼容 VOFA+ FireWater / JustFloat)"
        >
          <FileCode class="w-3.5 h-3.5 text-cyan-400" />
          <span>📜 波形协议规范</span>
        </button>

        <!-- Clear -->
        <button
          @click="clearPlot"
          class="px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 rounded text-xs flex items-center gap-1"
          title="清空当前波形缓存"
        >
          <Trash2 class="w-3 h-3 text-zinc-400" />
          <span>清空</span>
        </button>

        <!-- Export CSV -->
        <button
          @click="exportCsv"
          class="px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 rounded text-xs flex items-center gap-1"
          title="导出采集到的通道数据为 CSV"
        >
          <Download class="w-3 h-3 text-zinc-400" />
          <span>导出CSV</span>
        </button>

        <!-- Reset View / Zoom -->
        <button
          @click="resetView"
          class="px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 rounded text-xs flex items-center gap-1 transition-colors"
          title="双击画布或点击此按钮重置缩放与平移"
        >
          <RotateCcw class="w-3 h-3 text-zinc-400" />
          <span>复位视图</span>
        </button>
      </div>

      <!-- Right Controls: Display Mode, Window, Points, Y Axis, Metrics -->
      <div class="flex items-center gap-3">
        <!-- Plotter Display Mode: Time Domain vs FFT Spectrum -->
        <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded p-0.5">
          <button
            @click="plotterDisplayMode = 'time'"
            class="px-2 py-0.5 rounded text-[11px] transition-colors"
            :class="plotterDisplayMode === 'time' ? 'bg-zinc-800 text-cyan-400 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            title="时域波形走势图"
          >
            📈 时域
          </button>
          <button
            @click="plotterDisplayMode = 'fft'"
            class="px-2 py-0.5 rounded text-[11px] transition-colors"
            :class="plotterDisplayMode === 'fft' ? 'bg-zinc-800 text-amber-400 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            title="FFT 频域幅值谱分析 (Rust 原生微秒级加速)"
          >
            📊 FFT 频谱
          </button>
        </div>

        <!-- Window Function Selector (when FFT is active) -->
        <div v-if="plotterDisplayMode === 'fft'" class="flex items-center gap-1">
          <span class="text-amber-400">窗函数:</span>
          <select
            v-model="selectedWindowFunction"
            class="bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5 text-zinc-200 focus:outline-none"
          >
            <option value="hanning">汉宁窗 (Hanning/推荐)</option>
            <option value="hamming">海明窗 (Hamming)</option>
            <option value="blackman_harris">Blackman-Harris (92dB)</option>
            <option value="flattop">Flat Top (幅值标定)</option>
            <option value="rectangular">矩形窗 (无窗)</option>
          </select>
        </div>

        <!-- Points Window Selector -->
        <div v-if="plotterDisplayMode === 'time'" class="flex items-center gap-1">
          <span>点数:</span>
          <select
            v-model="maxPoints"
            @change="onMaxPointsChange"
            class="bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5 text-zinc-200 focus:outline-none"
          >
            <option :value="200">200 点</option>
            <option :value="500">500 点</option>
            <option :value="1000">1000 点</option>
            <option :value="2000">2000 点</option>
            <option :value="5000">5000 点</option>
            <option :value="10000">10000 点</option>
            <option :value="20000">20000 点</option>
          </select>
        </div>

        <!-- Downsampling Mode Selector -->
        <div v-if="plotterDisplayMode === 'time'" class="flex items-center gap-1">
          <span class="text-sky-400">降采样:</span>
          <select
            v-model="downsampleMode"
            class="bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5 text-sky-200 focus:outline-none"
            title="大数据量降采样渲染，保持高刷丝滑"
          >
            <option value="smart_minmax">智能Min-Max分桶(极速推荐)</option>
            <option value="none">全量原始点(无降采样)</option>
            <option value="2x">2倍降采样 (1/2)</option>
            <option value="5x">5倍降采样 (1/5)</option>
            <option value="10x">10倍降采样 (1/10)</option>
          </select>
        </div>

        <!-- High-FPS Target Selector -->
        <div class="flex items-center gap-1">
          <span class="text-emerald-400">刷新率:</span>
          <select
            v-model="fpsTarget"
            class="bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5 text-emerald-300 focus:outline-none font-bold"
            title="目标渲染帧率，120Hz 极速电竞级丝滑刷新"
          >
            <option value="vsync">VSync 屏幕原生</option>
            <option value="120hz">⚡ 120 FPS 极速高刷</option>
            <option value="60hz">60 FPS 均衡</option>
            <option value="30hz">30 FPS 低功耗</option>
          </select>
        </div>

        <!-- Y Axis Mode -->
        <div v-if="plotterDisplayMode === 'time'" class="flex items-center gap-1">
          <span>Y轴:</span>
          <select
            v-model="yAxisMode"
            class="bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5 text-zinc-200 focus:outline-none"
          >
            <option value="auto">自适应缩放</option>
            <option value="fixed">固定 ±50</option>
          </select>
        </div>

        <div class="h-3 w-px bg-zinc-800"></div>

        <!-- Metrics -->
        <div class="flex items-center gap-2 font-mono">
          <span>帧率: <strong class="text-emerald-400 font-bold">{{ fps }}</strong> FPS</span>
          <span>样本: <strong class="text-zinc-300">{{ receivedSamplesCount }}</strong></span>
        </div>
      </div>
    </div>

    <!-- Active Channels Bar / Legend -->
    <div class="bg-zinc-900/60 border-b border-zinc-800 px-4 py-1.5 flex items-center gap-3 overflow-x-auto shrink-0">
      <span class="text-zinc-500 text-[11px] shrink-0">通道 ({{ channels.length }}/8):</span>

      <div v-if="channels.length === 0" class="text-zinc-600 italic text-[11px]">
        等待串口数据流 (支持 CSV: <code>12.3, 45.6</code> 或 键值对: <code>roll:12.3, pitch:45.6</code>) 或点击上方仿真信号
      </div>

      <div
        v-for="ch in channels"
        :key="ch.id"
        class="flex items-center gap-1.5 px-2 py-0.5 rounded border text-xs bg-zinc-950 transition-all"
        :style="{ borderColor: ch.visible ? ch.color + '66' : '#27272a' }"
      >
        <!-- Toggle visibility -->
        <button
          @click="ch.visible = !ch.visible"
          class="hover:opacity-80 transition-opacity"
          :title="ch.visible ? '点击隐藏通道' : '点击显示通道'"
        >
          <component :is="ch.visible ? Eye : EyeOff" class="w-3 h-3" :style="{ color: ch.color }" />
        </button>

        <span class="font-bold font-mono" :style="{ color: ch.color }">{{ ch.name }}</span>
        <span class="text-zinc-400 font-mono text-[11px]">
          = <strong class="text-zinc-200">{{ ch.lastValue.toFixed(2) }}</strong>
        </span>
        <span class="text-zinc-600 text-[10px]">
          [{{ ch.minValue.toFixed(1) }} ~ {{ ch.maxValue.toFixed(1) }}]
        </span>
      </div>
    </div>

    <!-- Main Canvas Area -->
    <div
      ref="containerRef"
      class="flex-1 relative overflow-hidden select-none"
      :class="isDragging ? 'cursor-grabbing' : 'cursor-crosshair'"
      @wheel.prevent="handleWheel"
      @mousedown="handleMouseDown"
      @mousemove="handleMouseMove"
      @mouseup="handleMouseUp"
      @mouseleave="handleMouseLeave"
      @dblclick="handleDoubleClick"
    >
      <canvas ref="canvasRef" class="absolute inset-0 w-full h-full block"></canvas>

      <!-- Floating HUD when autoFollow is paused by dragging/zooming -->
      <div
        v-if="!autoFollow"
        class="absolute top-3 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 px-3 py-1 rounded-full bg-cyan-950/90 border border-cyan-700 text-cyan-300 text-xs shadow-xl backdrop-blur"
      >
        <span>🔍 自由浏览模式 (已暂停自动跟随)</span>
        <button
          @click.stop="resumeAutoFollow"
          class="px-2 py-0.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-full text-[10px] font-semibold transition-colors shadow-sm"
        >
          恢复跟随最新
        </button>
      </div>

      <!-- Hover Tooltip Floating HUD -->
      <div
        v-if="hoveredData"
        class="absolute pointer-events-none bg-zinc-900/95 border border-zinc-700 shadow-xl rounded px-2.5 py-1.5 text-[11px] backdrop-blur z-20"
        :style="{
          left: `${Math.min(hoveredData.x + 12, (containerRef?.clientWidth || 800) - 150)}px`,
          top: `${Math.max(hoveredData.y - 40, 10)}px`
        }"
      >
        <div class="text-zinc-400 font-mono text-[10px] border-b border-zinc-800 pb-0.5 mb-1">
          光标位置数据
        </div>
        <div
          v-for="item in hoveredData.values"
          :key="item.name"
          class="flex items-center justify-between gap-3 font-mono"
        >
          <span :style="{ color: item.color }">{{ item.name }}:</span>
          <strong class="text-zinc-100">{{ item.val.toFixed(2) }}</strong>
        </div>
      </div>
    </div>

    <!-- Real-time Oscilloscope Measurement Bar (Powered by Rust Native DSP) -->
    <div class="bg-zinc-950 border-t border-zinc-800 px-4 py-1.5 flex items-center justify-between gap-4 text-xs font-mono shrink-0 select-text overflow-x-auto">
      <div class="flex items-center gap-1.5 shrink-0">
        <span class="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold">标尺测量:</span>
        <select
          v-model="selectedMeasureChannelId"
          class="bg-zinc-900 border border-zinc-800 rounded px-1.5 py-0.5 text-zinc-200 text-[11px] outline-none"
        >
          <option v-for="c in channels" :key="c.id" :value="c.id">{{ c.name }}</option>
        </select>
      </div>

      <!-- Measurement Values Grid -->
      <div class="flex items-center gap-4 text-[11px] flex-wrap">
        <div><span class="text-zinc-500">Vpp:</span> <strong class="text-emerald-400">{{ liveMeasurements.vpp.toFixed(2) }}</strong></div>
        <div><span class="text-zinc-500">Max:</span> <strong class="text-zinc-300">{{ liveMeasurements.max.toFixed(2) }}</strong></div>
        <div><span class="text-zinc-500">Min:</span> <strong class="text-zinc-300">{{ liveMeasurements.min.toFixed(2) }}</strong></div>
        <div><span class="text-zinc-500">Mean:</span> <strong class="text-zinc-300">{{ liveMeasurements.mean.toFixed(2) }}</strong></div>
        <div><span class="text-zinc-500">RMS:</span> <strong class="text-cyan-400">{{ liveMeasurements.rms.toFixed(2) }}</strong></div>

        <!-- Frequency & Period -->
        <div>
          <span class="text-zinc-500">频率:</span>
          <strong class="text-amber-400 ml-1">
            {{ liveMeasurements.frequency !== null ? (liveMeasurements.frequency >= 1000 ? `${(liveMeasurements.frequency / 1000).toFixed(2)} kHz` : `${liveMeasurements.frequency.toFixed(1)} Hz`) : '--' }}
          </strong>
        </div>

        <div>
          <span class="text-zinc-500">周期:</span>
          <strong class="text-amber-300 ml-1">
            {{ liveMeasurements.period_sec !== null ? (liveMeasurements.period_sec < 0.001 ? `${(liveMeasurements.period_sec * 1000000).toFixed(1)} µs` : `${(liveMeasurements.period_sec * 1000).toFixed(2)} ms`) : '--' }}
          </strong>
        </div>

        <!-- Duty Cycle -->
        <div>
          <span class="text-zinc-500">占空比:</span>
          <strong class="text-purple-400 ml-1">
            {{ liveMeasurements.duty_cycle_percent !== null ? `${liveMeasurements.duty_cycle_percent.toFixed(1)}%` : '--' }}
          </strong>
        </div>

        <!-- THD Distortion -->
        <div>
          <span class="text-zinc-500">THD失真:</span>
          <strong class="text-rose-400 ml-1">
            {{ liveFftResult?.thd_percent !== null && liveFftResult?.thd_percent !== undefined ? `${liveFftResult.thd_percent.toFixed(2)}%` : '--' }}
          </strong>
        </div>
      </div>
    </div>

    <!-- Bottom Instructions Footer -->
    <div class="bg-zinc-900 border-t border-zinc-800 px-4 py-1 text-[10px] text-zinc-500 flex items-center justify-between">
      <span>💡 交互: <code>滚轮缩放时间轴</code> | <code>Shift+滚轮缩放Y轴</code> | <code>左键拖拽平移</code> | <code>双击复位</code></span>
      <span v-if="!isConnected && !isSampling" class="text-amber-500">⚠ 串口未连接，可点击 [🎯 变量自动捕获] 直连单片机 RAM 采样</span>
      <span v-else-if="isSampling" class="text-purple-400 font-semibold animate-pulse">● SWD 高速变量监视中...</span>
      <span v-else class="text-emerald-400">● 串口已就绪，正在监听数据流</span>
    </div>

    <!-- J-Scope Variable Sampling Modal Dialog -->
    <div
      v-if="isJScopeModalOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
    >
      <div class="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-2xl shadow-2xl flex flex-col max-h-[85vh] overflow-hidden">
        <!-- Dialog Header -->
        <div class="px-5 py-3.5 border-b border-zinc-800 flex items-center justify-between bg-zinc-950/60">
          <div class="flex items-center gap-2 text-zinc-100 font-bold text-sm">
            <Crosshair class="w-4 h-4 text-purple-400" />
            <span>变量自动捕获设置 (SWD 硬件实时变量监视)</span>
          </div>
          <button
            @click="isJScopeModalOpen = false"
            class="text-zinc-400 hover:text-zinc-200 p-1 rounded hover:bg-zinc-800 transition-colors"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <!-- Dialog Body -->
        <div class="p-5 flex-1 overflow-y-auto space-y-4">
          <!-- Target Core / Architecture Selection -->
          <div class="space-y-1.5">
            <label class="block text-[11px] text-zinc-400 font-medium flex items-center justify-between">
              <span>目标单片机内核架构 (自动兼容 Generic Cortex-M 调度):</span>
              <span class="text-purple-400 text-[10px]">自动处理 M4/M3/M0 目标类型</span>
            </label>
            <select
              v-model="selectedCoreTarget"
              class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-zinc-200 text-xs outline-none focus:border-purple-500 font-mono"
            >
              <option v-for="c in coreTargetOptions" :key="c.value" :value="c.value">
                {{ c.label }}
              </option>
            </select>
          </div>

          <!-- File selection -->
          <div class="space-y-1.5">
            <label class="block text-[11px] text-zinc-400 font-medium">
              Keil MDK 固件可执行文件物理路径 (.axf / .elf)
            </label>
            <div class="flex items-center gap-2">
              <div class="relative flex-1 flex items-center">
                <input
                  v-model="axfFilePath"
                  type="text"
                  placeholder="点击右侧浏览选择文件，或粘贴绝对路径 (.axf / .elf)"
                  class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 pr-24 text-zinc-200 text-xs outline-none focus:border-purple-500 font-mono"
                />
                <button
                  @click="handlePickAxfFile"
                  type="button"
                  class="absolute right-1 px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-purple-400 rounded text-xs flex items-center gap-1 transition-colors border border-zinc-700/80"
                  title="打开系统文件选择对话框"
                >
                  <FolderOpen class="w-3.5 h-3.5" />
                  <span>浏览选择</span>
                </button>
              </div>
              <button
                @click="handleParseAxf"
                :disabled="isParsingAxf || !axfFilePath.trim()"
                class="flex items-center gap-1.5 px-3 py-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded text-xs font-medium transition-colors disabled:opacity-40 shrink-0"
              >
                <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isParsingAxf }" />
                <span>解析符号表</span>
              </button>
            </div>
            <div class="text-[10px] text-zinc-500">
              通过解析 DWARF 符号表自动定位 SRAM 中的全局和静态变量地址与数据类型，零侵入无须单片机串口打印。
            </div>
          </div>

          <!-- Error message if any -->
          <div v-if="jscopeError" class="p-2.5 rounded bg-rose-950/60 border border-rose-800 text-rose-300 text-xs">
            {{ jscopeError }}
          </div>

          <!-- Symbols List & Filter -->
          <div v-if="axfSymbols.length > 0" class="space-y-2">
            <div class="flex items-center justify-between pt-2 border-t border-zinc-800">
              <div class="flex items-center gap-2">
                <span class="font-semibold text-zinc-300">找到的 RAM 变量 ({{ axfSymbols.length }} 个):</span>
                <button
                  @click="selectAllSymbols(true)"
                  class="text-[11px] text-purple-400 hover:text-purple-300"
                >
                  全选
                </button>
                <span class="text-zinc-600">|</span>
                <button
                  @click="selectAllSymbols(false)"
                  class="text-[11px] text-zinc-400 hover:text-zinc-300"
                >
                  全不选
                </button>
              </div>

              <!-- Search filter input -->
              <div class="flex items-center gap-1.5">
                <Search class="w-3.5 h-3.5 text-zinc-500" />
                <input
                  v-model="searchKeyword"
                  @keyup.enter="handleParseAxf"
                  placeholder="过滤变量名..."
                  class="bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-[11px] text-zinc-200 outline-none focus:border-purple-500 w-32"
                />
              </div>
            </div>

            <!-- Table of Symbols -->
            <div class="border border-zinc-800 rounded-lg overflow-hidden max-h-56 overflow-y-auto bg-zinc-950">
              <table class="w-full text-left text-xs font-mono">
                <thead class="bg-zinc-900/80 text-zinc-400 text-[10px] border-b border-zinc-800">
                  <tr>
                    <th class="p-2 w-8">选</th>
                    <th class="p-2">变量名称</th>
                    <th class="p-2">SRAM物理地址</th>
                    <th class="p-2">大小</th>
                    <th class="p-2">解析类型</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-zinc-800/60">
                  <tr
                    v-for="sym in axfSymbols"
                    :key="sym.name"
                    @click="sym.selected = !sym.selected"
                    class="hover:bg-zinc-900/60 cursor-pointer transition-colors"
                    :class="{ 'bg-purple-950/20': sym.selected }"
                  >
                    <td class="p-2" @click.stop>
                      <input
                        type="checkbox"
                        v-model="sym.selected"
                        class="accent-purple-500 rounded cursor-pointer"
                      />
                    </td>
                    <td class="p-2 font-bold text-zinc-200">{{ sym.name }}</td>
                    <td class="p-2 text-emerald-400">{{ sym.address }}</td>
                    <td class="p-2 text-zinc-400">{{ sym.size }} 字节</td>
                    <td class="p-2">
                      <select
                        v-model="sym.type"
                        @click.stop
                        class="bg-zinc-900 border border-zinc-700 rounded px-1.5 py-0.5 text-[10.5px] text-zinc-300 outline-none"
                      >
                        <option value="int32">int32</option>
                        <option value="uint32">uint32</option>
                        <option value="float32">float32</option>
                        <option value="int16">int16</option>
                        <option value="uint16">uint16</option>
                        <option value="int8">int8</option>
                        <option value="uint8">uint8</option>
                        <option value="int64">int64</option>
                        <option value="uint64">uint64</option>
                        <option value="float64">float64</option>
                      </select>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          <!-- Sampling Settings & SWD Frequency Deduction -->
          <div class="space-y-3 pt-2 border-t border-zinc-800">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
              <!-- SWD Clock Frequency Setting -->
              <div class="flex items-center gap-2">
                <label class="text-[11px] text-zinc-400 font-medium flex items-center gap-1 shrink-0">
                  <Zap class="w-3.5 h-3.5 text-amber-400" />
                  <span>SWD 时钟频率:</span>
                </label>
                <select
                  v-model.number="swdClockFreq"
                  class="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-xs text-zinc-200 outline-none focus:border-purple-500 font-mono"
                >
                  <option v-for="opt in swdFreqOptions" :key="opt.value" :value="opt.value">
                    {{ opt.label }}
                  </option>
                </select>
              </div>

              <!-- Sampling Period / Frequency Setting -->
              <div class="flex items-center gap-2">
                <label class="text-[11px] text-zinc-400 font-medium flex items-center gap-1 shrink-0">
                  <Gauge class="w-3.5 h-3.5 text-cyan-400" />
                  <span>采样周期/速率:</span>
                </label>
                <select
                  v-model.number="samplePeriodUs"
                  class="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-xs text-zinc-200 outline-none focus:border-purple-500 font-mono"
                >
                  <option
                    v-for="p in samplingPeriodPresets"
                    :key="p.us"
                    :value="p.us"
                    :disabled="p.rateHz > maxHardwareSampleRate.maxRateHz"
                  >
                    {{ p.label }}
                    {{ p.rateHz > maxHardwareSampleRate.maxRateHz ? ' (🚫 超过 SWD 物理带宽)' : '' }}
                  </option>
                </select>
              </div>
            </div>

            <!-- Physics Deduction & Hardware Limit Status Banner -->
            <div class="p-2.5 rounded bg-zinc-950 border border-zinc-800/90 text-[11px] space-y-1">
              <div class="flex items-center justify-between text-zinc-300">
                <span class="flex items-center gap-1.5 text-purple-300 font-medium">
                  <Gauge class="w-3.5 h-3.5 text-purple-400" />
                  <span>SWD 硬件在环通信带宽反推:</span>
                </span>
                <span class="font-mono text-zinc-400 text-[10px]">
                  已选 <strong class="text-purple-400">{{ maxHardwareSampleRate.selectedCount }}</strong> 变量 | 单轮耗时: <strong class="text-zinc-200">{{ maxHardwareSampleRate.totalScanUs }} µs</strong>
                </span>
              </div>
              <div class="text-[10px] text-zinc-400 font-mono">
                当前 SWD 时钟 (<strong class="text-zinc-300">{{ maxHardwareSampleRate.swdFreqMhz }}</strong>) 下，
                理论物理最高采样率: <strong class="text-emerald-400 font-bold">{{ formatFreq(maxHardwareSampleRate.maxRateHz) }}</strong>
                (最小物理周期: <strong class="text-cyan-400">{{ maxHardwareSampleRate.minPeriodUs }} µs</strong>)
              </div>
              <div v-if="sampleRateWarning" class="pt-1.5 text-[11px] text-amber-400 flex items-center gap-1.5 border-t border-zinc-800/80">
                <AlertTriangle class="w-3.5 h-3.5 text-amber-400 shrink-0" />
                <span>{{ sampleRateWarning }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Dialog Footer -->
        <div class="px-5 py-3 border-t border-zinc-800 bg-zinc-950/60 flex items-center justify-end gap-2">
          <button
            @click="isJScopeModalOpen = false"
            class="px-3 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs transition-colors"
          >
            取消
          </button>

          <button
            @click="handleToggleJScopeSampling"
            class="px-4 py-1.5 rounded text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-sm"
            :class="isSampling
              ? 'bg-rose-600 hover:bg-rose-500 text-white'
              : 'bg-purple-600 hover:bg-purple-500 text-white'"
          >
            <Crosshair class="w-3.5 h-3.5" />
            <span>{{ isSampling ? '停止当前采样' : '开始变量自动捕获监视' }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Protocol Specification & C Demo Modal Dialog -->
    <div
      v-if="isProtocolModalOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4"
    >
      <div class="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-3xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden">
        <!-- Dialog Header -->
        <div class="px-5 py-3.5 border-b border-zinc-800 flex items-center justify-between bg-zinc-950/60">
          <div class="flex items-center gap-2 text-zinc-100 font-bold text-sm">
            <FileCode class="w-4 h-4 text-cyan-400" />
            <span>示波器波形通信协议规范 & 单片机 C 驱动 Demo (兼容 VOFA+)</span>
          </div>
          <button
            @click="isProtocolModalOpen = false"
            class="text-zinc-400 hover:text-zinc-200 p-1 rounded hover:bg-zinc-800 transition-colors"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <!-- Protocol Tabs -->
        <div class="flex items-center px-5 border-b border-zinc-800 bg-zinc-950/40 text-xs font-medium">
          <button
            @click="activeProtocolTab = 'custom_json'"
            class="px-4 py-2.5 border-b-2 transition-colors flex items-center gap-1.5"
            :class="activeProtocolTab === 'custom_json' ? 'border-purple-500 text-purple-300 font-bold' : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <Sliders class="w-3.5 h-3.5" />
            <span>⚙️ Rust 协议引擎 (JSON 自定义)</span>
          </button>
          <button
            @click="activeProtocolTab = 'firewater'"
            class="px-4 py-2.5 border-b-2 transition-colors flex items-center gap-1.5"
            :class="activeProtocolTab === 'firewater' ? 'border-cyan-500 text-cyan-300 font-bold' : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <span>🔥 FireWater (ASCII)</span>
          </button>
          <button
            @click="activeProtocolTab = 'justfloat'"
            class="px-4 py-2.5 border-b-2 transition-colors flex items-center gap-1.5"
            :class="activeProtocolTab === 'justfloat' ? 'border-emerald-500 text-emerald-300 font-bold' : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <span>⚡ JustFloat (二进制)</span>
          </button>
          <button
            @click="activeProtocolTab = 'rawdata'"
            class="px-4 py-2.5 border-b-2 transition-colors flex items-center gap-1.5"
            :class="activeProtocolTab === 'rawdata' ? 'border-amber-500 text-amber-300 font-bold' : 'border-transparent text-zinc-400 hover:text-zinc-200'"
          >
            <span>📄 RawData (纯透传流)</span>
          </button>
        </div>

        <!-- Dialog Body -->
        <div class="p-5 flex-1 overflow-y-auto space-y-4 text-xs font-mono">
          <!-- Custom JSON Protocol Engine for Rust Backend -->
          <div v-if="activeProtocolTab === 'custom_json'" class="space-y-3">
            <div class="p-3 bg-purple-950/40 border border-purple-800/80 rounded text-purple-200 space-y-1">
              <div class="font-bold flex items-center justify-between text-purple-300">
                <span class="flex items-center gap-1.5">
                  <Sliders class="w-4 h-4 text-purple-400" />
                  <span>Rust 后端协议引擎声明式配置 (JSON):</span>
                </span>
                <span class="text-[10px] px-2 py-0.5 rounded font-mono" :class="isRustEngineActive ? 'bg-emerald-950 border border-emerald-800 text-emerald-300' : 'bg-zinc-800 text-zinc-400'">
                  {{ isRustEngineActive ? '● 后端引擎已激活' : '○ 未启用 (当前为前端默认解析)' }}
                </span>
              </div>
              <div class="text-[11px] text-zinc-300">
                定义帧头 (<code>header</code>)、帧尾 (<code>tail</code>)、固定包长 (<code>fixed_length</code>)、校验和及各通道类型与偏移量。
                配置将直接下发至 <strong>Rust 后端后台线程</strong> 极速硬件级流式解析，彻底消除前端 JS 运算压力！
              </div>
            </div>

            <!-- Quick Template Presets -->
            <div class="flex items-center justify-between gap-2 pt-1 text-[11px]">
              <span class="text-zinc-400 shrink-0 font-medium">加载官方协议模版:</span>
              <div class="flex items-center gap-1.5 flex-wrap">
                <button
                  @click="customProtocolJsonText = presetCustomJsonBinary"
                  class="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-purple-300 border border-zinc-700 transition-colors"
                >
                  🚀 0xAA55 六轴传感器 (二进制)
                </button>
                <button
                  @click="customProtocolJsonText = presetCustomJsonJustFloat"
                  class="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-emerald-300 border border-zinc-700 transition-colors"
                >
                  ⚡ JustFloat 二进制浮点
                </button>
                <button
                  @click="customProtocolJsonText = presetCustomJsonFirewater"
                  class="px-2 py-1 rounded bg-zinc-800 hover:bg-zinc-700 text-cyan-300 border border-zinc-700 transition-colors"
                >
                  🔥 FireWater 文本 CSV
                </button>
              </div>
            </div>

            <!-- JSON Editor Area -->
            <div class="space-y-1.5">
              <div class="flex items-center justify-between text-zinc-400">
                <span>协议引擎 JSON 定义:</span>
                <span class="text-[10px] text-zinc-500">支持 float32/int16/uint16/int32/uint8/scale/bias</span>
              </div>
              <textarea
                v-model="customProtocolJsonText"
                rows="12"
                class="w-full bg-zinc-950 border border-zinc-800 rounded p-3 text-purple-200 text-xs font-mono outline-none focus:border-purple-500 leading-relaxed resize-y"
                placeholder="在此编写或粘贴 JSON 协议定义..."
              ></textarea>
            </div>

            <!-- Status message -->
            <div v-if="protocolApplySuccess" class="p-2.5 rounded bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs">
              {{ protocolApplySuccess }}
            </div>
            <div v-if="protocolApplyError" class="p-2.5 rounded bg-rose-950/60 border border-rose-800 text-rose-300 text-xs">
              {{ protocolApplyError }}
            </div>

            <!-- Actions -->
            <div class="flex items-center justify-between pt-1">
              <button
                @click="resetToDefaultProtocol"
                class="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded text-xs transition-colors"
              >
                恢复内置默认解析
              </button>
              <button
                @click="applyRustProtocolConfig"
                class="px-4 py-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded text-xs font-semibold flex items-center gap-1.5 transition-colors shadow-sm"
              >
                <Sliders class="w-3.5 h-3.5" />
                <span>下发配置至 Rust 后端解析器</span>
              </button>
            </div>
          </div>

          <!-- FireWater Spec & Demo -->
          <div v-if="activeProtocolTab === 'firewater'" class="space-y-3">
            <div class="p-3 bg-cyan-950/30 border border-cyan-800/60 rounded text-cyan-200 space-y-1">
              <div class="font-bold flex items-center gap-1 text-cyan-300">
                <span>🔥 FireWater 协议说明:</span>
              </div>
              <div>格式 1: <code>&lt;任意前缀&gt;:ch0,ch1,ch2...\\n</code> 或 <code>ch0,ch1,ch2...\\n</code></div>
              <div>格式 2 (键值对): <code>roll:12.3, pitch:45.6, yaw:-7.8\\n</code></div>
              <div class="text-[11px] text-cyan-400/80">⚠️ 重点：波形解析器以 <code>\\n</code> 换行作为一帧数据的结束标志。</div>
            </div>

            <div class="space-y-1.5">
              <div class="flex items-center justify-between text-zinc-400">
                <span>STM32 / GD32 / 通用 C 驱动代码示例:</span>
                <button
                  @click="copyDemoCode(cDemoFireWater)"
                  class="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 transition-colors"
                >
                  <component :is="isCopied ? Check : Copy" class="w-3 h-3 text-emerald-400" />
                  <span>{{ isCopied ? '已复制' : '复制代码' }}</span>
                </button>
              </div>
              <pre class="p-3 bg-zinc-950 rounded border border-zinc-800 text-emerald-300 overflow-x-auto text-[11px] leading-relaxed">{{ cDemoFireWater }}</pre>
            </div>
          </div>

          <!-- JustFloat Spec & Demo -->
          <div v-if="activeProtocolTab === 'justfloat'" class="space-y-3">
            <div class="p-3 bg-emerald-950/30 border border-emerald-800/60 rounded text-emerald-200 space-y-1">
              <div class="font-bold flex items-center gap-1 text-emerald-300">
                <span>⚡ JustFloat 极速二进制协议规范:</span>
              </div>
              <div>数据结构：小端 <code>float32[N]</code> 数组 + 4 字节固定帧尾 <code>{ 0x00, 0x00, 0x80, 0x7F }</code> (IEEE-754 +Inf)。</div>
              <div class="text-[11px] text-emerald-400/80">🚀 极速优势：无需 <code>printf</code> 浮点字符串格式化，MCU 可直接通过 DMA 或 RTT 发送，最高可达 1000Hz+。</div>
            </div>

            <div class="space-y-1.5">
              <div class="flex items-center justify-between text-zinc-400">
                <span>C 语言实现结构体与发送函数:</span>
                <button
                  @click="copyDemoCode(cDemoJustFloat)"
                  class="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 transition-colors"
                >
                  <component :is="isCopied ? Check : Copy" class="w-3 h-3 text-emerald-400" />
                  <span>{{ isCopied ? '已复制' : '复制代码' }}</span>
                </button>
              </div>
              <pre class="p-3 bg-zinc-950 rounded border border-zinc-800 text-emerald-300 overflow-x-auto text-[11px] leading-relaxed">{{ cDemoJustFloat }}</pre>
            </div>
          </div>

          <!-- RawData Spec & Demo -->
          <div v-if="activeProtocolTab === 'rawdata'" class="space-y-3">
            <div class="p-3 bg-amber-950/30 border border-amber-800/60 rounded text-amber-200 space-y-1">
              <div class="font-bold text-amber-300">📄 RawData 纯字节流透传:</div>
              <div>不做波形数学采样解析，适用于串口终端打印与纯 HEX 字节流调试需求。</div>
            </div>
            <pre class="p-3 bg-zinc-950 rounded border border-zinc-800 text-zinc-300 overflow-x-auto text-[11px] leading-relaxed">{{ cDemoRawData }}</pre>
          </div>
        </div>

        <!-- Dialog Footer -->
        <div class="px-5 py-3 border-t border-zinc-800 bg-zinc-950/60 flex items-center justify-end">
          <button
            @click="isProtocolModalOpen = false"
            class="px-4 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs transition-colors"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
