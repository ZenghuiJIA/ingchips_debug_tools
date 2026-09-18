<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick } from 'vue';
import { isTauri } from '../utils/ipc';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import type { SerialRxPayload, PlotterChannel } from '../types';
import { parseTelemetryLine, PRESET_CHANNEL_COLORS } from '../utils/telemetryParser';
import {
  Activity,
  Play,
  Pause,
  Trash2,
  Download,
  Dices,
  Eye,
  EyeOff
} from '@lucide/vue';

defineProps<{
  isConnected: boolean;
}>();

// --- Plotter State ---
const canvasRef = ref<HTMLCanvasElement | null>(null);
const containerRef = ref<HTMLDivElement | null>(null);

const isPaused = ref<boolean>(false);
const isSimulating = ref<boolean>(false);
const maxPoints = ref<number>(500);
const yAxisMode = ref<'auto' | 'fixed'>('auto');
const fixedMinY = ref<number>(-50);
const fixedMaxY = ref<number>(50);

const channels = ref<PlotterChannel[]>([]);
const receivedSamplesCount = ref<number>(0);
const fps = ref<number>(60);

// Hover tooltip
const mouseX = ref<number | null>(null);
const mouseY = ref<number | null>(null);
const hoveredData = ref<{ x: number; y: number; values: { name: string; color: string; val: number }[] } | null>(null);

let unlistenRx: UnlistenFn | null = null;
let simTimer: any = null;
let animFrameId: number | null = null;
let lastFpsTime = performance.now();
let framesRendered = 0;

// Partial text buffer from serial stream
let partialLineBuffer = '';

// --- Color Allocation ---
function getChannelColor(index: number): string {
  return PRESET_CHANNEL_COLORS[index % PRESET_CHANNEL_COLORS.length];
}

// --- Data Ingestion ---
function ingestDataPoint(record: Record<string, number>, timestamp: number) {
  receivedSamplesCount.value++;

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
      if (ch.points.length > maxPoints.value) {
        ch.points.shift();
      }
    }
  }
}

// Handle raw bytes coming from Serial
function processIncomingBytes(raw: Uint8Array) {
  const text = new TextDecoder('utf-8', { fatal: false }).decode(raw);
  partialLineBuffer += text;

  const lines = partialLineBuffer.split('\n');
  // Keep the last incomplete fragment in buffer
  partialLineBuffer = lines.pop() || '';

  const now = performance.now();
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

// --- Canvas Rendering Loop ---
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
    animFrameId = requestAnimationFrame(renderCanvas);
    return;
  }

  const ctx = canvas.getContext('2d');
  if (!ctx) {
    animFrameId = requestAnimationFrame(renderCanvas);
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
    animFrameId = requestAnimationFrame(renderCanvas);
    return;
  }

  // Determine Y range
  let minY = Infinity;
  let maxY = -Infinity;

  if (yAxisMode.value === 'fixed') {
    minY = fixedMinY.value;
    maxY = fixedMaxY.value;
  } else {
    for (const ch of channels.value) {
      if (!ch.visible || ch.points.length === 0) continue;
      for (const p of ch.points) {
        if (p.v < minY) minY = p.v;
        if (p.v > maxY) maxY = p.v;
      }
    }
    if (minY === Infinity || maxY === -Infinity) {
      minY = -10;
      maxY = 10;
    } else if (minY === maxY) {
      minY -= 1;
      maxY += 1;
    } else {
      // Add 10% padding
      const diff = maxY - minY;
      minY -= diff * 0.08;
      maxY += diff * 0.08;
    }
  }

  const yRange = maxY - minY || 1;

  // 1. Draw Grid Lines
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
    const val = maxY - ratio * yRange;

    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(width - padRight, y);
    ctx.stroke();

    ctx.fillText(val.toFixed(1), padLeft - 8 * dpr, y);
  }

  // Zero-line if visible
  if (minY < 0 && maxY > 0) {
    const zeroY = padTop + (maxY / yRange) * plotH;
    ctx.strokeStyle = '#52525b';
    ctx.lineWidth = 1.5 * dpr;
    ctx.setLineDash([4 * dpr, 4 * dpr]);
    ctx.beginPath();
    ctx.moveTo(padLeft, zeroY);
    ctx.lineTo(width - padRight, zeroY);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  // 2. Draw Waveforms
  const visibleChannels = channels.value.filter(c => c.visible && c.points.length > 1);

  for (const ch of visibleChannels) {
    ctx.strokeStyle = ch.color;
    ctx.lineWidth = 2 * dpr;
    ctx.lineJoin = 'round';
    ctx.beginPath();

    const pts = ch.points;
    const count = pts.length;

    for (let i = 0; i < count; i++) {
      const px = padLeft + (i / (maxPoints.value - 1)) * plotW;
      const py = padTop + ((maxY - pts[i].v) / yRange) * plotH;

      if (i === 0) {
        ctx.moveTo(px, py);
      } else {
        ctx.lineTo(px, py);
      }
    }
    ctx.stroke();
  }

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

    // Calculate nearest index
    const relX = (hoverX - padLeft) / plotW;
    const targetIdx = Math.round(relX * (maxPoints.value - 1));

    const hoverVals: { name: string; color: string; val: number }[] = [];
    for (const ch of visibleChannels) {
      if (targetIdx < ch.points.length) {
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

  animFrameId = requestAnimationFrame(renderCanvas);
}

// --- Canvas Resizing ---
function resizeCanvas() {
  const canvas = canvasRef.value;
  const container = containerRef.value;
  if (!canvas || !container) return;

  const rect = container.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
}

function handleMouseMove(e: MouseEvent) {
  const canvas = canvasRef.value;
  if (!canvas) return;
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  mouseX.value = (e.clientX - rect.left) * dpr;
  mouseY.value = (e.clientY - rect.top) * dpr;
}

function handleMouseLeave() {
  mouseX.value = null;
  mouseY.value = null;
  hoveredData.value = null;
}

// --- Lifecycle ---
onMounted(async () => {
  nextTick(() => {
    resizeCanvas();
    window.addEventListener('resize', resizeCanvas);
    animFrameId = requestAnimationFrame(renderCanvas);
  });

  if (isTauri()) {
    try {
      unlistenRx = await listen<SerialRxPayload>('serial-rx', (event) => {
        const raw = new Uint8Array(event.payload.data);
        processIncomingBytes(raw);
      });
    } catch (err) {
      console.warn('Failed to listen to serial-rx in Plotter:', err);
    }
  }
});

onUnmounted(() => {
  if (unlistenRx) unlistenRx();
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
      </div>

      <!-- Right: Settings & Stats -->
      <div class="flex items-center gap-3 text-zinc-400 text-[11px]">
        <!-- Points Window Selector -->
        <div class="flex items-center gap-1">
          <span>点数:</span>
          <select
            v-model="maxPoints"
            class="bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5 text-zinc-200 focus:outline-none"
          >
            <option :value="200">200 点</option>
            <option :value="500">500 点</option>
            <option :value="1000">1000 点</option>
            <option :value="2000">2000 点</option>
          </select>
        </div>

        <!-- Y Axis Mode -->
        <div class="flex items-center gap-1">
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
          <span>帧率: <strong class="text-emerald-400">{{ fps }}</strong> FPS</span>
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
      class="flex-1 relative overflow-hidden cursor-crosshair"
      @mousemove="handleMouseMove"
      @mouseleave="handleMouseLeave"
    >
      <canvas ref="canvasRef" class="absolute inset-0 w-full h-full block"></canvas>

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

    <!-- Bottom Instructions Footer -->
    <div class="bg-zinc-900 border-t border-zinc-800 px-4 py-1 text-[10px] text-zinc-500 flex items-center justify-between">
      <span>💡 支持协议: <code>CSV (v1,v2,v3)</code> | <code>键值对 (roll:12.3,pitch:45.6)</code> | <code>JSON ({"a":1,"b":2})</code></span>
      <span v-if="!isConnected" class="text-amber-500">⚠ 串口未连接，可点击 [🎲 启动仿真信号] 进行界面回归体验</span>
      <span v-else class="text-emerald-400">● 串口已就绪，正在监听数据流</span>
    </div>
  </div>
</template>
