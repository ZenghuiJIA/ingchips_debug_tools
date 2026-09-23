<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import { safeInvoke } from '../utils/ipc';
import type { SystemMetrics } from '../types';
import {
  Cpu,
  Activity,
  CheckCircle2,
  AlertCircle,
  Radio
} from '@lucide/vue';

const props = withDefaults(defineProps<{
  activeSessionsCount?: number;
}>(), {
  activeSessionsCount: 0
});

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

async function refreshMetrics() {
  try {
    const m: SystemMetrics = await safeInvoke('get_system_metrics');
    metrics.value = m;
  } catch (err) {
    console.error('Failed to fetch metrics:', err);
  }
}

onMounted(() => {
  refreshMetrics();
  metricsTimer = setInterval(refreshMetrics, 2000);
});

onUnmounted(() => {
  if (metricsTimer) clearInterval(metricsTimer);
});
</script>

<template>
  <header class="bg-zinc-900 border-b border-zinc-800 px-4 py-2.5 flex items-center justify-between gap-4 select-none">
    <!-- Left: Brand & Status -->
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
          <div class="text-[11px] text-zinc-400 flex items-center gap-1.5">
            <span
              class="inline-block w-1.5 h-1.5 rounded-full"
              :class="activeSessionsCount > 0 ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-500'"
            ></span>
            <span>{{ activeSessionsCount > 0 ? `硬件在线 · ${activeSessionsCount} 个端口已连接` : '等待连接硬件' }}</span>
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

    <!-- Center: Global System Status Indicator -->
    <div class="hidden md:flex items-center gap-2 text-xs text-zinc-400">
      <span class="flex items-center gap-1.5 px-3 py-1 rounded-full bg-zinc-950/80 border border-zinc-800/80 text-[11px] font-sans">
        <Radio class="w-3.5 h-3.5 text-emerald-400" />
        <span>多串口及硬件引脚 (DTR/RTS/复位) 均已由标签页独立自主管理</span>
      </span>
    </div>

    <!-- Right: Active Connections Badge -->
    <div class="flex items-center gap-3">
      <div
        v-if="activeSessionsCount > 0"
        class="flex items-center gap-2 bg-emerald-950/40 border border-emerald-800/40 px-2.5 py-1 rounded-md text-xs font-mono"
      >
        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
        <span class="text-emerald-300 font-semibold">{{ activeSessionsCount }} 端口会话在线</span>
      </div>

      <div v-else class="text-[11px] text-zinc-500 font-mono hidden sm:block">
        无活动连接
      </div>
    </div>
  </header>
</template>
