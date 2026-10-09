<script setup lang="ts">
import { ref, computed } from 'vue';
import { safeInvoke } from '../utils/ipc';
import {
  Download,
  RefreshCw,
  ChevronUp,
  ChevronDown,
  Layers,
  FolderOpen
} from '@lucide/vue';

const props = defineProps<{
  initialAddress?: string;
  isConnected: boolean;
}>();

// Target parameters
const dumpAddressHex = ref<string>(props.initialAddress || '0x02000000');
const dumpLengthBytes = ref<number>(4096);
const isLoading = ref<boolean>(false);
const statusMsg = ref<string>('');
const statusType = ref<'info' | 'success' | 'error'>('info');

// Data sources
const snapshotAName = ref<string>('快照 A (基准)');
const snapshotBName = ref<string>('快照 B (当前)');
const bufferA = ref<number[]>([]);
const bufferB = ref<number[]>([]);
const localFilePath = ref<string>('');

// Quick length presets
const lengthPresets = [
  { label: '1 KB', val: 1024 },
  { label: '4 KB (扇区)', val: 4096 },
  { label: '16 KB', val: 16384 },
  { label: '64 KB (Block)', val: 65536 },
  { label: '128 KB', val: 131072 }
];

// Calculated Diffs
interface DiffRow {
  offset: number;
  addrHex: string;
  bytesA: number[];
  bytesB: number[];
  hasDiff: boolean;
  diffCount: number;
}

const diffRows = computed<DiffRow[]>(() => {
  const maxLen = Math.max(bufferA.value.length, bufferB.value.length);
  if (maxLen === 0) return [];

  const rows: DiffRow[] = [];
  const baseAddr = parseInt(dumpAddressHex.value, 16) || 0;

  for (let i = 0; i < maxLen; i += 16) {
    const chunkA = bufferA.value.slice(i, i + 16);
    const chunkB = bufferB.value.slice(i, i + 16);

    // Pad to 16
    while (chunkA.length < 16) chunkA.push(0xFF);
    while (chunkB.length < 16) chunkB.push(0xFF);

    let diffCount = 0;
    for (let b = 0; b < 16; b++) {
      if (chunkA[b] !== chunkB[b]) diffCount++;
    }

    rows.push({
      offset: i,
      addrHex: '0x' + (baseAddr + i).toString(16).toUpperCase().padStart(8, '0'),
      bytesA: chunkA,
      bytesB: chunkB,
      hasDiff: diffCount > 0,
      diffCount
    });
  }

  return rows;
});

const totalDiffBytes = computed<number>(() => {
  let count = 0;
  const len = Math.min(bufferA.value.length, bufferB.value.length);
  for (let i = 0; i < len; i++) {
    if (bufferA.value[i] !== bufferB.value[i]) count++;
  }
  count += Math.abs(bufferA.value.length - bufferB.value.length);
  return count;
});

// Difference indices for navigation
const currentDiffIndex = ref<number>(-1);
const diffRowIndices = computed<number[]>(() => {
  const list: number[] = [];
  diffRows.value.forEach((r, idx) => {
    if (r.hasDiff) list.push(idx);
  });
  return list;
});

function navigateDiff(direction: 'prev' | 'next') {
  if (diffRowIndices.value.length === 0) return;
  if (direction === 'next') {
    currentDiffIndex.value = (currentDiffIndex.value + 1) % diffRowIndices.value.length;
  } else {
    currentDiffIndex.value = (currentDiffIndex.value - 1 + diffRowIndices.value.length) % diffRowIndices.value.length;
  }
  const targetRow = diffRowIndices.value[currentDiffIndex.value];
  const el = document.getElementById(`diff-row-${targetRow}`);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
}

// 1. Capture Snapshot A
async function captureSnapshotA() {
  isLoading.value = true;
  statusMsg.value = '正在从芯片读取快照 A...';
  statusType.value = 'info';
  try {
    const res: any = await safeInvoke('pyocd_read_memory', {
      address: dumpAddressHex.value,
      count: dumpLengthBytes.value,
      probeId: null,
      targetOverride: null
    });
    bufferA.value = res.bytes || [];
    snapshotAName.value = `快照 A (${new Date().toLocaleTimeString()}, ${bufferA.value.length} B)`;
    statusMsg.value = `成功捕获快照 A (${bufferA.value.length} 字节)`;
    statusType.value = 'success';
  } catch (err: any) {
    statusMsg.value = `读取快照 A 失败: ${err}`;
    statusType.value = 'error';
  } finally {
    isLoading.value = false;
  }
}

// 2. Capture Snapshot B
async function captureSnapshotB() {
  isLoading.value = true;
  statusMsg.value = '正在从芯片读取快照 B...';
  statusType.value = 'info';
  try {
    const res: any = await safeInvoke('pyocd_read_memory', {
      address: dumpAddressHex.value,
      count: dumpLengthBytes.value,
      probeId: null,
      targetOverride: null
    });
    bufferB.value = res.bytes || [];
    snapshotBName.value = `快照 B (${new Date().toLocaleTimeString()}, ${bufferB.value.length} B)`;
    statusMsg.value = `成功捕获快照 B (${bufferB.value.length} 字节)，差异比对已就绪`;
    statusType.value = 'success';
  } catch (err: any) {
    statusMsg.value = `读取快照 B 失败: ${err}`;
    statusType.value = 'error';
  } finally {
    isLoading.value = false;
  }
}

// 3. Load Local File for Source B
async function pickLocalFile() {
  try {
    const selected: string | null = await safeInvoke('pick_firmware_file', {
      title: '选择本地固件或内存镜像文件 (.bin / .hex)'
    });
    if (!selected) return;
    localFilePath.value = selected;
    statusMsg.value = `正在加载本地文件: ${selected}...`;
    const bytes: number[] = await safeInvoke('read_local_binary_file', { filePath: selected });
    bufferB.value = bytes.slice(0, dumpLengthBytes.value);
    snapshotBName.value = `本地文件: ${selected.split(/[\\/]/).pop()} (${bufferB.value.length} B)`;
    statusMsg.value = `本地文件加载完成 (${bufferB.value.length} 字节)`;
    statusType.value = 'success';
  } catch (err: any) {
    statusMsg.value = `加载本地文件失败: ${err}`;
    statusType.value = 'error';
  }
}

// 4. Dump Buffer A to local disk
async function dumpBufferAToDisk() {
  if (bufferA.value.length === 0) {
    alert('快照 A 数据为空，请先读取芯片内存');
    return;
  }
  try {
    const defaultName = `dump_${dumpAddressHex.value}_${Date.now()}.bin`;
    const blob = new Blob([new Uint8Array(bufferA.value)], { type: 'application/octet-stream' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = defaultName;
    a.click();
    URL.revokeObjectURL(url);
    statusMsg.value = `快照 A 已成功转储保存为 ${defaultName}`;
    statusType.value = 'success';
  } catch (err: any) {
    statusMsg.value = `转储导出失败: ${err}`;
    statusType.value = 'error';
  }
}

// Helper to format visible ascii
function toAscii(b: number): string {
  if (b >= 32 && b <= 126) return String.fromCharCode(b);
  return '.';
}
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-mono text-xs select-none overflow-hidden">
    <!-- Top Configuration Header -->
    <div class="bg-zinc-900 border-b border-zinc-800 p-3 flex items-center justify-between gap-3 shrink-0">
      <div class="flex items-center gap-2">
        <div class="p-1.5 rounded bg-cyan-950/60 border border-cyan-800/40 text-cyan-400">
          <Layers class="w-4 h-4" />
        </div>
        <div>
          <span class="font-bold text-zinc-100 font-sans">Flash / RAM 内存转储与双栏十六进制 Diff</span>
          <p class="text-[10.5px] text-zinc-400 font-sans">
            支持芯片内存快照两两比对，或芯片实时 Flash 内容与本地待烧录固件镜像比对。
          </p>
        </div>
      </div>

      <!-- Controls -->
      <div class="flex items-center gap-2">
        <!-- Address & Length Input -->
        <div class="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded px-2 py-1">
          <span class="text-zinc-500">起始地址:</span>
          <input
            v-model="dumpAddressHex"
            class="bg-transparent text-cyan-400 w-24 outline-none font-bold"
            placeholder="0x02000000"
          />
        </div>

        <div class="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded px-2 py-1">
          <span class="text-zinc-500">大小:</span>
          <select
            v-model.number="dumpLengthBytes"
            class="bg-transparent text-zinc-200 outline-none cursor-pointer"
          >
            <option v-for="p in lengthPresets" :key="p.val" :value="p.val">
              {{ p.label }}
            </option>
          </select>
        </div>

        <div class="h-4 w-[1px] bg-zinc-800 mx-1"></div>

        <!-- Mode Buttons -->
        <button
          @click="captureSnapshotA"
          :disabled="isLoading"
          class="flex items-center gap-1.5 px-3 py-1.5 bg-cyan-950 hover:bg-cyan-900 text-cyan-300 border border-cyan-800 rounded transition-colors disabled:opacity-50"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isLoading }" />
          <span>读取快照 A</span>
        </button>

        <button
          @click="captureSnapshotB"
          :disabled="isLoading"
          class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-950 hover:bg-emerald-900 text-emerald-300 border border-emerald-800 rounded transition-colors disabled:opacity-50"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isLoading }" />
          <span>读取快照 B</span>
        </button>

        <button
          @click="pickLocalFile"
          class="flex items-center gap-1.5 px-3 py-1.5 bg-purple-950 hover:bg-purple-900 text-purple-300 border border-purple-800 rounded transition-colors"
          title="加载本地 bin/hex 文件作为对比源 B"
        >
          <FolderOpen class="w-3.5 h-3.5" />
          <span>选择本地文件比对</span>
        </button>

        <button
          @click="dumpBufferAToDisk"
          :disabled="bufferA.length === 0"
          class="flex items-center gap-1.5 px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 rounded transition-colors disabled:opacity-50"
        >
          <Download class="w-3.5 h-3.5 text-cyan-400" />
          <span>转储保存快照 A</span>
        </button>
      </div>
    </div>

    <!-- Status & Diff Summary Bar -->
    <div class="bg-zinc-900/60 border-b border-zinc-800 px-4 py-1.5 flex items-center justify-between text-xs font-sans shrink-0">
      <div class="flex items-center gap-3">
        <span
          :class="[
            statusType === 'info' ? 'text-zinc-400' : '',
            statusType === 'success' ? 'text-emerald-400 font-semibold' : '',
            statusType === 'error' ? 'text-rose-400 font-semibold' : ''
          ]"
        >
          {{ statusMsg || '就绪。请点击“读取快照 A”和“读取快照 B”开始差异比对。' }}
        </span>
      </div>

      <div class="flex items-center gap-3 font-mono">
        <span class="text-zinc-400">
          差异字节数: <strong :class="totalDiffBytes > 0 ? 'text-amber-400 font-bold' : 'text-emerald-400'">{{ totalDiffBytes }}</strong> / {{ Math.max(bufferA.length, bufferB.length) }}
        </span>
        <span class="text-zinc-500">|</span>
        <span class="text-zinc-400">
          差异连续行: <strong class="text-amber-400">{{ diffRowIndices.length }}</strong> 处
        </span>

        <!-- Diff Navigator -->
        <div class="flex items-center gap-1 pl-2 border-l border-zinc-800">
          <button
            @click="navigateDiff('prev')"
            :disabled="diffRowIndices.length === 0"
            class="p-1 hover:bg-zinc-800 rounded text-zinc-400 hover:text-zinc-200 disabled:opacity-30"
            title="上一处差异"
          >
            <ChevronUp class="w-3.5 h-3.5" />
          </button>
          <span class="text-[11px] text-zinc-500">
            {{ diffRowIndices.length > 0 && currentDiffIndex >= 0 ? `${currentDiffIndex + 1}/${diffRowIndices.length}` : '-' }}
          </span>
          <button
            @click="navigateDiff('next')"
            :disabled="diffRowIndices.length === 0"
            class="p-1 hover:bg-zinc-800 rounded text-zinc-400 hover:text-zinc-200 disabled:opacity-30"
            title="下一处差异"
          >
            <ChevronDown class="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>

    <!-- Main Dual-Pane Hex Diff Table -->
    <div class="flex-1 flex flex-col overflow-hidden">
      <!-- Table Headers -->
      <div class="bg-zinc-900 border-b border-zinc-800 flex items-center text-[11px] text-zinc-400 font-mono py-1 select-none shrink-0">
        <div class="w-24 text-center text-zinc-500 shrink-0">基地址</div>
        <div class="flex-1 border-r border-zinc-800 px-3 flex items-center justify-between">
          <span class="text-cyan-400 font-bold font-sans">{{ snapshotAName }}</span>
          <span class="text-zinc-500">00 01 02 03 04 05 06 07 | 08 09 0A 0B 0C 0D 0E 0F  ASCII</span>
        </div>
        <div class="flex-1 px-3 flex items-center justify-between">
          <span class="text-emerald-400 font-bold font-sans">{{ snapshotBName }}</span>
          <span class="text-zinc-500">00 01 02 03 04 05 06 07 | 08 09 0A 0B 0C 0D 0E 0F  ASCII</span>
        </div>
      </div>

      <!-- Scrollable Diff Rows -->
      <div class="flex-1 overflow-y-auto divide-y divide-zinc-900">
        <template v-if="diffRows.length > 0">
          <div
            v-for="(row, rIdx) in diffRows"
            :id="`diff-row-${rIdx}`"
            :key="row.offset"
            class="flex items-center text-[11.5px] hover:bg-zinc-900/80 transition-colors py-0.5"
            :class="row.hasDiff ? 'bg-amber-950/20' : ''"
          >
            <!-- Offset -->
            <div
              class="w-24 text-center shrink-0 font-mono select-none"
              :class="row.hasDiff ? 'text-amber-400 font-bold' : 'text-zinc-500'"
            >
              {{ row.addrHex }}
            </div>

            <!-- Pane Left: Source A -->
            <div class="flex-1 border-r border-zinc-800 px-3 flex items-center justify-between">
              <div class="flex items-center gap-1.5 font-mono">
                <template v-for="(b, bIdx) in row.bytesA" :key="`a-${bIdx}`">
                  <span
                    class="rounded px-0.5 transition-all text-center w-5"
                    :class="[
                      b !== row.bytesB[bIdx] ? 'bg-amber-500 text-zinc-950 font-extrabold shadow-xs' : 'text-zinc-300',
                      b === 0xFF && b === row.bytesB[bIdx] ? 'text-zinc-600' : ''
                    ]"
                  >
                    {{ b.toString(16).padStart(2, '0').toUpperCase() }}
                  </span>
                  <span v-if="bIdx === 7" class="text-zinc-700 mx-0.5">|</span>
                </template>
              </div>

              <!-- ASCII A -->
              <div class="text-zinc-500 text-[10.5px] tracking-widest pl-2">
                {{ row.bytesA.map(toAscii).join('') }}
              </div>
            </div>

            <!-- Pane Right: Source B -->
            <div class="flex-1 px-3 flex items-center justify-between">
              <div class="flex items-center gap-1.5 font-mono">
                <template v-for="(b, bIdx) in row.bytesB" :key="`b-${bIdx}`">
                  <span
                    class="rounded px-0.5 transition-all text-center w-5"
                    :class="[
                      b !== row.bytesA[bIdx] ? 'bg-amber-500 text-zinc-950 font-extrabold shadow-xs' : 'text-zinc-300',
                      b === 0xFF && b === row.bytesA[bIdx] ? 'text-zinc-600' : ''
                    ]"
                  >
                    {{ b.toString(16).padStart(2, '0').toUpperCase() }}
                  </span>
                  <span v-if="bIdx === 7" class="text-zinc-700 mx-0.5">|</span>
                </template>
              </div>

              <!-- ASCII B -->
              <div class="text-zinc-500 text-[10.5px] tracking-widest pl-2">
                {{ row.bytesB.map(toAscii).join('') }}
              </div>
            </div>
          </div>
        </template>

        <div v-else class="h-64 flex flex-col items-center justify-center text-zinc-600">
          <Layers class="w-8 h-8 mb-2 stroke-1" />
          <p>暂无比对数据。请配置地址后点击“读取快照 A”和“读取快照 B”。</p>
        </div>
      </div>
    </div>
  </div>
</template>
