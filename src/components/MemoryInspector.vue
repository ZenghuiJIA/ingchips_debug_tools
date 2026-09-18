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
  Sparkles
} from '@lucide/vue';

defineProps<{
  isConnected: boolean;
}>();

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

const selectedIndex = ref<number | null>(null);
const editingIndex = ref<number | null>(null);
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

// --- Read Memory ---
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

// --- Byte Inline Edit ---
function startEditByte(index: number) {
  editingIndex.value = index;
  editingValue.value = (memoryBytes.value[index] || 0).toString(16).padStart(2, '0').toUpperCase();
}

function cancelEdit() {
  editingIndex.value = null;
  editingValue.value = '';
}

async function commitEditByte() {
  if (editingIndex.value === null) return;
  const idx = editingIndex.value;
  const rawHex = editingValue.value.trim();
  const val = parseInt(rawHex, 16);

  if (isNaN(val) || val < 0 || val > 255) {
    alert('请输入有效的单字节十六进制数值 (00 ~ FF)');
    return;
  }

  const byteAddr = parsedBaseAddress.value + idx;
  const byteAddrHex = `0x${byteAddr.toString(16).toUpperCase()}`;

  isWritingByte.value = true;
  try {
    await safeInvoke('pyocd_write_memory_byte', {
      address: byteAddrHex,
      value: val,
      probeId: null,
      targetOverride: null,
    });
    memoryBytes.value[idx] = val;
    previousBytes.value[idx] = val;
    editingIndex.value = null;
  } catch (err: any) {
    alert(`写入内存失败: ${err}`);
  } finally {
    isWritingByte.value = false;
  }
}

// --- Data Inspector Computations for Selected Byte ---
const selectedAddressHex = computed<string>(() => {
  if (selectedIndex.value === null) return '--';
  return `0x${(parsedBaseAddress.value + selectedIndex.value).toString(16).padStart(8, '0').toUpperCase()}`;
});

const inspectorValues = computed(() => {
  if (selectedIndex.value === null || selectedIndex.value >= memoryBytes.value.length) {
    return null;
  }
  const idx = selectedIndex.value;
  const b0 = memoryBytes.value[idx] ?? 0;
  const b1 = memoryBytes.value[idx + 1] ?? 0;
  const b2 = memoryBytes.value[idx + 2] ?? 0;
  const b3 = memoryBytes.value[idx + 3] ?? 0;

  // uint8 & int8
  const u8 = b0;
  const i8 = (b0 & 0x80) ? b0 - 0x100 : b0;

  // uint16 & int16 (Little Endian)
  const u16 = (b1 << 8) | b0;
  const i16 = (u16 & 0x8000) ? u16 - 0x10000 : u16;

  // uint32 & int32 (Little Endian)
  const u32 = ((b3 << 24) | (b2 << 16) | (b1 << 8) | b0) >>> 0;
  const i32 = (b3 << 24) | (b2 << 16) | (b1 << 8) | b0;

  // float32
  const buf = new ArrayBuffer(4);
  const view = new DataView(buf);
  view.setUint8(0, b0);
  view.setUint8(1, b1);
  view.setUint8(2, b2);
  view.setUint8(3, b3);
  const f32 = view.getFloat32(0, true);

  return {
    u8,
    i8,
    u16,
    i16,
    u32,
    i32,
    f32: isNaN(f32) ? 'NaN' : f32.toExponential(4),
    bin8: b0.toString(2).padStart(8, '0'),
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
    const hexParts = chunk.map(b => b.toString(16).padStart(2, '0').toUpperCase());
    while (hexParts.length < 16) hexParts.push('  ');
    const hexGroup1 = hexParts.slice(0, 8).join(' ');
    const hexGroup2 = hexParts.slice(8, 16).join(' ');

    const ascii = chunk.map(b => (b >= 32 && b <= 126 ? String.fromCharCode(b) : '.')).join('');
    lines.push(`${rowAddr}:  ${hexGroup1}  ${hexGroup2}  |${ascii}|`);
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

// --- Lifecycle ---
onMounted(() => {
  handleReadMemory();
});

onUnmounted(() => {
  if (autoRefreshTimer) clearInterval(autoRefreshTimer);
  if (diffFadeTimer) clearTimeout(diffFadeTimer);
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-mono text-xs overflow-hidden select-text">
    <!-- Top Control Bar -->
    <div class="bg-zinc-900 border-b border-zinc-800 px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 shrink-0">
      <!-- Address & Quick Select -->
      <div class="flex items-center gap-2">
        <div class="flex items-center gap-1.5 text-zinc-200 font-semibold mr-1">
          <Database class="w-4 h-4 text-emerald-400" />
          <span>内存查看与Dump</span>
        </div>

        <div class="h-4 w-px bg-zinc-800"></div>

        <!-- Address input -->
        <div class="flex items-center gap-1">
          <span class="text-zinc-400 text-[11px]">基址:</span>
          <input
            v-model="addressInput"
            @keyup.enter="handleReadMemory"
            type="text"
            placeholder="0x20000000"
            class="w-32 bg-zinc-950 border border-zinc-700 focus:border-emerald-500 rounded px-2 py-1 text-zinc-200 text-xs font-mono outline-none"
          />
        </div>

        <!-- Length selector -->
        <div class="flex items-center gap-1">
          <span class="text-zinc-400 text-[11px]">长度:</span>
          <select
            v-model="byteCount"
            @change="handleReadMemory"
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

        <!-- Auto Refresh Toggle -->
        <button
          @click="toggleAutoRefresh"
          class="flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-medium border transition-colors shadow-sm"
          :class="autoRefresh
            ? 'bg-cyan-950 text-cyan-300 border-cyan-700 animate-pulse'
            : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
        >
          <component :is="autoRefresh ? Pause : Play" class="w-3.5 h-3.5" />
          <span>{{ autoRefresh ? '自动刷新中' : '自动刷新' }}</span>
        </button>

        <!-- Interval Dropdown when auto refreshing -->
        <select
          v-if="autoRefresh"
          v-model="refreshIntervalMs"
          class="bg-zinc-950 border border-cyan-800 rounded px-1.5 py-1 text-cyan-300 text-xs focus:outline-none"
        >
          <option :value="200">200ms</option>
          <option :value="500">500ms</option>
          <option :value="1000">1000ms</option>
          <option :value="2000">2000ms</option>
        </select>
      </div>

      <!-- Right Actions: Quick Jump & Bin Export -->
      <div class="flex items-center gap-2">
        <!-- Quick Jumps -->
        <div class="hidden xl:flex items-center gap-1 text-[10px]">
          <span class="text-zinc-500">快捷:</span>
          <button
            v-for="q in QUICK_TARGETS"
            :key="q.addr"
            @click="setQuickAddress(q.addr)"
            class="px-1.5 py-0.5 rounded bg-zinc-800/80 hover:bg-zinc-700 text-zinc-300 border border-zinc-700/60 transition-colors"
          >
            {{ q.label }}
          </button>
        </div>

        <div class="h-4 w-px bg-zinc-800 hidden xl:block"></div>

        <!-- Copy View -->
        <button
          @click="copyFormattedHex"
          class="px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 rounded text-xs flex items-center gap-1 transition-colors"
          title="复制当前内存十六进制视图到剪贴板"
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

    <!-- Main Content Split Area: Left Hex Grid, Right/Bottom Data Inspector -->
    <div class="flex-1 flex flex-col lg:flex-row overflow-hidden">
      <!-- Hex Editor Grid -->
      <div class="flex-1 flex flex-col overflow-hidden border-r border-zinc-800">
        <!-- Hex Table Header -->
        <div class="bg-zinc-900/90 border-b border-zinc-800 px-4 py-1.5 text-[11px] text-zinc-400 font-mono flex items-center select-none shrink-0">
          <span class="w-24 text-zinc-500">偏移地址</span>
          <div class="flex-1 flex items-center gap-2">
            <div class="grid grid-cols-8 gap-x-2 w-56 text-center text-zinc-500">
              <span>00</span><span>01</span><span>02</span><span>03</span>
              <span>04</span><span>05</span><span>06</span><span>07</span>
            </div>
            <span class="text-zinc-700">|</span>
            <div class="grid grid-cols-8 gap-x-2 w-56 text-center text-zinc-500">
              <span>08</span><span>09</span><span>0A</span><span>0B</span>
              <span>0C</span><span>0D</span><span>0E</span><span>0F</span>
            </div>
          </div>
          <span class="w-40 text-left text-zinc-500 pl-4 border-l border-zinc-800">ASCII 文本</span>
        </div>

        <!-- Hex Rows Scroll Area -->
        <div class="flex-1 overflow-y-auto p-4 space-y-1 font-mono text-xs">
          <div v-if="memoryBytes.length === 0" class="h-full flex items-center justify-center text-zinc-600">
            暂无内存数据，请连接调试器后点击「读取」
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

            <!-- 16 Bytes -->
            <div class="flex-1 flex items-center gap-2 shrink-0">
              <!-- First 8 bytes -->
              <div class="grid grid-cols-8 gap-x-2 w-56 text-center">
                <template v-for="bOffset in 8" :key="bOffset">
                  <span
                    v-if="(rowIdx - 1) * 16 + (bOffset - 1) < memoryBytes.length"
                    @click="selectedIndex = (rowIdx - 1) * 16 + (bOffset - 1)"
                    @dblclick="startEditByte((rowIdx - 1) * 16 + (bOffset - 1))"
                    class="cursor-pointer rounded px-0.5 transition-all text-center"
                    :class="[
                      selectedIndex === (rowIdx - 1) * 16 + (bOffset - 1) ? 'bg-emerald-500 text-zinc-950 font-bold' : '',
                      changedIndices.has((rowIdx - 1) * 16 + (bOffset - 1)) ? 'bg-amber-400 text-zinc-950 font-extrabold animate-pulse' : '',
                      editingIndex === (rowIdx - 1) * 16 + (bOffset - 1) ? 'ring-2 ring-cyan-400' : '',
                      memoryBytes[(rowIdx - 1) * 16 + (bOffset - 1)] === 0 ? 'text-zinc-600' : 'text-zinc-200'
                    ]"
                  >
                    <!-- Inline editing input -->
                    <input
                      v-if="editingIndex === (rowIdx - 1) * 16 + (bOffset - 1)"
                      v-model="editingValue"
                      @blur="commitEditByte"
                      @keyup.enter="commitEditByte"
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
                    @click="selectedIndex = (rowIdx - 1) * 16 + (bOffset + 7)"
                    @dblclick="startEditByte((rowIdx - 1) * 16 + (bOffset + 7))"
                    class="cursor-pointer rounded px-0.5 transition-all text-center"
                    :class="[
                      selectedIndex === (rowIdx - 1) * 16 + (bOffset + 7) ? 'bg-emerald-500 text-zinc-950 font-bold' : '',
                      changedIndices.has((rowIdx - 1) * 16 + (bOffset + 7)) ? 'bg-amber-400 text-zinc-950 font-extrabold animate-pulse' : '',
                      editingIndex === (rowIdx - 1) * 16 + (bOffset + 7) ? 'ring-2 ring-cyan-400' : '',
                      memoryBytes[(rowIdx - 1) * 16 + (bOffset + 7)] === 0 ? 'text-zinc-600' : 'text-zinc-200'
                    ]"
                  >
                    <input
                      v-if="editingIndex === (rowIdx - 1) * 16 + (bOffset + 7)"
                      v-model="editingValue"
                      @blur="commitEditByte"
                      @keyup.enter="commitEditByte"
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

            <!-- ASCII Text Representation -->
            <div class="w-40 pl-4 border-l border-zinc-800 text-zinc-400 tracking-wider flex items-center">
              <template v-for="bOffset in 16" :key="bOffset">
                <span
                  v-if="(rowIdx - 1) * 16 + (bOffset - 1) < memoryBytes.length"
                  :class="selectedIndex === (rowIdx - 1) * 16 + (bOffset - 1) ? 'text-emerald-400 font-bold underline' : ''"
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
      <div class="w-full lg:w-72 bg-zinc-900/40 p-4 flex flex-col justify-between shrink-0">
        <div class="space-y-4">
          <div class="flex items-center justify-between border-b border-zinc-800 pb-2">
            <div class="flex items-center gap-1.5 text-zinc-300 font-semibold">
              <Sparkles class="w-4 h-4 text-emerald-400" />
              <span>数据解析器 (Inspector)</span>
            </div>
            <span v-if="selectedIndex !== null" class="text-[11px] text-zinc-500">
              偏移 +0x{{ selectedIndex.toString(16).toUpperCase() }}
            </span>
          </div>

          <!-- Selected Byte Address -->
          <div class="bg-zinc-950 border border-zinc-800 rounded p-2.5">
            <div class="text-[10px] text-zinc-500 uppercase">选中地址 (Physical Address)</div>
            <div class="text-emerald-400 font-bold text-sm mt-0.5">
              {{ selectedAddressHex }}
            </div>
          </div>

          <!-- Multi-type Decoding Table -->
          <div v-if="inspectorValues" class="space-y-2 text-[11px]">
            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60">
              <span class="text-zinc-500">uint8:</span>
              <strong class="text-zinc-200">{{ inspectorValues.u8 }} (0x{{ inspectorValues.u8.toString(16).toUpperCase().padStart(2, '0') }})</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60">
              <span class="text-zinc-500">int8:</span>
              <strong class="text-zinc-200">{{ inspectorValues.i8 }}</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60">
              <span class="text-zinc-500">uint16 (LE):</span>
              <strong class="text-zinc-200">{{ inspectorValues.u16 }} (0x{{ inspectorValues.u16.toString(16).toUpperCase().padStart(4, '0') }})</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60">
              <span class="text-zinc-500">int16 (LE):</span>
              <strong class="text-zinc-200">{{ inspectorValues.i16 }}</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60">
              <span class="text-zinc-500">uint32 (LE):</span>
              <strong class="text-cyan-300 font-bold">{{ inspectorValues.u32 }} (0x{{ inspectorValues.u32.toString(16).toUpperCase().padStart(8, '0') }})</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60">
              <span class="text-zinc-500">int32 (LE):</span>
              <strong class="text-zinc-200">{{ inspectorValues.i32 }}</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60">
              <span class="text-zinc-500">float32 (LE):</span>
              <strong class="text-amber-300">{{ inspectorValues.f32 }}</strong>
            </div>

            <div class="flex items-center justify-between py-1 border-b border-zinc-800/60">
              <span class="text-zinc-500">Binary (8-bit):</span>
              <strong class="text-emerald-400 font-mono text-[10px]">{{ inspectorValues.bin8 }}</strong>
            </div>
          </div>

          <div v-else class="text-zinc-600 text-center py-6 italic text-[11px]">
            点击左侧任意字节以查看解码数据
          </div>
        </div>

        <!-- Hot Edit & Refresh Tips -->
        <div class="border-t border-zinc-800 pt-3 text-[10px] text-zinc-500 space-y-1">
          <div>💡 <strong>提示</strong>: 双击左侧任意字节可直接就地修改 (热写入)</div>
          <div>🔥 <strong>变动高亮</strong>: 自动刷新时数值发生变动的字节以高亮琥珀色跳动显示</div>
          <div v-if="lastReadTime">🕒 上次更新: {{ lastReadTime }}</div>
        </div>
      </div>
    </div>

    <!-- Bottom Status Bar -->
    <div class="bg-zinc-900 border-t border-zinc-800 px-4 py-1 text-[10px] text-zinc-500 flex items-center justify-between">
      <span>已加载 {{ memoryBytes.length }} 字节 ({{ addressInput }} ~ 0x{{ (parsedBaseAddress + memoryBytes.length).toString(16).toUpperCase() }})</span>
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
