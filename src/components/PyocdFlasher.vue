<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { safeInvoke } from '../utils/ipc';
import type { ProbeInfo } from '../types';
import {
  Zap,
  RotateCcw,
  Pause,
  RefreshCw
} from '@lucide/vue';

const probes = ref<ProbeInfo[]>([]);
const selectedProbeId = ref<string>('');
const isScanningProbes = ref<boolean>(false);

const targetMcu = ref<string>('cortex_m');
const targetPresets = [
  { label: 'ARM Cortex-M (通用)', value: 'cortex_m' },
  { label: 'STM32F103C8 (BluePill)', value: 'stm32f103c8' },
  { label: 'STM32F407VG / ZG', value: 'stm32f407vg' },
  { label: 'STM32H743VI', value: 'stm32h743vi' },
  { label: 'RP2040 (Raspberry Pi Pico)', value: 'rp2040' },
  { label: 'NRF52840', value: 'nrf52840' },
  { label: 'Cortex-M0+ 通用', value: 'cortex_m0p' },
  { label: 'Cortex-M4 通用', value: 'cortex_m4' },
];

const filePath = ref<string>('');
const isFlashing = ref<boolean>(false);
const isResetting = ref<boolean>(false);
const flashLogs = ref<Array<{ time: string; text: string; status: 'info' | 'success' | 'error' }>>([]);

function logMsg(text: string, status: 'info' | 'success' | 'error' = 'info') {
  const time = new Date().toTimeString().split(' ')[0];
  flashLogs.value.unshift({ time, text, status });
  if (flashLogs.value.length > 100) flashLogs.value.pop();
}

async function scanProbes() {
  isScanningProbes.value = true;
  logMsg('正在扫描 SWD/JTAG 硬件调试器 (PyOCD)...');
  try {
    const list: ProbeInfo[] = await safeInvoke('pyocd_list_probes');
    probes.value = list;
    if (list.length > 0) {
      selectedProbeId.value = list[0].unique_id;
      logMsg(`成功发现 ${list.length} 个调试器探针: ${list[0].description} (ID: ${list[0].unique_id})`, 'success');
    } else {
      logMsg('未检测到 CMSIS-DAP / DAPLink 调试器探针，请确认 USB 连接', 'error');
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
  logMsg(`开始通过 SWD 烧录: ${filePath.value} (目标: ${targetMcu.value})...`);

  try {
    const res: any = await safeInvoke('pyocd_flash_firmware', {
      filePath: filePath.value,
      targetOverride: targetMcu.value || null,
      probeId: selectedProbeId.value || null,
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
          <span>SWD 硬件在环固件烧录器 (PyOCD CMSIS-Pack)</span>
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

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
        <!-- Probe Selection -->
        <div>
          <label class="block text-zinc-400 mb-1 text-[11px] font-medium">调试器硬件探针 (DAPLink / CMSIS-DAP)</label>
          <select
            v-model="selectedProbeId"
            class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-zinc-200 outline-none focus:border-emerald-500"
          >
            <option v-if="probes.length === 0" value="">(未找到探针)</option>
            <option v-for="p in probes" :key="p.unique_id" :value="p.unique_id">
              {{ p.description }} (ID: {{ p.unique_id }})
            </option>
          </select>
        </div>

        <!-- Target MCU Selection -->
        <div>
          <label class="block text-zinc-400 mb-1 text-[11px] font-medium">目标芯片型号 (CMSIS-Pack 标识符)</label>
          <div class="flex gap-2">
            <select
              v-model="targetMcu"
              class="flex-1 bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-zinc-200 outline-none focus:border-emerald-500"
            >
              <option v-for="p in targetPresets" :key="p.value" :value="p.value">
                {{ p.label }}
              </option>
            </select>
            <input
              v-model="targetMcu"
              type="text"
              placeholder="自定义型号"
              class="w-32 bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 outline-none focus:border-emerald-500 font-mono"
            />
          </div>
        </div>
      </div>

      <!-- File Path Selector -->
      <div>
        <label class="block text-zinc-400 mb-1 text-[11px] font-medium">固件文件绝对路径 (.bin / .hex / .elf)</label>
        <div class="flex gap-2">
          <div class="relative flex-1">
            <input
              v-model="filePath"
              type="text"
              placeholder="输入或粘贴固件物理路径，如: D:\projects\firmware\build\app.hex"
              class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-zinc-200 outline-none focus:border-emerald-500 font-mono"
            />
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
      </div>
    </div>

    <!-- Bottom Card: Flash & SWD Execution Logs -->
    <div class="flex-1 bg-zinc-900 border border-zinc-800 rounded-lg p-4 flex flex-col min-h-[220px]">
      <div class="flex items-center justify-between pb-2 border-b border-zinc-800 mb-2">
        <span class="font-semibold text-zinc-300">烧录与调试事务日志</span>
        <button
          @click="flashLogs = []"
          class="text-[11px] text-zinc-500 hover:text-zinc-300"
        >
          清空日志
        </button>
      </div>

      <div class="flex-1 overflow-y-auto space-y-1.5 font-mono text-[11px] p-2 bg-zinc-950 rounded border border-zinc-800/60">
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
