<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { safeInvoke } from '../utils/ipc';
import type {
  CoreRegisters,
  FaultRegisters,
  CfsrDecoded,
  HfsrDecoded,
  ProbeInfo,
  HardFaultDeepAnalysis
} from '../types';
import {
  AlertOctagon,
  Cpu,
  RefreshCw,
  Search,
  AlertTriangle,
  Lightbulb,
  Binary,
  Copy,
  Check,
  FolderOpen,
  Layers,
  ChevronDown,
  ChevronRight,
  Code,
  FileText,
  X,
  ShieldAlert
} from '@lucide/vue';

const isCapturing = ref<boolean>(false);
const targetChip = ref<string>('cortex_m');
const probes = ref<ProbeInfo[]>([]);
const selectedProbeId = ref<string>('');
const axfPath = ref<string>('');

const coreRegisters = ref<CoreRegisters | null>(null);
const faultRegisters = ref<FaultRegisters | null>(null);
const cfsrDecoded = ref<CfsrDecoded | null>(null);
const hfsrDecoded = ref<HfsrDecoded | null>(null);
const deepAnalysis = ref<HardFaultDeepAnalysis | null>(null);
const aiRecommendations = ref<string[]>([]);
const errorMsg = ref<string>('');

// Stack tracing UI state
const activeStackTab = ref<'psp' | 'msp'>('psp');
const expandedFrames = ref<Set<number>>(new Set([0]));
const showDisassemblyMap = ref<Record<string, boolean>>({});

// Copy state
const isCopiedReport = ref<boolean>(false);
const isCopiedMemory = ref<boolean>(false);

async function pickAxfFile() {
  try {
    const selected = await safeInvoke<string | null>('pick_firmware_file', {
      title: '选择 ARM ELF / AXF 固件目标调试符号文件'
    });
    if (selected) {
      axfPath.value = selected;
    }
  } catch (err: any) {
    console.error('Pick AXF file failed:', err);
  }
}

function clearAxfFile() {
  axfPath.value = '';
}

function toggleFrame(idx: number) {
  if (expandedFrames.value.has(idx)) {
    expandedFrames.value.delete(idx);
  } else {
    expandedFrames.value.add(idx);
  }
}

function toggleDisasm(key: string) {
  showDisassemblyMap.value[key] = !showDisassemblyMap.value[key];
}

function copyDiagnosticReport() {
  const parts: string[] = ['=== ARM Cortex-M HardFault 智能诊断报告 ==='];
  if (deepAnalysis.value) {
    parts.push(`\n[异常栈模式分析]`);
    parts.push(`当前异常压栈指针: ${deepAnalysis.value.active_sp_name} (${deepAnalysis.value.active_sp_val})`);
    parts.push(`EXC_RETURN: ${deepAnalysis.value.exc_return.raw_hex} (${deepAnalysis.value.exc_return.description})`);
    parts.push(`真实崩溃指令 (Stacked PC): ${deepAnalysis.value.exception_frame.pc} (${deepAnalysis.value.crash_location.func_name}${deepAnalysis.value.crash_location.offset_str})`);
    if (deepAnalysis.value.crash_location.file_name && deepAnalysis.value.crash_location.line) {
      parts.push(`源码位置: ${deepAnalysis.value.crash_location.file_name}:${deepAnalysis.value.crash_location.line}`);
    }
  }
  if (faultRegisters.value) {
    parts.push('\n[SCB 故障寄存器]');
    parts.push(`CFSR: ${faultRegisters.value.CFSR}`);
    parts.push(`HFSR: ${faultRegisters.value.HFSR}`);
    parts.push(`BFAR: ${faultRegisters.value.BFAR}`);
    parts.push(`MMFAR: ${faultRegisters.value.MMFAR}`);
  }
  if (cfsrDecoded.value && cfsrDecoded.value.flags.length > 0) {
    parts.push('\n[故障标志位]');
    parts.push(cfsrDecoded.value.flags.join(', '));
    parts.push('\n[原因解析]');
    parts.push(cfsrDecoded.value.explanations.join('\n'));
  }
  if (coreRegisters.value) {
    parts.push('\n[核心寄存器现场]');
    for (const [k, v] of Object.entries(coreRegisters.value)) {
      parts.push(`${k}: ${v}`);
    }
  }
  if (deepAnalysis.value) {
    if (deepAnalysis.value.psp_call_stack.length > 0) {
      parts.push('\n[PSP 调用栈回溯]');
      deepAnalysis.value.psp_call_stack.forEach(f => {
        const src = f.source_info.file_name ? ` (${f.source_info.file_name}:${f.source_info.line})` : '';
        parts.push(`  #${f.frame_index} ${f.return_address} in ${f.source_info.func_name}${f.source_info.offset_str}${src}`);
      });
    }
    if (deepAnalysis.value.msp_call_stack.length > 0) {
      parts.push('\n[MSP 调用栈回溯]');
      deepAnalysis.value.msp_call_stack.forEach(f => {
        const src = f.source_info.file_name ? ` (${f.source_info.file_name}:${f.source_info.line})` : '';
        parts.push(`  #${f.frame_index} ${f.return_address} in ${f.source_info.func_name}${f.source_info.offset_str}${src}`);
      });
    }
  }
  if (aiRecommendations.value.length > 0) {
    parts.push('\n[排查建议]');
    aiRecommendations.value.forEach((rec, idx) => parts.push(`${idx + 1}. ${rec}`));
  }

  navigator.clipboard.writeText(parts.join('\n'));
  isCopiedReport.value = true;
  setTimeout(() => isCopiedReport.value = false, 2000);
}

function copyMemoryDump() {
  if (!memoryDump.value) return;
  const rows = formatHexGrid(memoryDump.value.bytes, parseInt(memoryDump.value.address, 16));
  const text = rows.map(r => `${r.offset}:  ${r.hex.padEnd(48, ' ')}  |${r.ascii}|`).join('\n');
  navigator.clipboard.writeText(text);
  isCopiedMemory.value = true;
  setTimeout(() => isCopiedMemory.value = false, 2000);
}

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
      probeId: selectedProbeId.value || null,
      axfPath: axfPath.value.trim() || null
    });

    const raw = res.raw_dump;
    coreRegisters.value = raw.core_registers;
    faultRegisters.value = raw.fault_registers;
    cfsrDecoded.value = raw.cfsr_decoded;
    hfsrDecoded.value = raw.hfsr_decoded;
    aiRecommendations.value = res.recommendations || [];
    deepAnalysis.value = res.deep_analysis || null;

    if (deepAnalysis.value?.active_sp_name) {
      activeStackTab.value = deepAnalysis.value.active_sp_name.toLowerCase() as 'psp' | 'msp';
    }
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
    <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3.5 flex flex-col md:flex-row md:items-center justify-between gap-3">
      <div class="flex items-center gap-2">
        <div class="p-2 rounded bg-rose-500/10 text-rose-400 border border-rose-500/20">
          <AlertOctagon class="w-5 h-5" />
        </div>
        <div>
          <div class="font-bold text-sm text-zinc-100 flex items-center gap-2">
            <span>ARM Cortex-M 硬件硬故障 (HardFault) 智能诊断</span>
            <span v-if="deepAnalysis?.axf_loaded" class="px-2 py-0.5 rounded text-[10px] bg-emerald-950 text-emerald-300 border border-emerald-700">
              AXF 符号已加载
            </span>
          </div>
          <div class="text-[11px] text-zinc-400">一键捕获栈现场、解析 EXC_RETURN 模式、回溯双栈调用链、定位崩溃源码与反汇编</div>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <!-- Probe Selection (PyOCD CMSIS-DAP / J-Link) -->
        <select
          v-if="probes.length > 0"
          v-model="selectedProbeId"
          class="bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 outline-none focus:border-rose-500 font-mono text-xs max-w-[190px]"
          title="选择调试探针 (DAPLink / J-Link)"
        >
          <option v-for="p in probes" :key="p.unique_id" :value="p.unique_id">
            {{ getProbeBadge(p) }} {{ p.description }}
          </option>
        </select>

        <input
          v-model="targetChip"
          type="text"
          placeholder="芯片型号 (如 cortex_m)"
          class="bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 outline-none focus:border-rose-500 font-mono w-32"
        />

        <!-- AXF File Picker -->
        <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded px-2 py-1 max-w-[280px]">
          <input
            v-model="axfPath"
            type="text"
            placeholder="可选导入 .axf / .elf 文件"
            class="bg-transparent text-zinc-200 outline-none font-mono text-[11px] w-44 truncate"
            title="选择工程编译产出的 AXF/ELF 文件，自动匹配源码行号与调用栈"
          />
          <button
            v-if="axfPath"
            @click="clearAxfFile"
            class="p-0.5 text-zinc-500 hover:text-zinc-300 mr-1"
            title="清除 AXF 文件"
          >
            <X class="w-3.5 h-3.5" />
          </button>
          <button
            @click="pickAxfFile"
            class="p-1 hover:bg-zinc-800 text-zinc-400 hover:text-cyan-300 rounded transition-colors"
            title="浏览本地 AXF/ELF 固件目标文件"
          >
            <FolderOpen class="w-3.5 h-3.5 text-cyan-400" />
          </button>
        </div>

        <button
          @click="captureRegistersAndDiagnose"
          :disabled="isCapturing"
          class="flex items-center gap-2 px-3.5 py-1.5 bg-rose-600 hover:bg-rose-500 text-white rounded font-medium transition-colors shadow-sm disabled:opacity-40"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isCapturing }" />
          <span>{{ isCapturing ? '正在分析诊断...' : '一键抓取现场并诊断' }}</span>
        </button>

        <button
          v-if="coreRegisters || faultRegisters"
          @click="copyDiagnosticReport"
          class="flex items-center gap-1.5 px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded font-medium border border-zinc-700 transition-colors shadow-sm"
          title="复制当前完整的硬故障诊断分析与调用栈"
        >
          <component :is="isCopiedReport ? Check : Copy" class="w-3.5 h-3.5 text-emerald-400" />
          <span>{{ isCopiedReport ? '已复制' : '复制诊断' }}</span>
        </button>
      </div>
    </div>

    <!-- Error Alert if failed -->
    <div v-if="errorMsg" class="bg-rose-950/50 border border-rose-800/80 text-rose-300 p-3 rounded-lg flex items-center gap-2">
      <AlertTriangle class="w-4 h-4 text-rose-400 shrink-0" />
      <span>{{ errorMsg }}</span>
    </div>

    <!-- Active Stack Pointer & EXC_RETURN Banner -->
    <div v-if="deepAnalysis" class="bg-gradient-to-r from-zinc-900 via-zinc-900 to-zinc-950 border border-zinc-800 rounded-lg p-4 space-y-3">
      <div class="flex flex-wrap items-center justify-between gap-3 pb-2 border-b border-zinc-800/80">
        <div class="flex items-center gap-3">
          <div class="px-2.5 py-1 rounded font-bold text-xs flex items-center gap-1.5"
            :class="deepAnalysis.active_sp_name === 'PSP' ? 'bg-indigo-950 text-indigo-300 border border-indigo-700' : 'bg-cyan-950 text-cyan-300 border border-cyan-700'"
          >
            <Layers class="w-3.5 h-3.5" />
            <span>异常发生压栈指针: 【{{ deepAnalysis.active_sp_name }} ({{ deepAnalysis.active_sp_name === 'PSP' ? '进程/任务栈' : '主栈/中断栈' }})】</span>
          </div>
          <span class="font-mono text-zinc-300 text-xs">地址: <strong class="text-white">{{ deepAnalysis.active_sp_val }}</strong></span>
        </div>

        <div class="flex items-center gap-2 font-mono text-[11px] text-zinc-400">
          <span>EXC_RETURN:</span>
          <span class="px-2 py-0.5 rounded bg-zinc-800 font-bold text-amber-300">{{ deepAnalysis.exc_return.raw_hex }}</span>
          <span class="text-zinc-500">({{ deepAnalysis.exc_return.description }})</span>
        </div>
      </div>

      <!-- Real Crash Instruction Callout -->
      <div class="bg-rose-950/30 border border-rose-900/60 rounded p-3 flex flex-col md:flex-row md:items-center justify-between gap-2">
        <div class="space-y-1">
          <div class="text-[11px] text-rose-400 font-bold flex items-center gap-1.5">
            <ShieldAlert class="w-4 h-4" />
            <span>硬件压栈还原的真实崩溃发生点 (True Crash Location - Stacked PC)</span>
          </div>
          <div class="font-mono text-xs text-zinc-200 flex flex-wrap items-center gap-2">
            <span class="text-rose-300 font-bold">{{ deepAnalysis.exception_frame.pc }}</span>
            <span class="text-zinc-400">函数:</span>
            <span class="text-emerald-400 font-bold">{{ deepAnalysis.crash_location.func_name }}{{ deepAnalysis.crash_location.offset_str }}</span>
            <template v-if="deepAnalysis.crash_location.file_name">
              <span class="text-zinc-500">|</span>
              <span class="text-sky-300 font-semibold flex items-center gap-1">
                <FileText class="w-3.5 h-3.5 text-sky-400" />
                {{ deepAnalysis.crash_location.file_name }}:{{ deepAnalysis.crash_location.line }}
              </span>
            </template>
          </div>
        </div>

        <div class="flex items-center gap-3 font-mono text-[11px] text-zinc-400">
          <div>Stacked LR: <span class="text-amber-300 font-bold">{{ deepAnalysis.exception_frame.lr }}</span></div>
          <div>xPSR: <span class="text-zinc-300">{{ deepAnalysis.exception_frame.xpsr }}</span></div>
        </div>
      </div>

      <!-- Hardware Exception Stack Frame Register Values -->
      <div class="pt-1">
        <div class="text-[11px] text-zinc-400 mb-1.5 font-bold flex items-center gap-1">
          <Cpu class="w-3.5 h-3.5 text-zinc-500" />
          <span>硬件中断自动保存寄存器 (Stacked R0~R3, R12, LR, PC, xPSR)</span>
        </div>
        <div class="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-8 gap-2 font-mono text-center text-[11px]">
          <div class="bg-zinc-950 border border-zinc-800 rounded p-1">
            <span class="text-zinc-500 block text-[10px]">Stacked R0</span>
            <span class="text-zinc-200">{{ deepAnalysis.exception_frame.r0 }}</span>
          </div>
          <div class="bg-zinc-950 border border-zinc-800 rounded p-1">
            <span class="text-zinc-500 block text-[10px]">Stacked R1</span>
            <span class="text-zinc-200">{{ deepAnalysis.exception_frame.r1 }}</span>
          </div>
          <div class="bg-zinc-950 border border-zinc-800 rounded p-1">
            <span class="text-zinc-500 block text-[10px]">Stacked R2</span>
            <span class="text-zinc-200">{{ deepAnalysis.exception_frame.r2 }}</span>
          </div>
          <div class="bg-zinc-950 border border-zinc-800 rounded p-1">
            <span class="text-zinc-500 block text-[10px]">Stacked R3</span>
            <span class="text-zinc-200">{{ deepAnalysis.exception_frame.r3 }}</span>
          </div>
          <div class="bg-zinc-950 border border-zinc-800 rounded p-1">
            <span class="text-zinc-500 block text-[10px]">Stacked R12</span>
            <span class="text-zinc-200">{{ deepAnalysis.exception_frame.r12 }}</span>
          </div>
          <div class="bg-zinc-950 border border-amber-900/60 rounded p-1 bg-amber-950/10">
            <span class="text-amber-400 block text-[10px]">Stacked LR</span>
            <span class="text-amber-200 font-bold">{{ deepAnalysis.exception_frame.lr }}</span>
          </div>
          <div class="bg-zinc-950 border border-rose-900/60 rounded p-1 bg-rose-950/20">
            <span class="text-rose-400 block text-[10px]">Stacked PC</span>
            <span class="text-rose-200 font-bold">{{ deepAnalysis.exception_frame.pc }}</span>
          </div>
          <div class="bg-zinc-950 border border-zinc-800 rounded p-1">
            <span class="text-zinc-500 block text-[10px]">Stacked xPSR</span>
            <span class="text-zinc-200">{{ deepAnalysis.exception_frame.xpsr }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Dual Stack Call Tracing Section (PSP vs MSP) -->
    <div v-if="deepAnalysis" class="bg-zinc-900 border border-zinc-800 rounded-lg p-3.5 space-y-3">
      <div class="flex items-center justify-between border-b border-zinc-800 pb-2.5">
        <div class="flex items-center gap-2">
          <Layers class="w-4 h-4 text-emerald-400" />
          <span class="font-bold text-zinc-100 text-xs">异常调用栈回溯 (Call Stack Backtrace)</span>
          <span class="text-[11px] text-zinc-500 font-normal">支持源码行 address2line 及 Thumb-2 反汇编展开</span>
        </div>

        <!-- Stack Tabs: PSP vs MSP -->
        <div class="flex items-center bg-zinc-950 p-0.5 rounded border border-zinc-800">
          <button
            @click="activeStackTab = 'psp'"
            class="px-3 py-1 rounded text-xs font-medium transition-colors flex items-center gap-1.5"
            :class="activeStackTab === 'psp'
              ? 'bg-indigo-600 text-white shadow-sm'
              : 'text-zinc-400 hover:text-zinc-200'"
          >
            <span>进程栈 (PSP) 回溯</span>
            <span class="px-1.5 py-0.2 rounded-full text-[10px]" :class="activeStackTab === 'psp' ? 'bg-indigo-800 text-indigo-200' : 'bg-zinc-800 text-zinc-400'">
              {{ deepAnalysis.psp_call_stack.length }} 层
            </span>
            <span v-if="deepAnalysis.active_sp_name === 'PSP'" class="text-[10px] text-amber-300 font-bold">★异常现场</span>
          </button>

          <button
            @click="activeStackTab = 'msp'"
            class="px-3 py-1 rounded text-xs font-medium transition-colors flex items-center gap-1.5"
            :class="activeStackTab === 'msp'
              ? 'bg-cyan-600 text-white shadow-sm'
              : 'text-zinc-400 hover:text-zinc-200'"
          >
            <span>主栈 (MSP) 回溯</span>
            <span class="px-1.5 py-0.2 rounded-full text-[10px]" :class="activeStackTab === 'msp' ? 'bg-cyan-800 text-cyan-200' : 'bg-zinc-800 text-zinc-400'">
              {{ deepAnalysis.msp_call_stack.length }} 层
            </span>
            <span v-if="deepAnalysis.active_sp_name === 'MSP'" class="text-[10px] text-amber-300 font-bold">★异常现场</span>
          </button>
        </div>
      </div>

      <!-- Frames List -->
      <div class="space-y-2">
        <template v-if="(activeStackTab === 'psp' ? deepAnalysis.psp_call_stack : deepAnalysis.msp_call_stack).length === 0">
          <div class="p-6 text-center text-zinc-500 font-mono text-xs">
            该栈内未检测到有效的代码执行调用帧 (可能栈未初始化或已被重置)
          </div>
        </template>

        <div
          v-for="frame in (activeStackTab === 'psp' ? deepAnalysis.psp_call_stack : deepAnalysis.msp_call_stack)"
          :key="frame.frame_index"
          class="bg-zinc-950 border rounded-lg overflow-hidden transition-all"
          :class="frame.is_crash_instruction ? 'border-rose-600/70 bg-rose-950/10' : 'border-zinc-800/80'"
        >
          <!-- Frame Header -->
          <div
            @click="toggleFrame(frame.frame_index)"
            class="p-2.5 flex items-center justify-between cursor-pointer hover:bg-zinc-900/60 select-none"
          >
            <div class="flex items-center gap-2.5 font-mono text-xs">
              <span
                class="px-1.5 py-0.5 rounded text-[10px] font-bold"
                :class="frame.is_crash_instruction ? 'bg-rose-500 text-white' : 'bg-zinc-800 text-zinc-300'"
              >
                #{{ frame.frame_index }}
              </span>

              <span class="text-zinc-400 font-bold">{{ frame.return_address }}</span>

              <span class="text-emerald-400 font-bold">
                {{ frame.source_info.func_name }}
                <span class="text-zinc-500 text-[11px] font-normal">{{ frame.source_info.offset_str }}</span>
              </span>

              <span v-if="frame.is_crash_instruction" class="px-2 py-0.5 rounded text-[10px] bg-rose-950 text-rose-300 border border-rose-800 font-sans font-bold animate-pulse">
                💥 崩溃指令 (Crash Instruction)
              </span>

              <span v-if="frame.source_info.file_name" class="text-sky-300 text-[11px] font-sans flex items-center gap-1 border-l border-zinc-800 pl-2">
                <FileText class="w-3 h-3 text-sky-400" />
                {{ frame.source_info.file_name }}:{{ frame.source_info.line }}
              </span>
            </div>

            <div class="flex items-center gap-2 text-zinc-500">
              <span class="font-mono text-[10px]">栈顶偏移: {{ frame.address }}</span>
              <component :is="expandedFrames.has(frame.frame_index) ? ChevronDown : ChevronRight" class="w-4 h-4" />
            </div>
          </div>

          <!-- Expanded Frame Detail Body -->
          <div v-if="expandedFrames.has(frame.frame_index)" class="p-3 border-t border-zinc-800/80 bg-zinc-900/40 space-y-3">
            <!-- Full Source Path & Location -->
            <div v-if="frame.source_info.file_path" class="text-[11px] text-zinc-400 font-mono flex items-center gap-1.5">
              <span class="text-zinc-500">物理路径:</span>
              <span class="text-zinc-300">{{ frame.source_info.file_path }}:{{ frame.source_info.line }}</span>
            </div>

            <!-- Source Code Snippet Preview (address2line) -->
            <div v-if="frame.source_info.source_snippet && frame.source_info.source_snippet.length > 0" class="space-y-1">
              <div class="text-[11px] font-bold text-zinc-300 flex items-center gap-1.5">
                <Code class="w-3.5 h-3.5 text-cyan-400" />
                <span>源文件行预览 (Source Code Line Context)</span>
              </div>
              <div class="bg-zinc-950 border border-zinc-800 rounded p-2 font-mono text-[11px] overflow-x-auto space-y-0.5">
                <div
                  v-for="lineItem in frame.source_info.source_snippet"
                  :key="lineItem.line"
                  class="flex items-center px-1.5 py-0.5 rounded"
                  :class="lineItem.is_target ? 'bg-rose-950/60 text-rose-200 border-l-2 border-rose-500 font-bold' : 'text-zinc-400 hover:bg-zinc-900/40'"
                >
                  <span class="w-10 text-right pr-3 select-none" :class="lineItem.is_target ? 'text-rose-400 font-bold' : 'text-zinc-600'">
                    {{ lineItem.line }}
                  </span>
                  <span class="w-4 select-none" :class="lineItem.is_target ? 'text-rose-400 font-bold' : 'text-transparent'">
                    {{ lineItem.is_target ? '➔' : '' }}
                  </span>
                  <span class="flex-1 whitespace-pre">{{ lineItem.code }}</span>
                </div>
              </div>
            </div>

            <!-- Disassembly Preview Toggle -->
            <div class="pt-1">
              <div class="flex items-center justify-between mb-1.5">
                <button
                  @click="toggleDisasm(`frame_${frame.frame_index}`)"
                  class="text-[11px] text-cyan-400 hover:text-cyan-300 font-medium flex items-center gap-1 transition-colors"
                >
                  <Binary class="w-3.5 h-3.5" />
                  <span>{{ showDisassemblyMap[`frame_${frame.frame_index}`] ? '收起 Thumb-2 反汇编' : '展开 Thumb-2 反汇编指令视图' }}</span>
                </button>
              </div>

              <!-- Disassembly Table -->
              <div
                v-if="showDisassemblyMap[`frame_${frame.frame_index}`] && frame.disassembly && frame.disassembly.length > 0"
                class="bg-zinc-950 border border-zinc-800 rounded p-2 font-mono text-[11px] overflow-x-auto space-y-0.5"
              >
                <div
                  v-for="d in frame.disassembly"
                  :key="d.address"
                  class="flex items-center px-1.5 py-0.5 rounded"
                  :class="d.is_target ? 'bg-rose-950/50 text-rose-200 border-l-2 border-rose-500 font-bold' : 'text-zinc-400 hover:bg-zinc-900/40'"
                >
                  <span class="w-4 select-none" :class="d.is_target ? 'text-rose-400' : 'text-transparent'">
                    {{ d.is_target ? '➔' : '' }}
                  </span>
                  <span class="w-24 text-zinc-500 select-none">{{ d.address }}:</span>
                  <span class="w-20 text-zinc-600 select-none">{{ d.bytes }}</span>
                  <span class="w-16 font-bold" :class="d.is_target ? 'text-rose-400' : 'text-emerald-400'">{{ d.mnemonic }}</span>
                  <span class="flex-1 text-zinc-200">{{ d.op_str }}</span>
                  <span v-if="d.func_name" class="text-zinc-500 text-[10px] italic">;&lt;{{ d.func_name }}&gt;</span>
                </div>
              </div>

              <div
                v-else-if="showDisassemblyMap[`frame_${frame.frame_index}`] && (!frame.disassembly || frame.disassembly.length === 0)"
                class="bg-zinc-950 border border-zinc-800 rounded p-2 text-zinc-600 text-center italic text-[11px]"
              >
                该调用帧暂无反汇编指令缓存
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Crash PC Instruction Disassembly (Global View) -->
    <div v-if="deepAnalysis && deepAnalysis.crash_disassembly && deepAnalysis.crash_disassembly.length > 0" class="bg-zinc-900 border border-zinc-800 rounded-lg p-3.5 space-y-2">
      <div class="flex items-center justify-between">
        <div class="font-bold text-zinc-200 flex items-center gap-1.5 text-xs">
          <Binary class="w-4 h-4 text-rose-400" />
          <span>崩溃指令上下文 Thumb-2 反汇编 (Crash Instruction Disassembly)</span>
        </div>
        <span class="text-[10px] text-zinc-500 font-mono">通过 Capstone 反汇编引擎从目标内存直接反编译</span>
      </div>

      <div class="bg-zinc-950 border border-zinc-800 rounded p-2.5 font-mono text-[11px] overflow-x-auto space-y-1">
        <div
          v-for="d in deepAnalysis.crash_disassembly"
          :key="d.address"
          class="flex items-center px-1.5 py-0.5 rounded"
          :class="d.is_target ? 'bg-rose-950/70 text-rose-100 border-l-2 border-rose-500 font-bold shadow-sm' : 'text-zinc-400 hover:bg-zinc-900/40'"
        >
          <span class="w-5 select-none" :class="d.is_target ? 'text-rose-400 font-bold' : 'text-transparent'">
            {{ d.is_target ? '💥➔' : '' }}
          </span>
          <span class="w-24 text-zinc-500 select-none">{{ d.address }}:</span>
          <span class="w-20 text-zinc-600 select-none">{{ d.bytes }}</span>
          <span class="w-16 font-bold" :class="d.is_target ? 'text-rose-400' : 'text-emerald-400'">{{ d.mnemonic }}</span>
          <span class="flex-1 text-zinc-200">{{ d.op_str }}</span>
          <span v-if="d.file && d.line" class="text-sky-300 text-[10px] pl-2">[{{ d.file }}:{{ d.line }}]</span>
        </div>
      </div>
    </div>

    <!-- AI Diagnosis Recommendations (if available) -->
    <div v-if="aiRecommendations.length > 0" class="bg-amber-950/30 border border-amber-800/60 rounded-lg p-3.5 space-y-2">
      <div class="flex items-center gap-2 font-semibold text-amber-400">
        <Lightbulb class="w-4 h-4" />
        <span>AI 智能诊断排查建议 (Diagnostic Recommendations)</span>
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
          <button
            v-if="memoryDump"
            @click="copyMemoryDump"
            class="flex items-center gap-1 px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded border border-zinc-700 font-medium transition-colors"
            title="复制 Hex 与 ASCII 内存数据"
          >
            <component :is="isCopiedMemory ? Check : Copy" class="w-3 h-3 text-emerald-400" />
            <span>{{ isCopiedMemory ? '已复制' : '复制数据' }}</span>
          </button>
        </div>
      </div>

      <!-- Hex View Table -->
      <div v-if="memoryDump" class="bg-zinc-950 border border-zinc-800/80 rounded p-2.5 font-mono text-[11px] overflow-x-auto space-y-1 select-text">
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
