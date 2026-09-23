<script setup lang="ts">
import { ref } from 'vue';
import { safeInvoke } from '../utils/ipc';
import {
  Cpu,
  RefreshCw,
  FolderOpen,
  CheckCircle,
  AlertTriangle,
  Layers,
  Activity
} from '@lucide/vue';

const firmwarePath = ref<string>('');
const isScanning = ref<boolean>(false);
const errorMsg = ref<string>('');
const detectionResult = ref<any>(null);

async function handlePickFirmware() {
  try {
    const selected: string | null = await safeInvoke('pick_firmware_file', {
      title: '选择嵌入式固件文件 (.axf / .elf / .out)'
    });
    if (selected) {
      firmwarePath.value = selected;
      await runRtosDetection();
    }
  } catch (err: any) {
    errorMsg.value = `选择文件失败: ${err}`;
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
    errorMsg.value = `RTOS 探测执行失败: ${err}`;
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
        <span>RTOS 任务内核实时 Trace 探测器 (Non-intrusive SWD 内存扫描)</span>
      </div>

      <div class="flex items-center gap-2 flex-1 max-w-xl">
        <div class="relative flex-1 flex items-center">
          <input
            v-model="firmwarePath"
            type="text"
            placeholder="选择固件 .axf / .elf / .out 文件"
            class="w-full bg-zinc-950 border border-zinc-800 rounded px-3 py-1.5 pr-24 text-zinc-200 text-xs outline-none focus:border-purple-500 font-mono"
            @keyup.enter="runRtosDetection"
          />
          <button
            @click="handlePickFirmware"
            type="button"
            class="absolute right-1 px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-purple-400 rounded text-xs flex items-center gap-1 transition-colors border border-zinc-700/80"
          >
            <FolderOpen class="w-3.5 h-3.5" />
            <span>浏览固件</span>
          </button>
        </div>

        <button
          @click="runRtosDetection"
          :disabled="isScanning || !firmwarePath.trim()"
          class="flex items-center gap-1.5 px-3 py-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded text-xs font-semibold transition-colors disabled:opacity-40 shrink-0"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isScanning }" />
          <span>探测内核</span>
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
          <div class="text-[10px] text-zinc-400 mb-1">识别到的操作系统 (RTOS Type)</div>
          <div class="text-base font-bold flex items-center gap-2" :class="detectionResult.detected ? 'text-purple-400' : 'text-amber-400'">
            <CheckCircle v-if="detectionResult.detected" class="w-4 h-4 text-emerald-400" />
            <AlertTriangle v-else class="w-4 h-4 text-amber-400" />
            <span>{{ detectionResult.rtos_type }}</span>
          </div>
        </div>

        <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div class="text-[10px] text-zinc-400 mb-1">特征匹配置信度 (Confidence)</div>
          <div class="text-base font-bold text-zinc-200">
            {{ detectionResult.confidence || '0/0' }}
          </div>
        </div>

        <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3">
          <div class="text-[10px] text-zinc-400 mb-1">内核状态 (Kernel State)</div>
          <div class="text-base font-bold text-emerald-400">
            {{ detectionResult.detected ? '已锁定关键符号基址' : '未检测到已知 RTOS' }}
          </div>
        </div>
      </div>

      <!-- Matched Symbols Table -->
      <div v-if="detectionResult?.matched_symbols && Object.keys(detectionResult.matched_symbols).length > 0" class="border border-zinc-800 rounded-lg overflow-hidden bg-zinc-900/60">
        <div class="bg-zinc-900 px-3 py-2 border-b border-zinc-800 flex items-center justify-between text-xs font-semibold text-zinc-200">
          <div class="flex items-center gap-1.5">
            <Layers class="w-3.5 h-3.5 text-purple-400" />
            <span>内核特征控制块物理地址 (DWARF Symbols)</span>
          </div>
          <span class="text-[10px] text-zinc-500 font-normal">零侵入 SWD 内存映射</span>
        </div>

        <table class="w-full text-left text-xs font-mono">
          <thead class="bg-zinc-950/60 text-zinc-400 text-[10px] border-b border-zinc-800">
            <tr>
              <th class="p-2.5">内核变量 / 结构体符号</th>
              <th class="p-2.5">SRAM 物理地址</th>
              <th class="p-2.5">作用说明</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-zinc-800/60">
            <tr v-for="(addr, symName) in detectionResult.matched_symbols" :key="symName" class="hover:bg-zinc-900/80">
              <td class="p-2.5 font-bold text-zinc-200">{{ symName }}</td>
              <td class="p-2.5 text-emerald-400">{{ addr }}</td>
              <td class="p-2.5 text-zinc-400 text-[11px]">
                <span v-if="String(symName).includes('Ready') || String(symName).includes('ready')">就绪任务优先级链表</span>
                <span v-else-if="String(symName).includes('Current') || String(symName).includes('Cur') || String(symName).includes('curr')">当前正在运行的 TCB 控制块指针</span>
                <span v-else-if="String(symName).includes('Config') || String(symName).includes('config')">操作系统内核全局配置表</span>
                <span v-else-if="String(symName).includes('Info') || String(symName).includes('info')">操作系统运行状态信息块</span>
                <span v-else-if="String(symName).includes('Tick') || String(symName).includes('clock')">系统全局滴答计数器 (Tick Counter)</span>
                <span v-else-if="String(symName).includes('created') || String(symName).includes('Tbl')">系统创建的所有任务/线程链表入口</span>
                <span v-else>操作系统内核内部关键调试指针</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- No Selection Prompt -->
      <div v-else-if="!isScanning" class="p-12 text-center text-zinc-500 space-y-3">
        <Activity class="w-10 h-10 mx-auto text-zinc-700 animate-pulse" />
        <div class="text-sm font-medium text-zinc-400">选择嵌入式固件文件 (.axf / .elf / .out) 即可自动侦测 RTOS</div>
        <div class="text-[11px] text-zinc-600 max-w-md mx-auto">
          无需在下位机代码中插入任何打印或 Trace 宏，通过解析 DWARF 符号表自动识别 FreeRTOS、RTX5、ThreadX、uCOS-II、uCOS-III 或 RT-Thread，并通过探针读取全量任务链表与栈空间。
        </div>
      </div>
    </div>
  </div>
</template>
