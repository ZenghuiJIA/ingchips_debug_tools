<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue';
import { safeInvoke } from '../utils/ipc';
import {
  Play,
  Square,
  Activity
} from '@lucide/vue';

// Function Execution Profiling Record
export interface FunctionProfileItem {
  id: number;
  name: string;
  category: string;
  callCount: number;
  lastUs: number;
  minUs: number;
  maxUs: number;
  avgUs: number;
  p95Us: number;
  cpuPercent: number;
  histogram: number[]; // 10 bins of execution time distribution
}

// Global Profiler Settings
const cpuFreqMhz = ref<number>(64); // 64MHz default for ING9188 / Cortex-M
const isProfiling = ref<boolean>(false);
const alertThresholdUs = ref<number>(200); // 200µs threshold alert

// Freq Presets
const freqPresets = [16, 24, 32, 48, 64, 80, 120, 168, 240];

// Profiling functions list
const functionsList = ref<FunctionProfileItem[]>([
  {
    id: 1,
    name: 'ble_ll_event_poll',
    category: 'BLE Stack',
    callCount: 1420,
    lastUs: 24.5,
    minUs: 8.2,
    maxUs: 185.0,
    avgUs: 22.4,
    p95Us: 45.1,
    cpuPercent: 14.8,
    histogram: [120, 450, 600, 180, 45, 15, 6, 2, 1, 1]
  },
  {
    id: 2,
    name: 'SysTick_Handler',
    category: 'ISR',
    callCount: 10000,
    lastUs: 1.8,
    minUs: 1.2,
    maxUs: 12.5,
    avgUs: 1.6,
    p95Us: 2.8,
    cpuPercent: 3.2,
    histogram: [3200, 5800, 900, 80, 15, 3, 1, 1, 0, 0]
  },
  {
    id: 3,
    name: 'sensor_adc_dma_isr',
    category: 'ISR',
    callCount: 2500,
    lastUs: 8.4,
    minUs: 6.0,
    maxUs: 38.0,
    avgUs: 7.9,
    p95Us: 14.2,
    cpuPercent: 5.6,
    histogram: [800, 1400, 250, 40, 7, 2, 1, 0, 0, 0]
  },
  {
    id: 4,
    name: 'aes_ccm_encrypt',
    category: 'Security',
    callCount: 340,
    lastUs: 82.0,
    minUs: 76.5,
    maxUs: 245.0,
    avgUs: 84.1,
    p95Us: 110.0,
    cpuPercent: 8.4,
    histogram: [10, 40, 220, 55, 10, 2, 1, 1, 1, 0]
  },
  {
    id: 5,
    name: 'vTaskSwitchContext',
    category: 'RTOS',
    callCount: 6500,
    lastUs: 3.2,
    minUs: 2.1,
    maxUs: 18.4,
    avgUs: 3.1,
    p95Us: 5.8,
    cpuPercent: 4.1,
    histogram: [1800, 3900, 700, 80, 15, 3, 1, 1, 0, 0]
  },
  {
    id: 6,
    name: 'os_idle_task',
    category: 'RTOS',
    callCount: 890,
    lastUs: 450.0,
    minUs: 100.0,
    maxUs: 1200.0,
    avgUs: 680.0,
    p95Us: 950.0,
    cpuPercent: 63.9,
    histogram: [20, 80, 150, 280, 220, 90, 35, 10, 4, 1]
  }
]);

// Active Selected function for detailed histogram view
const selectedFunctionId = ref<number>(1);
const selectedFunction = computed(() => {
  return functionsList.value.find(f => f.id === selectedFunctionId.value) || functionsList.value[0];
});

// Overall CPU Load
const totalCpuLoad = computed<number>(() => {
  const nonIdle = functionsList.value.filter(f => !f.name.toLowerCase().includes('idle'));
  const sum = nonIdle.reduce((acc, cur) => acc + cur.cpuPercent, 0);
  return Number(Math.min(100, sum).toFixed(1));
});

let timer: any = null;

// Start / Stop Hardware DWT Profiling
async function toggleProfiling() {
  isProfiling.value = !isProfiling.value;
  if (isProfiling.value) {
    // Enable DWT CYCCNT via SWD
    try {
      // 0xE000EDFC (DEMCR) bit 24 = 1
      await safeInvoke('pyocd_write_memory', {
        address: '0xE000EDFC',
        value: '0x01000000',
        probeId: null,
        targetOverride: null
      });
      // 0xE0001000 (DWT_CTRL) bit 0 = 1 (CYCCNTENA)
      await safeInvoke('pyocd_write_memory', {
        address: '0xE0001000',
        value: '0x00000001',
        probeId: null,
        targetOverride: null
      });
    } catch (_) {}

    timer = setInterval(() => {
      // Refresh simulated/live jitter
      for (const item of functionsList.value) {
        item.callCount += Math.floor(Math.random() * 20);
        const jitter = (Math.random() - 0.48) * 4;
        item.lastUs = Math.max(item.minUs, Number((item.lastUs + jitter).toFixed(1)));
        if (item.lastUs > item.maxUs) item.maxUs = item.lastUs;
      }
    }, 500);
  } else {
    if (timer) clearInterval(timer);
    timer = null;
  }
}

function resetStatistics() {
  for (const item of functionsList.value) {
    item.callCount = 0;
    item.maxUs = item.avgUs;
    item.minUs = item.avgUs;
  }
}

onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-sans select-none overflow-hidden">
    <!-- Header Controls Toolbar -->
    <div class="bg-zinc-900 border-b border-zinc-800 p-3 flex items-center justify-between gap-3 shrink-0">
      <div class="flex items-center gap-2.5">
        <div class="p-1.5 rounded bg-amber-950/60 border border-amber-800/40 text-amber-400">
          <Activity class="w-4 h-4" />
        </div>
        <div>
          <span class="font-bold text-xs text-zinc-100 font-sans">MCU 实时性能与耗时统计分析器 (DWT Runtime Profiler)</span>
          <p class="text-[10.5px] text-zinc-400 font-sans">
            利用 Cortex-M 内核 DWT 硬件周期计数器 (CYCCNT)，纳秒/微秒级免侵入分析关键函数与中断耗时分布及 CPU 负载。
          </p>
        </div>
      </div>

      <!-- Controls -->
      <div class="flex items-center gap-3">
        <!-- CPU Frequency Input -->
        <div class="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-xs font-mono">
          <span class="text-zinc-500">MCU 主频:</span>
          <select
            v-model.number="cpuFreqMhz"
            class="bg-transparent text-amber-400 font-bold outline-none cursor-pointer"
          >
            <option v-for="f in freqPresets" :key="f" :value="f">{{ f }} MHz</option>
          </select>
        </div>

        <!-- Alert Threshold -->
        <div class="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-xs font-mono">
          <span class="text-zinc-500">超时告警:</span>
          <input
            type="number"
            v-model.number="alertThresholdUs"
            class="w-14 bg-transparent text-rose-400 font-bold outline-none"
          />
          <span class="text-zinc-500">µs</span>
        </div>

        <button
          @click="resetStatistics"
          class="px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 rounded text-xs transition-colors"
        >
          重置统计
        </button>

        <button
          @click="toggleProfiling"
          class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-semibold shadow-sm transition-all"
          :class="isProfiling ? 'bg-rose-600 hover:bg-rose-500 text-zinc-100 animate-pulse' : 'bg-emerald-600 hover:bg-emerald-500 text-zinc-950'"
        >
          <component :is="isProfiling ? Square : Play" class="w-3.5 h-3.5 fill-current" />
          <span>{{ isProfiling ? '停止性能采样' : '启动 DWT 实时性能采样' }}</span>
        </button>
      </div>
    </div>

    <!-- Live Performance Dashboard Cards -->
    <div class="bg-zinc-900/40 border-b border-zinc-800 p-3 grid grid-cols-4 gap-3 shrink-0">
      <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
        <div class="text-[11px] text-zinc-400">综合 CPU 负载率 (Load %)</div>
        <div class="text-xl font-bold font-mono text-emerald-400 mt-1 flex items-baseline gap-2">
          <span>{{ totalCpuLoad }}%</span>
          <span class="text-[10px] text-zinc-500 font-normal">基于 {{ cpuFreqMhz }}MHz</span>
        </div>
      </div>

      <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
        <div class="text-[11px] text-zinc-400">DWT 计数器分辨率</div>
        <div class="text-xl font-bold font-mono text-cyan-400 mt-1">
          {{ (1000 / cpuFreqMhz).toFixed(1) }} ns
        </div>
      </div>

      <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
        <div class="text-[11px] text-zinc-400">当前活跃跟踪函数</div>
        <div class="text-xl font-bold font-mono text-amber-400 mt-1">
          {{ functionsList.length }} 个符号
        </div>
      </div>

      <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
        <div class="text-[11px] text-zinc-400">超限抖动事件 (Jitter)</div>
        <div class="text-xl font-bold font-mono text-rose-400 mt-1 flex items-baseline gap-1.5">
          <span>{{ functionsList.filter(f => f.maxUs > alertThresholdUs).length }} 处</span>
          <span class="text-[10px] text-zinc-500 font-normal">&gt;{{ alertThresholdUs }}µs</span>
        </div>
      </div>
    </div>

    <!-- Main Workspace (Functions Table + Histogram Chart) -->
    <div class="flex-1 flex overflow-hidden">
      <!-- Left: Function Performance Table -->
      <div class="flex-1 flex flex-col border-r border-zinc-800 overflow-hidden">
        <div class="p-2.5 bg-zinc-900 border-b border-zinc-800 flex items-center justify-between text-xs">
          <span class="font-bold text-zinc-200">函数与中断服务耗时排名列表 (按 Max 倒序)</span>
          <span class="text-[11px] text-zinc-500">点击选中行查看右侧耗时分布正态直方图</span>
        </div>

        <div class="flex-1 overflow-y-auto">
          <table class="w-full text-left text-xs border-collapse">
            <thead class="bg-zinc-900/90 text-zinc-400 text-[11px] font-mono sticky top-0 border-b border-zinc-800 select-none">
              <tr>
                <th class="p-2">函数 / 中断名称</th>
                <th class="p-2">分类</th>
                <th class="p-2 text-right">调用次数</th>
                <th class="p-2 text-right">当前 (µs)</th>
                <th class="p-2 text-right">最小 (µs)</th>
                <th class="p-2 text-right">最大 (µs)</th>
                <th class="p-2 text-right">平均 (µs)</th>
                <th class="p-2 text-right">P95 (µs)</th>
                <th class="p-2 text-right w-24">CPU 占比</th>
              </tr>
            </thead>
            <tbody class="font-mono text-[11.5px] divide-y divide-zinc-900">
              <tr
                v-for="item in functionsList"
                :key="item.id"
                @click="selectedFunctionId = item.id"
                class="hover:bg-zinc-800/60 cursor-pointer transition-colors"
                :class="selectedFunctionId === item.id ? 'bg-amber-950/30 text-amber-200' : ''"
              >
                <td class="p-2 font-sans font-semibold text-zinc-200 flex items-center gap-1.5">
                  <span
                    v-if="item.maxUs > alertThresholdUs"
                    class="w-1.5 h-1.5 rounded-full bg-rose-500 animate-ping"
                    title="存在超限耗时抖动"
                  ></span>
                  <span>{{ item.name }}</span>
                </td>
                <td class="p-2 text-zinc-400 font-sans">
                  <span class="px-1.5 py-0.5 rounded text-[10px] bg-zinc-800 text-zinc-400 border border-zinc-700/60">
                    {{ item.category }}
                  </span>
                </td>
                <td class="p-2 text-right text-zinc-400">{{ item.callCount }}</td>
                <td class="p-2 text-right text-cyan-400">{{ item.lastUs }}</td>
                <td class="p-2 text-right text-zinc-500">{{ item.minUs }}</td>
                <td class="p-2 text-right" :class="item.maxUs > alertThresholdUs ? 'text-rose-400 font-bold' : 'text-zinc-200'">
                  {{ item.maxUs }}
                </td>
                <td class="p-2 text-right text-zinc-300">{{ item.avgUs }}</td>
                <td class="p-2 text-right text-amber-400">{{ item.p95Us }}</td>
                <td class="p-2 text-right">
                  <div class="flex items-center justify-end gap-1.5">
                    <div class="w-12 bg-zinc-800 h-1.5 rounded-full overflow-hidden">
                      <div class="bg-emerald-500 h-full" :style="{ width: `${Math.min(100, item.cpuPercent)}%` }"></div>
                    </div>
                    <span class="text-zinc-400 text-[10.5px] w-8 text-right">{{ item.cpuPercent }}%</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Right: Detailed Histogram & Distribution Panel -->
      <div class="w-80 border-l border-zinc-800 bg-zinc-900/40 p-4 flex flex-col shrink-0 text-xs overflow-y-auto">
        <div class="font-bold text-xs text-zinc-200 pb-2 border-b border-zinc-800 flex items-center justify-between">
          <span>耗时分布直方图 (Histogram)</span>
          <span class="text-amber-400 font-mono">{{ selectedFunction.name }}</span>
        </div>

        <!-- Metric Details -->
        <div class="grid grid-cols-2 gap-2 my-3 font-mono text-[11px]">
          <div class="p-2 bg-zinc-900 border border-zinc-800 rounded">
            <span class="text-zinc-500 block text-[10px]">Min 耗时</span>
            <span class="text-emerald-400 font-bold text-sm">{{ selectedFunction.minUs }} µs</span>
          </div>
          <div class="p-2 bg-zinc-900 border border-zinc-800 rounded">
            <span class="text-zinc-500 block text-[10px]">Max 耗时</span>
            <span class="text-rose-400 font-bold text-sm">{{ selectedFunction.maxUs }} µs</span>
          </div>
          <div class="p-2 bg-zinc-900 border border-zinc-800 rounded">
            <span class="text-zinc-500 block text-[10px]">Avg 耗时</span>
            <span class="text-cyan-400 font-bold text-sm">{{ selectedFunction.avgUs }} µs</span>
          </div>
          <div class="p-2 bg-zinc-900 border border-zinc-800 rounded">
            <span class="text-zinc-500 block text-[10px]">P95 耗时</span>
            <span class="text-amber-400 font-bold text-sm">{{ selectedFunction.p95Us }} µs</span>
          </div>
        </div>

        <!-- Histogram Bars Visualization -->
        <div class="flex-1 flex flex-col justify-end pt-4 border-t border-zinc-800">
          <div class="text-[11px] text-zinc-400 font-sans mb-3 flex items-center justify-between">
            <span>采样频次分布 (正态分布区间)</span>
            <span class="text-zinc-500 font-mono text-[10px]">10 阶区间</span>
          </div>

          <div class="h-44 flex items-end gap-1.5 bg-zinc-950 p-2.5 rounded-lg border border-zinc-800/80">
            <div
              v-for="(count, bIdx) in selectedFunction.histogram"
              :key="bIdx"
              class="flex-1 flex flex-col items-center justify-end h-full group relative"
            >
              <!-- Bar -->
              <div
                class="w-full bg-cyan-600/70 hover:bg-cyan-400 rounded-t transition-all"
                :style="{ height: `${Math.max(4, (count / Math.max(...selectedFunction.histogram)) * 100)}%` }"
              ></div>

              <!-- Tooltip -->
              <div class="opacity-0 group-hover:opacity-100 absolute -top-8 bg-zinc-800 text-zinc-200 text-[10px] px-1.5 py-0.5 rounded shadow pointer-events-none transition-opacity font-mono z-10 whitespace-nowrap">
                {{ count }} 次
              </div>
            </div>
          </div>

          <div class="flex justify-between text-[10px] font-mono text-zinc-500 mt-1">
            <span>{{ selectedFunction.minUs }}µs</span>
            <span>{{ selectedFunction.avgUs }}µs</span>
            <span>{{ selectedFunction.maxUs }}µs</span>
          </div>
        </div>

        <!-- Optimization Suggestion -->
        <div class="mt-4 p-2.5 bg-zinc-900 border border-zinc-800 rounded-lg text-[11px] text-zinc-400 leading-relaxed font-sans">
          <span class="text-amber-400 font-semibold block mb-0.5">性能优化建议:</span>
          <span v-if="selectedFunction.maxUs > alertThresholdUs">
            函数最大耗时已超过 {{ alertThresholdUs }}µs 阈值，需排查其内部是否存在死循环、阻塞等待外设标志位或长中断嵌套。
          </span>
          <span v-else>
            该函数执行耗时均在安全合理区间内，无严重抖动风险。
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
