<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { safeInvoke } from '../utils/ipc';
import type { CoreRegisters, FaultRegisters, CfsrDecoded, HfsrDecoded, ProbeInfo } from '../types';
import {
  AlertOctagon,
  Cpu,
  RefreshCw,
  Search,
  AlertTriangle,
  Lightbulb,
  Binary
} from '@lucide/vue';

const isCapturing = ref<boolean>(false);
const targetChip = ref<string>('cortex_m');
const probes = ref<ProbeInfo[]>([]);
const selectedProbeId = ref<string>('');

const coreRegisters = ref<CoreRegisters | null>(null);
const faultRegisters = ref<FaultRegisters | null>(null);
const cfsrDecoded = ref<CfsrDecoded | null>(null);
const hfsrDecoded = ref<HfsrDecoded | null>(null);
const aiRecommendations = ref<string[]>([]);
const errorMsg = ref<string>('');

// Memory Inspector State
const memAddress = ref<string>('0x20000000');
const memCount = ref<number>(64);
const isReadingMem = ref<boolean>(false);
const memoryDump = ref<{ address: string; hex_dump: string; bytes: number[] } | null>(null);

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
  try {
    const list: ProbeInfo[] = await safeInvoke('pyocd_list_probes');
    probes.value = list;
    if (list.length > 0 && !selectedProbeId.value) {
      selectedProbeId.value = list[0].unique_id;
    }
  } catch (err) {
    console.error('Scan probes failed in HardFaultInspector:', err);
  }
}

async function captureRegistersAndDiagnose() {
  isCapturing.value = true;
  errorMsg.value = '';
  try {
    const res: any = await safeInvoke('pyocd_diagnose_hardfault', {
      targetOverride: targetChip.value || null,
      probeId: selectedProbeId.value || null
    });

    const raw = res.raw_dump;
    coreRegisters.value = raw.core_registers;
    faultRegisters.value = raw.fault_registers;
    cfsrDecoded.value = raw.cfsr_decoded;
    hfsrDecoded.value = raw.hfsr_decoded;
    aiRecommendations.value = res.recommendations || [];
  } catch (err: any) {
    errorMsg.value = `抓取寄存器失败: ${err}`;
  } finally {
    isCapturing.value = false;
  }
}

async function handleReadMemory() {
  isReadingMem.value = true;
  try {
    const res: any = await safeInvoke('pyocd_read_memory', {
      address: memAddress.value,
      count: Number(memCount.value),
      targetOverride: targetChip.value || null,
      probeId: selectedProbeId.value || null
    });
    memoryDump.value = res;
  } catch (err: any) {
    alert(`读取内存失败: ${err}`);
  } finally {
    isReadingMem.value = false;
  }
}

onMounted(() => {
  scanProbes();
});

function formatHexGrid(bytes: number[], startAddr: number) {
  const rows: Array<{ offset: string; hex: string; ascii: string }> = [];
  for (let i = 0; i < bytes.length; i += 16) {
    const chunk = bytes.slice(i, i + 16);
    const offset = '0x' + (startAddr + i).toString(16).toUpperCase().padStart(8, '0');
    const hex = chunk.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');
    const ascii = chunk.map(b => (b >= 32 && b <= 126) ? String.fromCharCode(b) : '.').join('');
    rows.push({ offset, hex, ascii });
  }
  return rows;
}
</script>

<template>
  <div class="h-full flex flex-col p-4 bg-zinc-950 text-zinc-100 text-xs overflow-y-auto space-y-4">
    <!-- Top Action Bar -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3.5 flex items-center justify-between gap-4">
      <div class="flex items-center gap-2">
        <div class="p-2 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20">
          <AlertOctagon class="w-5 h-5" />
        </div>
        <div>
          <div class="font-bold text-sm text-zinc-100">ARM Cortex-M 硬件硬故障 (HardFault) 智能诊断</div>
          <div class="text-[11px] text-zinc-400">一键 SWD 捕获核心栈现场、SCB 故障寄存器并自动分析根因</div>
        </div>
      </div>

      <div class="flex items-center gap-2">
        <!-- Probe Selection (PyOCD CMSIS-DAP / J-Link) -->
        <select
          v-if="probes.length > 0"
          v-model="selectedProbeId"
          class="bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 outline-none focus:border-rose-500 font-mono text-xs max-w-[200px]"
          title="选择调试探针 (DAPLink / J-Link)"
        >
          <option v-for="p in probes" :key="p.unique_id" :value="p.unique_id">
            {{ getProbeBadge(p) }} {{ p.description }}
          </option>
        </select>

        <input
          v-model="targetChip"
          type="text"
          placeholder="芯片型号 (如 stm32f407vg)"
          class="bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 text-zinc-200 outline-none focus:border-rose-500 font-mono w-44"
        />

        <button
          @click="captureRegistersAndDiagnose"
          :disabled="isCapturing"
          class="flex items-center gap-2 px-4 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded font-medium transition-colors shadow-sm disabled:opacity-40"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isCapturing }" />
          <span>{{ isCapturing ? '正在抓取寄存器...' : '一键抓取现场并诊断' }}</span>
        </button>
      </div>
    </div>

    <!-- Error Alert if failed -->
    <div v-if="errorMsg" class="bg-rose-950/50 border border-rose-800/80 text-rose-300 p-3 rounded-lg flex items-center gap-2">
      <AlertTriangle class="w-4 h-4 text-rose-400 shrink-0" />
      <span>{{ errorMsg }}</span>
    </div>

    <!-- AI Diagnosis Recommendations (if available) -->
    <div v-if="aiRecommendations.length > 0" class="bg-amber-950/30 border border-amber-800/60 rounded-lg p-3.5 space-y-2">
      <div class="flex items-center gap-2 font-semibold text-amber-400">
        <Lightbulb class="w-4 h-4" />
        <span>AI 智能诊断排查建议</span>
      </div>
      <ul class="space-y-1 pl-4 list-disc text-zinc-300">
        <li v-for="(rec, idx) in aiRecommendations" :key="idx">{{ rec }}</li>
      </ul>
    </div>

    <!-- SCB Fault Registers & Bitfield Visualizer -->
    <div v-if="faultRegisters" class="grid grid-cols-1 md:grid-cols-4 gap-3">
      <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
        <div class="text-[11px] text-zinc-500 font-mono">CFSR (可配置故障状态)</div>
        <div class="text-base font-mono font-bold text-rose-400 mt-1">{{ faultRegisters.CFSR }}</div>
        <div class="text-[10px] text-zinc-400 mt-0.5">MMFSR: {{ cfsrDecoded?.mmfsr }} | BFSR: {{ cfsrDecoded?.bfsr }} | UFSR: {{ cfsrDecoded?.ufsr }}</div>
      </div>

      <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
        <div class="text-[11px] text-zinc-500 font-mono">HFSR (硬故障状态)</div>
        <div class="text-base font-mono font-bold text-amber-400 mt-1">{{ faultRegisters.HFSR }}</div>
        <div class="text-[10px] text-zinc-400 mt-0.5">FORCED / DEBUGEVT 标志</div>
      </div>

      <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
        <div class="text-[11px] text-zinc-500 font-mono">BFAR (总线故障地址)</div>
        <div class="text-base font-mono font-bold text-sky-400 mt-1">{{ faultRegisters.BFAR }}</div>
        <div class="text-[10px] text-zinc-400 mt-0.5">精准总线崩溃时的硬件地址</div>
      </div>

      <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
        <div class="text-[11px] text-zinc-500 font-mono">MMFAR (内存管理故障地址)</div>
        <div class="text-base font-mono font-bold text-indigo-400 mt-1">{{ faultRegisters.MMFAR }}</div>
        <div class="text-[10px] text-zinc-400 mt-0.5">MPU / 越界内存访问地址</div>
      </div>
    </div>

    <!-- Active Fault Flags Breakdown -->
    <div v-if="cfsrDecoded && cfsrDecoded.flags.length > 0" class="bg-zinc-900 border border-zinc-800 rounded-lg p-3.5 space-y-2">
      <div class="font-semibold text-zinc-300 flex items-center gap-1.5">
        <AlertTriangle class="w-4 h-4 text-amber-400" />
        <span>触发的 SCB 故障硬件位 (Bitfields)</span>
      </div>

      <div class="flex flex-wrap gap-1.5">
        <span
          v-for="flag in cfsrDecoded.flags"
          :key="flag"
          class="px-2 py-0.5 rounded bg-rose-950/80 text-rose-300 border border-rose-800 text-[11px] font-mono font-bold"
        >
          {{ flag }}
        </span>
        <span
          v-for="flag in hfsrDecoded?.flags || []"
          :key="flag"
          class="px-2 py-0.5 rounded bg-amber-950/80 text-amber-300 border border-amber-800 text-[11px] font-mono font-bold"
        >
          {{ flag }}
        </span>
      </div>

      <div class="space-y-1 pt-1 text-[11px] text-zinc-400">
        <div v-for="(exp, idx) in cfsrDecoded.explanations" :key="idx" class="flex items-start gap-1.5">
          <span class="text-emerald-400">•</span>
          <span>{{ exp }}</span>
        </div>
      </div>
    </div>

    <!-- Cortex-M Core Registers Grid -->
    <div v-if="coreRegisters" class="bg-zinc-900 border border-zinc-800 rounded-lg p-3.5 space-y-2">
      <div class="font-semibold text-zinc-300 flex items-center gap-1.5">
        <Cpu class="w-4 h-4 text-emerald-400" />
        <span>ARM Cortex-M 核心寄存器实时现场 (Core Registers)</span>
      </div>

      <div class="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 lg:grid-cols-9 gap-2 font-mono text-center">
        <div
          v-for="(val, name) in coreRegisters"
          :key="name"
          class="bg-zinc-950 border border-zinc-800/80 rounded p-1.5"
          :class="{
            'border-rose-500/50 bg-rose-950/20': name === 'PC',
            'border-amber-500/50 bg-amber-950/20': name === 'LR',
            'border-sky-500/50 bg-sky-950/20': name === 'MSP' || name === 'PSP',
          }"
        >
          <div class="text-[10px] text-zinc-500 font-bold">{{ name }}</div>
          <div class="text-[11px] text-zinc-200 mt-0.5">{{ val }}</div>
        </div>
      </div>
    </div>

    <!-- Memory Dump Inspector -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3.5 space-y-3">
      <div class="flex items-center justify-between border-b border-zinc-800 pb-2">
        <div class="flex items-center gap-1.5 font-semibold text-zinc-200">
          <Binary class="w-4 h-4 text-emerald-400" />
          <span>SWD 目标内存查看器 (Memory Hex Viewer)</span>
        </div>

        <div class="flex items-center gap-2">
          <input
            v-model="memAddress"
            type="text"
            placeholder="起始地址 (如 0x20000000)"
            class="bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1 text-zinc-200 font-mono text-xs w-36 outline-none focus:border-emerald-500"
          />
          <input
            v-model.number="memCount"
            type="number"
            placeholder="字节数"
            class="bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1 text-zinc-200 font-mono text-xs w-20 outline-none focus:border-emerald-500"
          />
          <button
            @click="handleReadMemory"
            :disabled="isReadingMem"
            class="flex items-center gap-1 px-3 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded border border-zinc-700 font-medium transition-colors disabled:opacity-40"
          >
            <Search class="w-3.5 h-3.5" :class="{ 'animate-spin': isReadingMem }" />
            <span>读取内存</span>
          </button>
        </div>
      </div>

      <!-- Hex View Table -->
      <div v-if="memoryDump" class="bg-zinc-950 border border-zinc-800/80 rounded p-2.5 font-mono text-[11px] overflow-x-auto space-y-1">
        <div
          v-for="row in formatHexGrid(memoryDump.bytes, parseInt(memoryDump.address, 16))"
          :key="row.offset"
          class="flex items-center gap-4 hover:bg-zinc-900/60 px-1 rounded"
        >
          <span class="text-zinc-500 font-bold select-none">{{ row.offset }}:</span>
          <span class="text-emerald-400 tracking-wider flex-1">{{ row.hex }}</span>
          <span class="text-zinc-400 border-l border-zinc-800 pl-3 select-none">{{ row.ascii }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
