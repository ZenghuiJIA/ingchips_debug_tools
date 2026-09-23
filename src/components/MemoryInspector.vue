<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue';
import { safeInvoke } from '../utils/ipc';
import {
  Database,
  RefreshCw,
  Play,
  Pause,
  Copy,
  Download,
  Upload,
  Check,
  AlertCircle,
  X,
  Sparkles,
  MousePointer
} from '@lucide/vue';

defineProps<{
  isConnected: boolean;
}>();

// --- View Format Mode ---
export type ViewFormat = '8bit' | '16bit' | '32bit' | '64bit';
const viewFormat = ref<ViewFormat>('8bit');

// --- Memory State ---
const addressInput = ref<string>('0x20000000');
const byteCount = ref<number>(256);
const isLoading = ref<boolean>(false);
const autoRefresh = ref<boolean>(false);
const refreshIntervalMs = ref<number>(1000);
const errorMessage = ref<string>('');
const lastReadTime = ref<string>('');

const memoryBytes = ref<number[]>([]);
const previousBytes = ref<number[]>([]);
const changedIndices = ref<Set<number>>(new Set());

// --- Selection State (supports multi-byte range selection) ---
const selectedStartIndex = ref<number | null>(null);
const selectedByteCount = ref<number>(1);

// Inline Editing State
const editingStartIndex = ref<number | null>(null);
const editingChunkSize = ref<number>(1);
const editingValue = ref<string>('');
const isWritingByte = ref<boolean>(false);
const copySuccess = ref<boolean>(false);

let autoRefreshTimer: any = null;
let diffFadeTimer: any = null;

// --- Modal States ---
const isDumpModalOpen = ref<boolean>(false);
const dumpAddress = ref<string>('0x08000000');
const dumpSizeKb = ref<number>(64);
const dumpFilePath = ref<string>('D:\\firmware_backup.bin');
const isDumping = ref<boolean>(false);
const dumpStatus = ref<string>('');

const isLoadModalOpen = ref<boolean>(false);
const loadAddress = ref<string>('0x20000000');
const loadFilePath = ref<string>('');
const isUploading = ref<boolean>(false);
const loadStatus = ref<string>('');

// --- Parsed Base Address ---
const parsedBaseAddress = computed<number>(() => {
  const raw = addressInput.value.trim();
  if (raw.toLowerCase().startsWith('0x')) {
    return parseInt(raw, 16) || 0;
  }
  return parseInt(raw, 16) || 0;
});

// Quick address shortcuts
const QUICK_TARGETS = [
  { label: 'SRAM 起始', addr: '0x20000000' },
  { label: 'Flash 起始', addr: '0x08000000' },
  { label: '向量表/ROM', addr: '0x00000000' },
  { label: '外设基址 (APB/AHB)', addr: '0x40000000' },
];

function setQuickAddress(addr: string) {
  addressInput.value = addr;
  handleReadMemory();
}

// --- Read Memory (Manual trigger required, no auto-read on tab switch) ---
async function handleReadMemory() {
  if (isLoading.value) return;
  isLoading.value = true;
  errorMessage.value = '';

  try {
    const res: any = await safeInvoke('pyocd_read_memory', {
      address: addressInput.value.trim(),
      count: Number(byteCount.value) || 256,
      probeId: null,
      targetOverride: null,
    });

    const newBytes: number[] = res.bytes || [];
    const newChanged = new Set<number>();

    if (previousBytes.value.length === newBytes.length) {
      for (let i = 0; i < newBytes.length; i++) {
        if (previousBytes.value[i] !== newBytes[i]) {
          newChanged.add(i);
        }
      }
    }

    previousBytes.value = [...newBytes];
    memoryBytes.value = newBytes;
    changedIndices.value = newChanged;
    lastReadTime.value = new Date().toLocaleTimeString();

    // Default select first byte if none selected
    if (selectedStartIndex.value === null && newBytes.length > 0) {
      selectedStartIndex.value = 0;
      selectedByteCount.value = 1;
    }

    // Auto clear diff highlight after 1.5s
    if (diffFadeTimer) clearTimeout(diffFadeTimer);
    diffFadeTimer = setTimeout(() => {
      changedIndices.value = new Set();
    }, 1500);

  } catch (err: any) {
    errorMessage.value = `读取内存失败: ${err}`;
  } finally {
    isLoading.value = false;
  }
}

// --- Auto Refresh Controller ---
function toggleAutoRefresh() {
  autoRefresh.value = !autoRefresh.value;
  if (autoRefresh.value) {
    handleReadMemory();
    autoRefreshTimer = setInterval(() => {
      handleReadMemory();
    }, refreshIntervalMs.value);
  } else {
    if (autoRefreshTimer) {
      clearInterval(autoRefreshTimer);
      autoRefreshTimer = null;
    }
  }
}

watch(refreshIntervalMs, () => {
  if (autoRefresh.value) {
    if (autoRefreshTimer) clearInterval(autoRefreshTimer);
    autoRefreshTimer = setInterval(() => {
      handleReadMemory();
    }, refreshIntervalMs.value);
  }
});

// --- Selection Handlers ---
function handleByteClick(idx: number, event: MouseEvent) {
  if (event.shiftKey && selectedStartIndex.value !== null) {
    const start = Math.min(selectedStartIndex.value, idx);
    const end = Math.max(selectedStartIndex.value, idx);
    selectedStartIndex.value = start;
    selectedByteCount.value = end - start + 1;
  } else {
    selectedStartIndex.value = idx;
    selectedByteCount.value = 1;
  }
}

function handleChunkClick(startIdx: number, size: number) {
  selectedStartIndex.value = startIdx;
  selectedByteCount.value = size;
}

function setSelectionLength(len: number) {
  if (selectedStartIndex.value === null) {
    selectedStartIndex.value = 0;
  }
  selectedByteCount.value = len;
}

function isByteSelected(idx: number): boolean {
  if (selectedStartIndex.value === null) return false;
  return idx >= selectedStartIndex.value && idx < selectedStartIndex.value + selectedByteCount.value;
}

// --- Inline Chunk Editing (Supports 8/16/32/64-bit Little-Endian) ---
function startEditChunk(startIdx: number, chunkSize: number) {
  editingStartIndex.value = startIdx;
  editingChunkSize.value = chunkSize;
  // Format as Little-Endian hex string with MSB first for editing convenience
  let hex = '';
  for (let i = chunkSize - 1; i >= 0; i--) {
    const b = memoryBytes.value[startIdx + i] ?? 0;
    hex += b.toString(16).padStart(2, '0').toUpperCase();
  }
  editingValue.value = hex;
}

function cancelEdit() {
  editingStartIndex.value = null;
  editingChunkSize.value = 1;
  editingValue.value = '';
}

async function commitEditChunk() {
  if (editingStartIndex.value === null) return;
  const startIdx = editingStartIndex.value;
  const size = editingChunkSize.value;
  const rawHex = editingValue.value.trim();

  const expectedLength = size * 2;
  if (rawHex.length !== expectedLength || !/^[0-9a-fA-F]+$/.test(rawHex)) {
    alert(`请输入有效的 ${expectedLength} 位十六进制字符 (如 ${size === 1 ? 'FF' : size === 2 ? 'FFFF' : size === 4 ? '12345678' : '0123456789ABCDEF'})`);
    return;
  }

  isWritingByte.value = true;
  try {
    // Parse Little-Endian: rawHex has MSB first, so chunk[0] is the last 2 hex chars
    for (let i = 0; i < size; i++) {
      const hexByte = rawHex.slice((size - 1 - i) * 2, (size - i) * 2);
      const val = parseInt(hexByte, 16);
      const addrHex = `0x${(parsedBaseAddress.value + startIdx + i).toString(16).toUpperCase()}`;
      await safeInvoke('pyocd_write_memory_byte', {
        address: addrHex,
        value: val,
        probeId: null,
        targetOverride: null,
      });
      memoryBytes.value[startIdx + i] = val;
      previousBytes.value[startIdx + i] = val;
    }
    editingStartIndex.value = null;
    editingValue.value = '';
  } catch (err: any) {
    alert(`写入内存失败: ${err}`);
  } finally {
    isWritingByte.value = false;
  }
}

// --- Data Inspector Computations (supports full 64-bit BigInt and multi-byte parsing) ---
const selectedAddressHex = computed<string>(() => {
  if (selectedStartIndex.value === null) return '--';
  const start = parsedBaseAddress.value + selectedStartIndex.value;
  if (selectedByteCount.value > 1) {
    const end = start + selectedByteCount.value - 1;
    return `0x${start.toString(16).padStart(8, '0').toUpperCase()} ~ 0x${end.toString(16).padStart(8, '0').toUpperCase()} (${selectedByteCount.value} 字节)`;
  }
  return `0x${start.toString(16).padStart(8, '0').toUpperCase()}`;
});

const inspectorValues = computed(() => {
  if (selectedStartIndex.value === null || selectedStartIndex.value >= memoryBytes.value.length) {
    return null;
  }
  const idx = selectedStartIndex.value;
  const count = selectedByteCount.value;
  const slice = memoryBytes.value.slice(idx, idx + count);

  const b0 = slice[0] ?? 0;
  const b1 = slice[1] ?? 0;
  const b2 = slice[2] ?? 0;
  const b3 = slice[3] ?? 0;

  // uint8 & int8
  const u8 = b0;
  const i8 = (b0 & 0x80) ? b0 - 0x100 : b0;

  // uint16 & int16 (Little Endian)
  const u16 = (b1 << 8) | b0;
  const i16 = (u16 & 0x8000) ? u16 - 0x10000 : u16;

  // uint32 & int32 (Little Endian)
  const u32 = ((b3 << 24) | (b2 << 16) | (b1 << 8) | b0) >>> 0;
  const i32 = (b3 << 24) | (b2 << 16) | (b1 << 8) | b0;

  // float32 (Little Endian)
  const buf32 = new ArrayBuffer(4);
  const view32 = new DataView(buf32);
  view32.setUint8(0, b0);
  view32.setUint8(1, b1);
  view32.setUint8(2, b2);
  view32.setUint8(3, b3);
  const f32 = view32.getFloat32(0, true);

  // uint64 & int64 (Little Endian via BigInt)
  let u64 = 0n;
  for (let i = 0; i < 8; i++) {
    const b = BigInt(slice[i] ?? 0);
    u64 |= (b << BigInt(i * 8));
  }
  const i64 = BigInt.asIntN(64, u64);

  // float64 (double, Little Endian)
  const buf64 = new ArrayBuffer(8);
  const view64 = new DataView(buf64);
  for (let i = 0; i < 8; i++) {
    view64.setUint8(i, slice[i] ?? 0);
  }
  const f64 = view64.getFloat64(0, true);

  // ASCII string from selected range
  const asciiStr = slice.map(b => (b >= 32 && b <= 126 ? String.fromCharCode(b) : '.')).join('');

  // Hex dump of selected range
  const hexDumpStr = slice.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');

  return {
    u8,
    i8,
    u16,
    i16,
    u32,
    i32,
    f32: isNaN(f32) ? 'NaN' : f32.toExponential(4),
    u64Str: u64.toString(),
    u64Hex: '0x' + u64.toString(16).toUpperCase().padStart(16, '0'),
    i64Str: i64.toString(),
    f64Str: isNaN(f64) ? 'NaN' : f64.toExponential(6),
    bin8: b0.toString(2).padStart(8, '0'),
    asciiStr,
    hexDumpStr,
    count
  };
});

// --- Copy Formatted Hex View ---
function copyFormattedHex() {
  if (memoryBytes.value.length === 0) return;
  const lines: string[] = [];
  const base = parsedBaseAddress.value;

  for (let i = 0; i < memoryBytes.value.length; i += 16) {
    const rowAddr = `0x${(base + i).toString(16).padStart(8, '0').toUpperCase()}`;
    const chunk = memoryBytes.value.slice(i, i + 16);

    let formattedRow = '';
    if (viewFormat.value === '8bit') {
      const hexParts = chunk.map(b => b.toString(16).padStart(2, '0').toUpperCase());
      while (hexParts.length < 16) hexParts.push('  ');
      formattedRow = `${hexParts.slice(0, 8).join(' ')}  |  ${hexParts.slice(8, 16).join(' ')}`;
    } else if (viewFormat.value === '16bit') {
      const parts: string[] = [];
      for (let j = 0; j < 16; j += 2) {
        if (j < chunk.length) {
          const b0 = chunk[j];
          const b1 = chunk[j + 1] ?? 0;
          parts.push(`${b1.toString(16).padStart(2, '0')}${b0.toString(16).padStart(2, '0')}`.toUpperCase());
        }
      }
      formattedRow = parts.join(' ');
    } else if (viewFormat.value === '32bit') {
      const parts: string[] = [];
      for (let j = 0; j < 16; j += 4) {
        if (j < chunk.length) {
          let word = '';
          for (let k = 3; k >= 0; k--) {
            const b = chunk[j + k] ?? 0;
            word += b.toString(16).padStart(2, '0');
          }
          parts.push(word.toUpperCase());
        }
      }
      formattedRow = parts.join(' ');
    } else {
      const parts: string[] = [];
      for (let j = 0; j < 16; j += 8) {
        if (j < chunk.length) {
          let dword = '';
          for (let k = 7; k >= 0; k--) {
            const b = chunk[j + k] ?? 0;
            dword += b.toString(16).padStart(2, '0');
          }
          parts.push(dword.toUpperCase());
        }
      }
      formattedRow = parts.join(' ');
    }

    const ascii = chunk.map(b => (b >= 32 && b <= 126 ? String.fromCharCode(b) : '.')).join('');
    lines.push(`${rowAddr}:  ${formattedRow.padEnd(52, ' ')}  |${ascii}|`);
  }

  navigator.clipboard.writeText(lines.join('\n'));
  copySuccess.value = true;
  setTimeout(() => (copySuccess.value = false), 2000);
}

// --- Dump Memory to File ---
async function handleExecuteDump() {
  if (!dumpFilePath.value.trim()) {
    alert('请输入导出的目标文件绝对物理路径');
    return;
  }
  isDumping.value = true;
  dumpStatus.value = '正在分块读取目标芯片内存并写入文件...';

  try {
    const totalBytes = Number(dumpSizeKb.value) * 1024;
    const res: any = await safeInvoke('pyocd_dump_memory_to_file', {
      address: dumpAddress.value.trim(),
      count: totalBytes,
      filePath: dumpFilePath.value.trim(),
      probeId: null,
      targetOverride: null,
    });
    dumpStatus.value = `✔ 转储完成！成功导出 ${res.count} 字节到: ${res.file_path}`;
  } catch (err: any) {
    dumpStatus.value = `❌ 转储失败: ${err}`;
  } finally {
    isDumping.value = false;
  }
}

// --- Load File to Memory ---
async function handleExecuteLoad() {
  if (!loadFilePath.value.trim()) {
    alert('请输入要加载的本地 .bin 文件的绝对物理路径');
    return;
  }
  isUploading.value = true;
  loadStatus.value = '正在将本地二进制文件写入目标 RAM...';

  try {
    const res: any = await safeInvoke('pyocd_load_file_to_memory', {
      address: loadAddress.value.trim(),
      filePath: loadFilePath.value.trim(),
      probeId: null,
      targetOverride: null,
    });
    loadStatus.value = `✔ 载入完成！成功写入 ${res.count} 字节至 ${res.address}`;
    handleReadMemory();
  } catch (err: any) {
    loadStatus.value = `❌ 载入失败: ${err}`;
  } finally {
    isUploading.value = false;
  }
}

// --- Lifecycle (No auto-reading on mount per user requirement) ---
onMounted(() => {
  // Do not read automatically. User must explicitly click "读取"
});

onUnmounted(() => {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer);
  if (diffFadeTimer) clearTimeout(diffFadeTimer);
});

// Helper for formatted chunk rendering
function getChunkHex(startIdx: number, size: number): string {
  let hex = '';
  for (let i = size - 1; i >= 0; i--) {
    const b = memoryBytes.value[startIdx + i] ?? 0;
    hex += b.toString(16).padStart(2, '0').toUpperCase();
  }
  return hex;
}

function isChunkChanged(startIdx: number, size: number): boolean {
  for (let i = 0; i < size; i++) {
    if (changedIndices.value.has(startIdx + i)) return true;
  }
  return false;
}
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-mono text-xs overflow-hidden select-text">
    <!-- Top Control Bar -->
    <div class="bg-zinc-900 border-b border-zinc-800 px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 shrink-0">
      <!-- Address & Quick Select -->
      <div class="flex flex-wrap items-center gap-2">
        <div class="flex items-center gap-1.5 text-zinc-200 font-semibold mr-1">
          <Database class="w-4 h-4 text-emerald-400" />
          <span>内存查看与修改</span>
        </div>

        <div class="h-4 w-px bg-zinc-800 hidden sm:block"></div>

        <!-- Address input -->
        <div class="flex items-center gap-1">
          <span class="text-zinc-400 text-[11px]">基址:</span>
          <input
            v-model="addressInput"
            @keyup.enter="handleReadMemory"
            type="text"
            placeholder="0x20000000"
            class="w-28 bg-zinc-950 border border-zinc-700 focus:border-emerald-500 rounded px-2 py-1 text-zinc-200 text-xs font-mono outline-none"
          />
        </div>

        <!-- Length selector -->
        <div class="flex items-center gap-1">
          <span class="text-zinc-400 text-[11px]">长度:</span>
          <select
            v-model="byteCount"
            class="bg-zinc-950 border border-zinc-700 rounded px-1.5 py-1 text-zinc-200 text-xs focus:outline-none"
          >
            <option :value="64">64 B</option>
            <option :value="128">128 B</option>
            <option :value="256">256 B</option>
            <option :value="512">512 B</option>
            <option :value="1024">1 KB</option>
            <option :value="2048">2 KB</option>
            <option :value="4096">4 KB</option>
          </select>
        </div>

        <!-- Read Now Button -->
        <button
          @click="handleReadMemory"
          :disabled="isLoading"
          class="flex items-center gap-1.5 px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs font-medium transition-colors disabled:opacity-50 shadow-sm"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isLoading }" />
          <span>读取</span>
        </button>

        <!-- View Format Mode Toggle (8-bit / 16-bit / 32-bit / 64-bit) -->
        <div class="flex items-center bg-zinc-950 p-0.5 rounded border border-zinc-800 ml-1">
          <button
            @click="viewFormat = '8bit'"
            class="px-2 py-0.5 rounded text-[11px] font-mono transition-colors"
            :class="viewFormat === '8bit' ? 'bg-emerald-600 text-white font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            title="单字节展示 (8-bit uint8)"
          >
            8 bit
          </button>
          <button
            @click="viewFormat = '16bit'"
            class="px-2 py-0.5 rounded text-[11px] font-mono transition-colors"
            :class="viewFormat === '16bit' ? 'bg-emerald-600 text-white font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            title="双字节小端展示 (16-bit uint16 LE)"
          >
            16 bit
          </button>
          <button
            @click="viewFormat = '32bit'"
            class="px-2 py-0.5 rounded text-[11px] font-mono transition-colors"
            :class="viewFormat === '32bit' ? 'bg-emerald-600 text-white font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            title="四字节小端展示 (32-bit uint32 LE)"
          >
            32 bit
          </button>
          <button
            @click="viewFormat = '64bit'"
            class="px-2 py-0.5 rounded text-[11px] font-mono transition-colors"
            :class="viewFormat === '64bit' ? 'bg-emerald-600 text-white font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            title="八字节小端展示 (64-bit uint64 LE)"
          >
            64 bit
          </button>
        </div>

        <!-- Auto Refresh Toggle -->
        <button
          @click="toggleAutoRefresh"
          class="flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium border transition-colors shadow-sm ml-1"
          :class="autoRefresh
            ? 'bg-cyan-950 text-cyan-300 border-cyan-700 animate-pulse'
            : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
        >
          <component :is="autoRefresh ? Pause : Play" class="w-3.5 h-3.5" />
          <span>{{ autoRefresh ? '自动刷新中' : '自动刷新' }}</span>
        </button>
      </div>

      <!-- Quick targets & File actions -->
      <div class="flex items-center gap-1.5">
        <!-- Quick targets dropdown -->
        <div class="hidden xl:flex items-center gap-1">
          <button
            v-for="target in QUICK_TARGETS"
            :key="target.addr"
            @click="setQuickAddress(target.addr)"
            class="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-[11px] border border-zinc-700 transition-colors"
          >
            {{ target.label }}
          </button>
        </div>

        <!-- Copy View -->
        <button
          @click="copyFormattedHex"
          class="px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 rounded text-xs flex items-center gap-1 transition-colors"
          title="复制当前内存格式化十六进制视图到剪贴板"
        >
          <component :is="copySuccess ? Check : Copy" class="w-3.5 h-3.5" :class="{ 'text-emerald-400': copySuccess }" />
          <span>{{ copySuccess ? '已复制' : '复制Hex' }}</span>
        </button>

        <!-- Dump to Bin File -->
        <button
          @click="isDumpModalOpen = true"
          class="px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-cyan-300 border border-cyan-800/80 rounded text-xs flex items-center gap-1.5 transition-colors"
          title="将芯片 Flash/RAM 任意大段内存导出保存为本地 .bin 文件"
        >
          <Download class="w-3.5 h-3.5 text-cyan-400" />
          <span>Dump到Bin</span>
        </button>

        <!-- Load Bin to RAM -->
        <button
          @click="isLoadModalOpen = true"
          class="px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-purple-300 border border-purple-800/80 rounded text-xs flex items-center gap-1.5 transition-colors"
          title="将本地 .bin 文件直接加载写入到单片机 RAM 内存"
        >
          <Upload class="w-3.5 h-3.5 text-purple-400" />
          <span>加载Bin到RAM</span>
        </button>
      </div>
    </div>

    <!-- Error Banner -->
    <div v-if="errorMessage" class="bg-rose-950/80 border-b border-rose-800 px-4 py-1.5 text-rose-300 text-xs flex items-center justify-between">
      <div class="flex items-center gap-2">
        <AlertCircle class="w-4 h-4 shrink-0 text-rose-400" />
        <span>{{ errorMessage }}</span>
      </div>
      <button @click="errorMessage = ''" class="hover:text-white"><X class="w-3.5 h-3.5" /></button>
    </div>

    <!-- Main Content Split Area: Left Hex Grid, Right Data Inspector -->
    <div class="flex-1 flex flex-col lg:flex-row overflow-hidden">
      <!-- Hex Editor Grid -->
      <div class="flex-1 flex flex-col overflow-hidden border-r border-zinc-800">
        <!-- Hex Table Header -->
        <div class="bg-zinc-900/90 border-b border-zinc-800 px-4 py-1.5 text-[11px] text-zinc-400 font-mono flex items-center select-none shrink-0">
          <span class="w-24 text-zinc-500">偏移地址</span>
          <div class="flex-1 flex items-center gap-2">
            <!-- 8-bit Header -->
            <template v-if="viewFormat === '8bit'">
              <div class="grid grid-cols-8 gap-x-2 w-56 text-center text-zinc-500">
                <span>00</span><span>01</span><span>02</span><span>03</span>
                <span>04</span><span>05</span><span>06</span><span>07</span>
              </div>
              <span class="text-zinc-700">|</span>
              <div class="grid grid-cols-8 gap-x-2 w-56 text-center text-zinc-500">
                <span>08</span><span>09</span><span>0A</span><span>0B</span>
                <span>0C</span><span>0D</span><span>0E</span><span>0F</span>
              </div>
            </template>

            <!-- 16-bit Header -->
            <template v-else-if="viewFormat === '16bit'">
              <div class="grid grid-cols-8 gap-x-3 w-[470px] text-center text-zinc-500">
                <span>+00</span><span>+02</span><span>+04</span><span>+06</span>
                <span>+08</span><span>+0A</span><span>+0C</span><span>+0E</span>
              </div>
            </template>

            <!-- 32-bit Header -->
            <template v-else-if="viewFormat === '32bit'">
              <div class="grid grid-cols-4 gap-x-4 w-[470px] text-center text-zinc-500">
                <span>+00 (Word 0)</span><span>+04 (Word 1)</span><span>+08 (Word 2)</span><span>+0C (Word 3)</span>
              </div>
            </template>

            <!-- 64-bit Header -->
            <template v-else>
              <div class="grid grid-cols-2 gap-x-6 w-[470px] text-center text-zinc-500">
                <span>+00 (DoubleWord 0)</span><span>+08 (DoubleWord 1)</span>
              </div>
            </template>
          </div>
          <span class="w-40 text-left text-zinc-500 pl-4 border-l border-zinc-800">ASCII 文本</span>
        </div>

        <!-- Hex Rows Scroll Area -->
        <div class="flex-1 overflow-y-auto p-4 space-y-1 font-mono text-xs">
          <div v-if="memoryBytes.length === 0" class="h-full flex flex-col items-center justify-center text-zinc-500 space-y-2 py-16">
            <Database class="w-10 h-10 text-zinc-700 mb-1" />
            <div class="text-zinc-400 font-bold">暂无内存数据，请连接调试器后点击「读取」</div>
            <div class="text-zinc-600 text-[11px]">可输入目标物理基址 (如 0x20000000) 与长度后点击上方读取按钮</div>
          </div>

          <!-- Rows (16 bytes per line) -->
          <div
            v-for="rowIdx in Math.ceil(memoryBytes.length / 16)"
            :key="rowIdx"
            class="flex items-center hover:bg-zinc-900/60 rounded px-1 py-0.5 transition-colors group"
          >
            <!-- Row Base Address -->
            <span class="w-24 text-zinc-500 font-bold shrink-0">
              0x{{ (parsedBaseAddress + (rowIdx - 1) * 16).toString(16).padStart(8, '0').toUpperCase() }}
            </span>

            <!-- FORMAT: 8-BIT (16 Columns) -->
            <template v-if="viewFormat === '8bit'">
              <div class="flex-1 flex items-center gap-2 shrink-0">
                <!-- First 8 bytes -->
                <div class="grid grid-cols-8 gap-x-2 w-56 text-center">
                  <template v-for="bOffset in 8" :key="bOffset">
                    <span
                      v-if="(rowIdx - 1) * 16 + (bOffset - 1) < memoryBytes.length"
                      @click="handleByteClick((rowIdx - 1) * 16 + (bOffset - 1), $event)"
                      @dblclick="startEditChunk((rowIdx - 1) * 16 + (bOffset - 1), 1)"
                      class="cursor-pointer rounded px-0.5 transition-all text-center select-none"
                      :class="[
                        isByteSelected((rowIdx - 1) * 16 + (bOffset - 1)) ? 'bg-emerald-500 text-zinc-950 font-bold' : '',
                        changedIndices.has((rowIdx - 1) * 16 + (bOffset - 1)) ? 'bg-amber-400 text-zinc-950 font-extrabold animate-pulse' : '',
                        editingStartIndex === (rowIdx - 1) * 16 + (bOffset - 1) && editingChunkSize === 1 ? 'ring-2 ring-cyan-400' : '',
                        memoryBytes[(rowIdx - 1) * 16 + (bOffset - 1)] === 0 && !isByteSelected((rowIdx - 1) * 16 + (bOffset - 1)) ? 'text-zinc-600' : 'text-zinc-200'
                      ]"
                    >
                      <input
                        v-if="editingStartIndex === (rowIdx - 1) * 16 + (bOffset - 1) && editingChunkSize === 1"
                        v-model="editingValue"
                        @blur="commitEditChunk"
                        @keyup.enter="commitEditChunk"
                        @keyup.esc="cancelEdit"
                        maxlength="2"
                        autofocus
                        class="w-5 bg-cyan-950 text-cyan-200 text-center font-bold outline-none rounded"
                      />
                      <span v-else>
                        {{ memoryBytes[(rowIdx - 1) * 16 + (bOffset - 1)].toString(16).padStart(2, '0').toUpperCase() }}
                      </span>
                    </span>
                    <span v-else class="text-zinc-800">..</span>
                  </template>
                </div>

                <span class="text-zinc-800">|</span>

                <!-- Next 8 bytes -->
                <div class="grid grid-cols-8 gap-x-2 w-56 text-center">
                  <template v-for="bOffset in 8" :key="bOffset + 8">
                    <span
                      v-if="(rowIdx - 1) * 16 + (bOffset + 7) < memoryBytes.length"
                      @click="handleByteClick((rowIdx - 1) * 16 + (bOffset + 7), $event)"
                      @dblclick="startEditChunk((rowIdx - 1) * 16 + (bOffset + 7), 1)"
                      class="cursor-pointer rounded px-0.5 transition-all text-center select-none"
                      :class="[
                        isByteSelected((rowIdx - 1) * 16 + (bOffset + 7)) ? 'bg-emerald-500 text-zinc-950 font-bold' : '',
                        changedIndices.has((rowIdx - 1) * 16 + (bOffset + 7)) ? 'bg-amber-400 text-zinc-950 font-extrabold animate-pulse' : '',
                        editingStartIndex === (rowIdx - 1) * 16 + (bOffset + 7) && editingChunkSize === 1 ? 'ring-2 ring-cyan-400' : '',
                        memoryBytes[(rowIdx - 1) * 16 + (bOffset + 7)] === 0 && !isByteSelected((rowIdx - 1) * 16 + (bOffset + 7)) ? 'text-zinc-600' : 'text-zinc-200'
                      ]"
                    >
                      <input
                        v-if="editingStartIndex === (rowIdx - 1) * 16 + (bOffset + 7) && editingChunkSize === 1"
                        v-model="editingValue"
                        @blur="commitEditChunk"
                        @keyup.enter="commitEditChunk"
                        @keyup.esc="cancelEdit"
                        maxlength="2"
                        autofocus
                        class="w-5 bg-cyan-950 text-cyan-200 text-center font-bold outline-none rounded"
                      />
                      <span v-else>
                        {{ memoryBytes[(rowIdx - 1) * 16 + (bOffset + 7)].toString(16).padStart(2, '0').toUpperCase() }}
                      </span>
                    </span>
                    <span v-else class="text-zinc-800">..</span>
                  </template>
                </div>
              </div>
            </template>

            <!-- FORMAT: 16-BIT (8 Columns, Little Endian) -->
            <template v-else-if="viewFormat === '16bit'">
              <div class="grid grid-cols-8 gap-x-3 w-[470px] text-center shrink-0">
                <template v-for="cIdx in 8" :key="cIdx">
                  <span
                    v-if="(rowIdx - 1) * 16 + (cIdx - 1) * 2 < memoryBytes.length"
                    @click="handleChunkClick((rowIdx - 1) * 16 + (cIdx - 1) * 2, 2)"
                    @dblclick="startEditChunk((rowIdx - 1) * 16 + (cIdx - 1) * 2, 2)"
                    class="cursor-pointer rounded px-1 transition-all text-center select-none"
                    :class="[
                      isByteSelected((rowIdx - 1) * 16 + (cIdx - 1) * 2) ? 'bg-emerald-500 text-zinc-950 font-bold' : '',
                      isChunkChanged((rowIdx - 1) * 16 + (cIdx - 1) * 2, 2) ? 'bg-amber-400 text-zinc-950 font-extrabold animate-pulse' : '',
                      editingStartIndex === (rowIdx - 1) * 16 + (cIdx - 1) * 2 && editingChunkSize === 2 ? 'ring-2 ring-cyan-400' : '',
                      'text-zinc-200'
                    ]"
                  >
                    <input
                      v-if="editingStartIndex === (rowIdx - 1) * 16 + (cIdx - 1) * 2 && editingChunkSize === 2"
                      v-model="editingValue"
                      @blur="commitEditChunk"
                      @keyup.enter="commitEditChunk"
                      @keyup.esc="cancelEdit"
                      maxlength="4"
                      autofocus
                      class="w-12 bg-cyan-950 text-cyan-200 text-center font-bold outline-none rounded"
                    />
                    <span v-else>
                      {{ getChunkHex((rowIdx - 1) * 16 + (cIdx - 1) * 2, 2) }}
                    </span>
                  </span>
                  <span v-else class="text-zinc-800">....</span>
                </template>
              </div>
            </template>

            <!-- FORMAT: 32-BIT (4 Columns, Little Endian) -->
            <template v-else-if="viewFormat === '32bit'">
              <div class="grid grid-cols-4 gap-x-4 w-[470px] text-center shrink-0">
                <template v-for="cIdx in 4" :key="cIdx">
                  <span
                    v-if="(rowIdx - 1) * 16 + (cIdx - 1) * 4 < memoryBytes.length"
                    @click="handleChunkClick((rowIdx - 1) * 16 + (cIdx - 1) * 4, 4)"
                    @dblclick="startEditChunk((rowIdx - 1) * 16 + (cIdx - 1) * 4, 4)"
                    class="cursor-pointer rounded px-1.5 transition-all text-center select-none"
                    :class="[
                      isByteSelected((rowIdx - 1) * 16 + (cIdx - 1) * 4) ? 'bg-emerald-500 text-zinc-950 font-bold' : '',
                      isChunkChanged((rowIdx - 1) * 16 + (cIdx - 1) * 4, 4) ? 'bg-amber-400 text-zinc-950 font-extrabold animate-pulse' : '',
                      editingStartIndex === (rowIdx - 1) * 16 + (cIdx - 1) * 4 && editingChunkSize === 4 ? 'ring-2 ring-cyan-400' : '',
                      'text-zinc-200'
                    ]"
                  >
                    <input
                      v-if="editingStartIndex === (rowIdx - 1) * 16 + (cIdx - 1) * 4 && editingChunkSize === 4"
                      v-model="editingValue"
                      @blur="commitEditChunk"
                      @keyup.enter="commitEditChunk"
                      @keyup.esc="cancelEdit"
                      maxlength="8"
                      autofocus
                      class="w-20 bg-cyan-950 text-cyan-200 text-center font-bold outline-none rounded"
                    />
                    <span v-else>
                      {{ getChunkHex((rowIdx - 1) * 16 + (cIdx - 1) * 4, 4) }}
                    </span>
                  </span>
                  <span v-else class="text-zinc-800">........</span>
                </template>
              </div>
            </template>

            <!-- FORMAT: 64-BIT (2 Columns, Little Endian) -->
            <template v-else>
              <div class="grid grid-cols-2 gap-x-6 w-[470px] text-center shrink-0">
                <template v-for="cIdx in 2" :key="cIdx">
                  <span
                    v-if="(rowIdx - 1) * 16 + (cIdx - 1) * 8 < memoryBytes.length"
                    @click="handleChunkClick((rowIdx - 1) * 16 + (cIdx - 1) * 8, 8)"
                    @dblclick="startEditChunk((rowIdx - 1) * 16 + (cIdx - 1) * 8, 8)"
                    class="cursor-pointer rounded px-2 transition-all text-center select-none"
                    :class="[
                      isByteSelected((rowIdx - 1) * 16 + (cIdx - 1) * 8) ? 'bg-emerald-500 text-zinc-950 font-bold' : '',
                      isChunkChanged((rowIdx - 1) * 16 + (cIdx - 1) * 8, 8) ? 'bg-amber-400 text-zinc-950 font-extrabold animate-pulse' : '',
                      editingStartIndex === (rowIdx - 1) * 16 + (cIdx - 1) * 8 && editingChunkSize === 8 ? 'ring-2 ring-cyan-400' : '',
                      'text-zinc-200'
                    ]"
                  >
                    <input
                      v-if="editingStartIndex === (rowIdx - 1) * 16 + (cIdx - 1) * 8 && editingChunkSize === 8"
                      v-model="editingValue"
                      @blur="commitEditChunk"
                      @keyup.enter="commitEditChunk"
                      @keyup.esc="cancelEdit"
                      maxlength="16"
                      autofocus
                      class="w-36 bg-cyan-950 text-cyan-200 text-center font-bold outline-none rounded"
                    />
                    <span v-else>
                      {{ getChunkHex((rowIdx - 1) * 16 + (cIdx - 1) * 8, 8) }}
                    </span>
                  </span>
                  <span v-else class="text-zinc-800">................</span>
                </template>
              </div>
            </template>

            <!-- ASCII Text Representation -->
            <div class="w-40 pl-4 border-l border-zinc-800 text-zinc-400 tracking-wider flex items-center">
              <template v-for="bOffset in 16" :key="bOffset">
                <span
                  v-if="(rowIdx - 1) * 16 + (bOffset - 1) < memoryBytes.length"
                  :class="isByteSelected((rowIdx - 1) * 16 + (bOffset - 1)) ? 'text-emerald-400 font-bold underline' : ''"
                >
                  {{
                    memoryBytes[(rowIdx - 1) * 16 + (bOffset - 1)] >= 32 && memoryBytes[(rowIdx - 1) * 16 + (bOffset - 1)] <= 126
                      ? String.fromCharCode(memoryBytes[(rowIdx - 1) * 16 + (bOffset - 1)])
                      : '.'
                  }}
                </span>
              </template>
            </div>
          </div>
        </div>
      </div>

      <!-- Right Side: Data Inspector HUD -->
      <div class="w-full lg:w-80 bg-zinc-900/40 p-4 flex flex-col justify-between shrink-0 overflow-y-auto border-t lg:border-t-0 border-zinc-800">
        <div class="space-y-3.5">
          <div class="flex items-center justify-between border-b border-zinc-800 pb-2">
            <div class="flex items-center gap-1.5 text-zinc-300 font-semibold">
              <Sparkles class="w-4 h-4 text-emerald-400" />
              <span>数据解析器 (Inspector)</span>
            </div>
            <span v-if="selectedStartIndex !== null" class="text-[11px] text-zinc-500 font-mono">
              +0x{{ selectedStartIndex.toString(16).toUpperCase() }}
            </span>
          </div>

          <!-- Selected Byte Address Banner -->
          <div class="bg-zinc-950 border border-zinc-800 rounded p-2.5 space-y-1">
            <div class="text-[10px] text-zinc-500 uppercase flex items-center justify-between">
              <span>选中物理地址 (Physical Address)</span>
              <span class="text-emerald-400 font-bold font-mono">{{ selectedByteCount }} 字节</span>
            </div>
            <div class="text-emerald-400 font-bold text-xs truncate">
              {{ selectedAddressHex }}
            </div>
          </div>

          <!-- Quick Multi-Byte Select Buttons -->
          <div class="space-y-1.5">
            <div class="text-[10px] text-zinc-500 flex items-center gap-1">
              <MousePointer class="w-3 h-3" />
              <span>连续内存多选 (Shift + 点击 或 快捷跨度):</span>
            </div>
            <div class="grid grid-cols-4 gap-1">
              <button
                @click="setSelectionLength(1)"
                class="px-2 py-1 rounded text-[10px] font-mono border transition-colors"
                :class="selectedByteCount === 1 ? 'bg-emerald-600 text-white border-emerald-500 font-bold' : 'bg-zinc-950 text-zinc-400 border-zinc-800 hover:text-zinc-200'"
              >
                1B (u8)
              </button>
              <button
                @click="setSelectionLength(2)"
                class="px-2 py-1 rounded text-[10px] font-mono border transition-colors"
                :class="selectedByteCount === 2 ? 'bg-emerald-600 text-white border-emerald-500 font-bold' : 'bg-zinc-950 text-zinc-400 border-zinc-800 hover:text-zinc-200'"
              >
                2B (u16)
              </button>
              <button
                @click="setSelectionLength(4)"
                class="px-2 py-1 rounded text-[10px] font-mono border transition-colors"
                :class="selectedByteCount === 4 ? 'bg-emerald-600 text-white border-emerald-500 font-bold' : 'bg-zinc-950 text-zinc-400 border-zinc-800 hover:text-zinc-200'"
              >
                4B (u32)
              </button>
              <button
                @click="setSelectionLength(8)"
                class="px-2 py-1 rounded text-[10px] font-mono border transition-colors"
                :class="selectedByteCount === 8 ? 'bg-emerald-600 text-white border-emerald-500 font-bold' : 'bg-zinc-950 text-zinc-400 border-zinc-800 hover:text-zinc-200'"
              >
                8B (u64)
              </button>
            </div>
          </div>

          <!-- Multi-byte Selected Range Raw Values -->
          <div v-if="inspectorValues" class="bg-zinc-950/80 border border-zinc-800 rounded p-2 text-[11px] space-y-1">
            <div class="flex items-center justify-between text-zinc-500 text-[10px]">
              <span>选中字节 Hex:</span>
              <span class="text-zinc-400 font-mono">{{ inspectorValues.hexDumpStr }}</span>
            </div>
            <div class="flex items-center justify-between text-zinc-500 text-[10px]">
              <span>选中文本 ASCII:</span>
              <span class="text-cyan-300 font-bold">"{{ inspectorValues.asciiStr }}"</span>
            </div>
          </div>

          <!-- Multi-type Full 64-bit Decoding Table -->
          <div v-if="inspectorValues" class="space-y-1.5 text-[11px] font-mono">
            <!-- 64-bit Decodes -->
            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60 bg-emerald-950/20 px-1 rounded">
              <span class="text-emerald-400 font-bold">uint64 (LE):</span>
              <strong class="text-emerald-300 text-right truncate max-w-[190px]" :title="inspectorValues.u64Str">
                {{ inspectorValues.u64Str }}
              </strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60 px-1">
              <span class="text-zinc-400">uint64 Hex:</span>
              <strong class="text-zinc-300 font-bold text-[10px]">{{ inspectorValues.u64Hex }}</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60 px-1">
              <span class="text-zinc-500">int64 (LE):</span>
              <strong class="text-zinc-300 truncate max-w-[190px]" :title="inspectorValues.i64Str">{{ inspectorValues.i64Str }}</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60 px-1">
              <span class="text-zinc-500">float64 (double):</span>
              <strong class="text-amber-300">{{ inspectorValues.f64Str }}</strong>
            </div>

            <!-- 32-bit Decodes -->
            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60 px-1">
              <span class="text-zinc-500">uint32 (LE):</span>
              <strong class="text-cyan-300 font-bold">{{ inspectorValues.u32 }} (0x{{ inspectorValues.u32.toString(16).toUpperCase().padStart(8, '0') }})</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60 px-1">
              <span class="text-zinc-500">int32 (LE):</span>
              <strong class="text-zinc-200">{{ inspectorValues.i32 }}</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60 px-1">
              <span class="text-zinc-500">float32 (LE):</span>
              <strong class="text-amber-300">{{ inspectorValues.f32 }}</strong>
            </div>

            <!-- 16-bit Decodes -->
            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60 px-1">
              <span class="text-zinc-500">uint16 (LE):</span>
              <strong class="text-zinc-200">{{ inspectorValues.u16 }} (0x{{ inspectorValues.u16.toString(16).toUpperCase().padStart(4, '0') }})</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60 px-1">
              <span class="text-zinc-500">int16 (LE):</span>
              <strong class="text-zinc-200">{{ inspectorValues.i16 }}</strong>
            </div>

            <!-- 8-bit Decodes -->
            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60 px-1">
              <span class="text-zinc-500">uint8:</span>
              <strong class="text-zinc-200">{{ inspectorValues.u8 }} (0x{{ inspectorValues.u8.toString(16).toUpperCase().padStart(2, '0') }})</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60 px-1">
              <span class="text-zinc-500">int8:</span>
              <strong class="text-zinc-200">{{ inspectorValues.i8 }}</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60 px-1">
              <span class="text-zinc-500">Binary (8-bit):</span>
              <strong class="text-emerald-400 font-mono text-[10px]">{{ inspectorValues.bin8 }}</strong>
            </div>
          </div>

          <div v-else class="text-zinc-600 text-center py-6 italic text-[11px]">
            点击左侧任意数据单元以查看解码数据
          </div>
        </div>

        <!-- Hot Edit & Refresh Tips -->
        <div class="border-t border-zinc-800 pt-3 text-[10px] text-zinc-500 space-y-1 shrink-0 mt-4">
          <div>💡 <strong>提示</strong>: 双击左侧任意数值单元可直接就地修改 (热写入)</div>
          <div>⌨️ <strong>多选</strong>: 在 8-bit 下按住 Shift 点击可选择连续内存范围</div>
          <div>🔥 <strong>变动高亮</strong>: 自动刷新时数值发生变动的字节以高亮跳动显示</div>
          <div v-if="lastReadTime">🕒 上次更新: {{ lastReadTime }}</div>
        </div>
      </div>
    </div>

    <!-- Bottom Status Bar -->
    <div class="bg-zinc-900 border-t border-zinc-800 px-4 py-1 text-[10px] text-zinc-500 flex items-center justify-between">
      <span>已加载 {{ memoryBytes.length }} 字节 ({{ addressInput }} ~ 0x{{ (parsedBaseAddress + memoryBytes.length).toString(16).toUpperCase() }}) | 当前展示格式: {{ viewFormat }}</span>
      <span v-if="autoRefresh" class="text-cyan-400 font-semibold animate-pulse">● 自动刷新运行中 ({{ refreshIntervalMs }}ms)</span>
      <span v-else class="text-zinc-400">单次刷新模式</span>
    </div>

    <!-- Dump Memory Modal Dialog -->
    <div
      v-if="isDumpModalOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
    >
      <div class="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-lg shadow-2xl flex flex-col overflow-hidden">
        <div class="px-5 py-3.5 border-b border-zinc-800 flex items-center justify-between bg-zinc-950/60">
          <div class="flex items-center gap-2 text-zinc-100 font-bold text-sm">
            <Download class="w-4 h-4 text-cyan-400" />
            <span>导出 Flash / RAM 到本地 Bin 文件</span>
          </div>
          <button @click="isDumpModalOpen = false" class="text-zinc-400 hover:text-white p-1 rounded">
            <X class="w-4 h-4" />
          </button>
        </div>

        <div class="p-5 space-y-3">
          <div>
            <label class="block text-[11px] text-zinc-400 mb-1">起始内存物理地址</label>
            <input
              v-model="dumpAddress"
              type="text"
              class="w-full bg-zinc-950 border border-zinc-700 rounded px-3 py-1.5 text-zinc-200 text-xs font-mono outline-none focus:border-cyan-500"
            />
          </div>

          <div>
            <label class="block text-[11px] text-zinc-400 mb-1">转储大小 (KB)</label>
            <input
              v-model="dumpSizeKb"
              type="number"
              min="1"
              max="2048"
              class="w-full bg-zinc-950 border border-zinc-700 rounded px-3 py-1.5 text-zinc-200 text-xs font-mono outline-none focus:border-cyan-500"
            />
            <div class="text-[10px] text-zinc-500 mt-0.5">例如: 64 表示导出 65536 字节</div>
          </div>

          <div>
            <label class="block text-[11px] text-zinc-400 mb-1">本地保存路径 (.bin)</label>
            <input
              v-model="dumpFilePath"
              type="text"
              class="w-full bg-zinc-950 border border-zinc-700 rounded px-3 py-1.5 text-zinc-200 text-xs font-mono outline-none focus:border-cyan-500"
            />
          </div>

          <div v-if="dumpStatus" class="p-2.5 rounded bg-zinc-950 border border-zinc-800 text-xs font-mono">
            {{ dumpStatus }}
          </div>
        </div>

        <div class="px-5 py-3 border-t border-zinc-800 bg-zinc-950/40 flex justify-end gap-2">
          <button @click="isDumpModalOpen = false" class="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded text-xs">
            关闭
          </button>
          <button
            @click="handleExecuteDump"
            :disabled="isDumping"
            class="px-4 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50"
          >
            <RefreshCw v-if="isDumping" class="w-3.5 h-3.5 animate-spin" />
            <span>{{ isDumping ? '正在转储...' : '开始转储' }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Load File to RAM Modal Dialog -->
    <div
      v-if="isLoadModalOpen"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-4"
    >
      <div class="bg-zinc-900 border border-zinc-700 rounded-xl w-full max-w-lg shadow-2xl flex flex-col overflow-hidden">
        <div class="px-5 py-3.5 border-b border-zinc-800 flex items-center justify-between bg-zinc-950/60">
          <div class="flex items-center gap-2 text-zinc-100 font-bold text-sm">
            <Upload class="w-4 h-4 text-purple-400" />
            <span>加载本地 Bin 文件至单片机 RAM</span>
          </div>
          <button @click="isLoadModalOpen = false" class="text-zinc-400 hover:text-white p-1 rounded">
            <X class="w-4 h-4" />
          </button>
        </div>

        <div class="p-5 space-y-3">
          <div>
            <label class="block text-[11px] text-zinc-400 mb-1">目标 RAM 起始物理地址</label>
            <input
              v-model="loadAddress"
              type="text"
              class="w-full bg-zinc-950 border border-zinc-700 rounded px-3 py-1.5 text-zinc-200 text-xs font-mono outline-none focus:border-purple-500"
            />
          </div>

          <div>
            <label class="block text-[11px] text-zinc-400 mb-1">本地 Bin 文件物理绝对路径</label>
            <input
              v-model="loadFilePath"
              type="text"
              placeholder="例如: D:\Projects\firmware_test.bin"
              class="w-full bg-zinc-950 border border-zinc-700 rounded px-3 py-1.5 text-zinc-200 text-xs font-mono outline-none focus:border-purple-500"
            />
          </div>

          <div v-if="loadStatus" class="p-2.5 rounded bg-zinc-950 border border-zinc-800 text-xs font-mono">
            {{ loadStatus }}
          </div>
        </div>

        <div class="px-5 py-3 border-t border-zinc-800 bg-zinc-950/40 flex justify-end gap-2">
          <button @click="isLoadModalOpen = false" class="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded text-xs">
            关闭
          </button>
          <button
            @click="handleExecuteLoad"
            :disabled="isUploading"
            class="px-4 py-1.5 bg-purple-600 hover:bg-purple-500 text-white rounded text-xs font-semibold flex items-center gap-1.5 disabled:opacity-50"
          >
            <RefreshCw v-if="isUploading" class="w-3.5 h-3.5 animate-spin" />
            <span>{{ isUploading ? '正在写入...' : '开始载入' }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
