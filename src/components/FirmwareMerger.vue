<script setup lang="ts">
import { ref, computed } from 'vue';
import { safeInvoke } from '../utils/ipc';
import {
  Layers,
  FileCode,
  FolderOpen,
  Plus,
  Trash2,
  ArrowUp,
  ArrowDown,
  Merge,
  AlertTriangle,
  CheckCircle2,
  Copy,
  Check,
  RefreshCw,
  Zap,
  Sliders
} from '@lucide/vue';

const emit = defineEmits<{
  (e: 'switch-tab', tab: string, payload?: any): void;
}>();

export interface FirmwareFileItem {
  id: string;
  filePath: string;
  fileName: string;
  type: 'hex' | 'bin';
  fileSize: number;
  dataSize: number;
  minAddr: string;
  maxAddr: string;
  rawMinAddr: number;
  rawMaxAddr: number;
  offset: string; // Used as base load address for BIN, or rebase offset for HEX
  segments: Array<{ start: string; end: string; size: number; raw_start?: number; raw_end?: number }>;
  error?: string;
}

const activeMode = ref<'hex' | 'bin'>('hex');
const fileList = ref<FirmwareFileItem[]>([]);
const outputPath = ref<string>('');
const outputFormat = ref<'hex' | 'bin'>('hex');
const overlapStrategy = ref<'error' | 'replace' | 'ignore'>('error');
const padByteHex = ref<string>('0xFF');

const isMerging = ref<boolean>(false);
const isPickingFiles = ref<boolean>(false);
const errorMsg = ref<string>('');
const successResult = ref<any>(null);
const isCopied = ref<boolean>(false);

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

// Check for address overlapping between files
const overlapWarnings = computed(() => {
  if (fileList.value.length < 2) return [];
  const warnings: string[] = [];

  for (let i = 0; i < fileList.value.length; i++) {
    const a = fileList.value[i];
    for (let j = i + 1; j < fileList.value.length; j++) {
      const b = fileList.value[j];
      
      // Calculate effective ranges
      let aStart = a.rawMinAddr;
      let aEnd = a.rawMaxAddr;
      let bStart = b.rawMinAddr;
      let bEnd = b.rawMaxAddr;

      if (activeMode.value === 'bin') {
        const offA = parseInt(a.offset.startsWith('0x') ? a.offset : '0x' + a.offset, 16) || 0;
        const offB = parseInt(b.offset.startsWith('0x') ? b.offset : '0x' + b.offset, 16) || 0;
        aStart = offA;
        aEnd = offA + a.fileSize - 1;
        bStart = offB;
        bEnd = offB + b.fileSize - 1;
      }

      if (Math.max(aStart, bStart) <= Math.min(aEnd, bEnd)) {
        warnings.push(`[${a.fileName}] 与 [${b.fileName}] 存在物理地址重叠区间 (0x${Math.max(aStart, bStart).toString(16).toUpperCase()} ~ 0x${Math.min(aEnd, bEnd).toString(16).toUpperCase()})`);
      }
    }
  }
  return warnings;
});

function switchMode(mode: 'hex' | 'bin') {
  activeMode.value = mode;
  outputFormat.value = mode;
  fileList.value = [];
  outputPath.value = '';
  successResult.value = null;
  errorMsg.value = '';
}

async function addFiles() {
  isPickingFiles.value = true;
  errorMsg.value = '';
  try {
    const paths: string[] = await safeInvoke('pick_multiple_firmware_files', {
      title: activeMode.value === 'hex' ? '选择多个 Intel HEX 固件文件 (*.hex)' : '选择多个原始 BIN 固件文件 (*.bin)',
      filterType: activeMode.value
    });

    if (!paths || paths.length === 0) return;

    for (const p of paths) {
      if (fileList.value.some(f => f.filePath === p)) continue;
      await inspectAndAddFile(p);
    }
  } catch (err: any) {
    errorMsg.value = `添加文件异常: ${err}`;
  } finally {
    isPickingFiles.value = false;
  }
}

async function inspectAndAddFile(path: string) {
  try {
    const defaultOffset = activeMode.value === 'bin' 
      ? (fileList.value.length === 0 ? '0x02000000' : '0x02004000') 
      : '0x00000000';

    const info: any = await safeInvoke('inspect_firmware_file', {
      filePath: path,
      fileType: activeMode.value,
      offset: parseInt(defaultOffset, 16)
    });

    fileList.value.push({
      id: Math.random().toString(36).substring(2, 9),
      filePath: path,
      fileName: info.file_name || path.split(/[\\/]/).pop() || 'firmware',
      type: info.type || activeMode.value,
      fileSize: info.file_size || 0,
      dataSize: info.data_size || 0,
      minAddr: info.min_addr || '0x00000000',
      maxAddr: info.max_addr || '0x00000000',
      rawMinAddr: info.raw_min_addr || 0,
      rawMaxAddr: info.raw_max_addr || 0,
      offset: defaultOffset,
      segments: info.segments || []
    });
  } catch (err: any) {
    errorMsg.value = `解析文件 [${path}] 失败: ${err}`;
  }
}

function removeFile(index: number) {
  fileList.value.splice(index, 1);
  if (fileList.value.length === 0) {
    successResult.value = null;
  }
}

function moveUp(index: number) {
  if (index <= 0) return;
  const item = fileList.value.splice(index, 1)[0];
  fileList.value.splice(index - 1, 0, item);
}

function moveDown(index: number) {
  if (index >= fileList.value.length - 1) return;
  const item = fileList.value.splice(index, 1)[0];
  fileList.value.splice(index + 1, 0, item);
}

function clearAllFiles() {
  fileList.value = [];
  outputPath.value = '';
  successResult.value = null;
  errorMsg.value = '';
}

async function selectOutputPath() {
  try {
    const ext = outputFormat.value === 'bin' ? 'bin' : 'hex';
    const defaultName = `merged_${activeMode.value}_firmware.${ext}`;
    const selected: string | null = await safeInvoke('pick_save_firmware_file', {
      title: '指定合并后输出文件的保存路径',
      defaultName,
      fileType: ext
    });
    if (selected) {
      outputPath.value = selected;
    }
  } catch (err: any) {
    errorMsg.value = `选择保存路径失败: ${err}`;
  }
}

async function executeMerge() {
  if (fileList.value.length === 0) {
    errorMsg.value = '请至少添加一个固件文件进行合并';
    return;
  }
  if (!outputPath.value) {
    await selectOutputPath();
    if (!outputPath.value) {
      errorMsg.value = '请指定合并文件的输出保存路径';
      return;
    }
  }

  isMerging.value = true;
  errorMsg.value = '';
  successResult.value = null;

  try {
    const pad = parseInt(padByteHex.value.startsWith('0x') ? padByteHex.value : '0x' + padByteHex.value, 16) || 255;

    if (activeMode.value === 'hex') {
      const payloadFiles = fileList.value.map(f => ({
        file_path: f.filePath,
        offset: f.offset || '0x00000000'
      }));

      const res: any = await safeInvoke('merge_hex_files', {
        files: payloadFiles,
        outputPath: outputPath.value,
        outputFormat: outputFormat.value,
        overlapStrategy: overlapStrategy.value,
        padByte: pad
      });
      successResult.value = res;
    } else {
      // BIN mode
      const payloadFiles = fileList.value.map(f => ({
        file_path: f.filePath,
        offset: f.offset || '0x00000000'
      }));

      const res: any = await safeInvoke('merge_bin_files', {
        files: payloadFiles,
        outputPath: outputPath.value,
        outputFormat: outputFormat.value,
        padByte: pad,
        overlapStrategy: overlapStrategy.value
      });
      successResult.value = res;
    }
  } catch (err: any) {
    errorMsg.value = `合并固件执行失败: ${err}`;
  } finally {
    isMerging.value = false;
  }
}

function copyResultSummary() {
  if (!successResult.value) return;
  const text = JSON.stringify(successResult.value, null, 2);
  navigator.clipboard.writeText(text);
  isCopied.value = true;
  setTimeout(() => (isCopied.value = false), 2000);
}

function flashMergedFirmware() {
  if (!outputPath.value) return;
  emit('switch-tab', 'flasher', { filePath: outputPath.value });
}
</script>

<template>
  <div class="h-full flex flex-col p-4 bg-zinc-950 text-zinc-100 text-xs overflow-y-auto space-y-4">
    <!-- Top Header & Mode Toggle -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-4 flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
      <div class="flex items-center gap-3">
        <div class="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400">
          <Merge class="w-5 h-5" />
        </div>
        <div>
          <h2 class="text-sm font-bold text-zinc-100 flex items-center gap-2">
            <span>HEX / BIN 固件多段地址合并器</span>
            <span class="px-2 py-0.5 text-[10px] font-mono rounded bg-emerald-950/80 text-emerald-300 border border-emerald-800">
              IntelHex 引擎
            </span>
          </h2>
          <p class="text-[11px] text-zinc-400 mt-0.5">
            支持将多个独立 HEX 文件、或指定起始基地址的多个 BIN 文件缝合为一个单一固件，自带重叠冲突检测与空隙 Padding
          </p>
        </div>
      </div>

      <!-- Mode Switcher Tabs -->
      <div class="flex items-center bg-zinc-950 p-1 rounded-lg border border-zinc-800">
        <button
          @click="switchMode('hex')"
          class="px-4 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5"
          :class="activeMode === 'hex' ? 'bg-emerald-600 text-white shadow' : 'text-zinc-400 hover:text-zinc-200'"
        >
          <FileCode class="w-3.5 h-3.5" />
          <span>多个 HEX 合并 (.hex)</span>
        </button>
        <button
          @click="switchMode('bin')"
          class="px-4 py-1.5 rounded-md text-xs font-medium transition-colors flex items-center gap-1.5"
          :class="activeMode === 'bin' ? 'bg-cyan-600 text-white shadow' : 'text-zinc-400 hover:text-zinc-200'"
        >
          <Layers class="w-3.5 h-3.5" />
          <span>多个 BIN 合并 (.bin)</span>
        </button>
      </div>
    </div>

    <!-- Alert / Notice Box -->
    <div v-if="overlapWarnings.length > 0" class="bg-amber-950/40 border border-amber-800/80 rounded-lg p-3 text-amber-300 flex items-start gap-2.5">
      <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5 text-amber-400" />
      <div class="space-y-1">
        <div class="font-semibold text-xs text-amber-200">检测到固件区间地址可能存在重叠冲突：</div>
        <ul class="list-disc list-inside text-[11px] text-amber-300/90 space-y-0.5 font-mono">
          <li v-for="(warn, i) in overlapWarnings" :key="i">{{ warn }}</li>
        </ul>
        <div class="text-[10px] text-amber-400/80 mt-1">
          提示：若此重叠非预期，请调整下方的地址偏移配置，或在右侧参数将冲突策略设置为“报错中断”。
        </div>
      </div>
    </div>

    <!-- Error Banner -->
    <div v-if="errorMsg" class="bg-rose-950/60 border border-rose-800 rounded-lg p-3 text-rose-300 flex items-center gap-2">
      <AlertTriangle class="w-4 h-4 text-rose-400 shrink-0" />
      <span class="flex-1 font-mono">{{ errorMsg }}</span>
      <button @click="errorMsg = ''" class="text-rose-400 hover:text-rose-200 text-xs">✕</button>
    </div>

    <!-- Main Workspace 2-Column Layout -->
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <!-- Left 2 Cols: File Queue & Address Map -->
      <div class="lg:col-span-2 space-y-3">
        <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3.5 space-y-3">
          <div class="flex items-center justify-between border-b border-zinc-800 pb-2.5">
            <div class="flex items-center gap-2 font-semibold text-zinc-200">
              <Layers class="w-4 h-4 text-emerald-400" />
              <span>待合并固件文件序列 (共 {{ fileList.length }} 个)</span>
            </div>
            <div class="flex items-center gap-2">
              <button
                @click="addFiles"
                :disabled="isPickingFiles"
                class="flex items-center gap-1.5 px-3 py-1.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-medium transition-colors"
              >
                <Plus class="w-3.5 h-3.5" />
                <span>添加固件文件</span>
              </button>
              <button
                v-if="fileList.length > 0"
                @click="clearAllFiles"
                class="px-2.5 py-1.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 transition-colors"
                title="清空当前列表"
              >
                <Trash2 class="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          <!-- Empty State -->
          <div
            v-if="fileList.length === 0"
            @click="addFiles"
            class="border-2 border-dashed border-zinc-800 hover:border-zinc-700 rounded-lg p-8 flex flex-col items-center justify-center gap-2.5 cursor-pointer text-zinc-500 hover:text-zinc-400 transition-all"
          >
            <FolderOpen class="w-8 h-8 stroke-1 text-zinc-600" />
            <div class="font-medium text-xs">点击添加或选择要合并的 {{ activeMode.toUpperCase() }} 固件文件</div>
            <div class="text-[11px] text-zinc-600">
              {{ activeMode === 'hex' ? '支持如 Bootloader.hex + App.hex + Config.hex 拼接' : '支持为每个 BIN 指定物理装载起始地址 (如 0x02000000)' }}
            </div>
          </div>

          <!-- File List Items -->
          <div v-else class="space-y-2.5">
            <div
              v-for="(item, idx) in fileList"
              :key="item.id"
              class="bg-zinc-950/70 border border-zinc-800/80 rounded-lg p-3 hover:border-zinc-700/80 transition-all flex flex-col gap-2"
            >
              <div class="flex items-center justify-between gap-3">
                <div class="flex items-center gap-2 min-w-0">
                  <span class="w-5 h-5 rounded-full bg-zinc-800 text-zinc-300 flex items-center justify-center font-mono text-[11px] font-bold shrink-0">
                    {{ idx + 1 }}
                  </span>
                  <div class="min-w-0">
                    <div class="font-semibold text-zinc-200 truncate flex items-center gap-2">
                      <span class="truncate">{{ item.fileName }}</span>
                      <span class="px-1.5 py-0.2 rounded text-[10px] uppercase font-mono bg-zinc-800 text-zinc-400">
                        {{ item.type }}
                      </span>
                      <span class="text-zinc-500 font-normal text-[11px]">
                        {{ formatBytes(item.fileSize) }}
                      </span>
                    </div>
                    <div class="text-[10px] text-zinc-500 font-mono truncate" :title="item.filePath">
                      {{ item.filePath }}
                    </div>
                  </div>
                </div>

                <!-- Reorder & Delete -->
                <div class="flex items-center gap-1 shrink-0">
                  <button
                    @click="moveUp(idx)"
                    :disabled="idx === 0"
                    class="p-1 rounded hover:bg-zinc-800 text-zinc-400 disabled:opacity-30 disabled:hover:bg-transparent"
                    title="上移"
                  >
                    <ArrowUp class="w-3.5 h-3.5" />
                  </button>
                  <button
                    @click="moveDown(idx)"
                    :disabled="idx === fileList.length - 1"
                    class="p-1 rounded hover:bg-zinc-800 text-zinc-400 disabled:opacity-30 disabled:hover:bg-transparent"
                    title="下移"
                  >
                    <ArrowDown class="w-3.5 h-3.5" />
                  </button>
                  <button
                    @click="removeFile(idx)"
                    class="p-1 rounded hover:bg-rose-950/50 hover:text-rose-400 text-zinc-500 ml-1"
                    title="移除"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              <!-- Address Configuration & Segments Breakdown -->
              <div class="bg-zinc-900/60 rounded p-2 flex flex-wrap items-center justify-between gap-3 text-[11px]">
                <div class="flex items-center gap-2">
                  <span class="text-zinc-400 font-medium">
                    {{ activeMode === 'bin' ? '装载物理起始地址 (Offset):' : '重定位偏移 (可选):' }}
                  </span>
                  <input
                    v-model="item.offset"
                    type="text"
                    placeholder="0x00000000"
                    class="w-32 bg-zinc-950 border border-zinc-800 rounded px-2 py-0.5 text-zinc-200 font-mono outline-none focus:border-emerald-500 text-center"
                  />
                </div>

                <div class="flex items-center gap-3 font-mono text-zinc-400">
                  <span v-if="activeMode === 'hex'">
                    原始区间: <strong class="text-emerald-400">{{ item.minAddr }}</strong> ~ <strong class="text-emerald-400">{{ item.maxAddr }}</strong>
                  </span>
                  <span v-else>
                    跨度: <strong class="text-cyan-400">{{ item.offset }}</strong> ~ <strong class="text-cyan-400">0x{{ ((parseInt(item.offset, 16) || 0) + item.fileSize - 1).toString(16).toUpperCase().padStart(8, '0') }}</strong>
                  </span>
                  <span>分段数: {{ item.segments.length }}</span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Right 1 Col: Output & Strategy Configuration -->
      <div class="space-y-4">
        <!-- Configuration Card -->
        <div class="bg-zinc-900 border border-zinc-800 rounded-lg p-3.5 space-y-3.5">
          <div class="flex items-center gap-2 font-semibold text-zinc-200 border-b border-zinc-800 pb-2">
            <Sliders class="w-4 h-4 text-emerald-400" />
            <span>合并输出设置</span>
          </div>

          <!-- Target Output Format -->
          <div>
            <label class="block text-zinc-400 mb-1 text-[11px] font-medium">合并后保存目标格式</label>
            <div class="grid grid-cols-2 gap-2">
              <button
                @click="outputFormat = 'hex'"
                class="px-3 py-1.5 rounded border text-center font-mono font-medium transition-colors"
                :class="outputFormat === 'hex' ? 'bg-emerald-950/80 border-emerald-500 text-emerald-300' : 'bg-zinc-950 border-zinc-800 text-zinc-400 hover:text-zinc-200'"
              >
                Intel HEX (*.hex)
              </button>
              <button
                @click="outputFormat = 'bin'"
                class="px-3 py-1.5 rounded border text-center font-mono font-medium transition-colors"
                :class="outputFormat === 'bin' ? 'bg-cyan-950/80 border-cyan-500 text-cyan-300' : 'bg-zinc-950 border-zinc-800 text-zinc-400 hover:text-zinc-200'"
              >
                Raw Binary (*.bin)
              </button>
            </div>
          </div>

          <!-- Overlap Strategy -->
          <div>
            <label class="block text-zinc-400 mb-1 text-[11px] font-medium">地址区间重叠冲突策略 (Overlap)</label>
            <select
              v-model="overlapStrategy"
              class="w-full bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 outline-none focus:border-emerald-500 font-sans"
            >
              <option value="error">严格报错中断 (推荐，防止固件意外相互覆盖)</option>
              <option value="replace">后来居上 (新文件覆盖冲突区域)</option>
              <option value="ignore">先入为主 (保留先添加文件的重叠数据)</option>
            </select>
          </div>

          <!-- Padding byte for BIN export -->
          <div>
            <label class="block text-zinc-400 mb-1 text-[11px] font-medium">
              空隙填充字节 (Padding Byte)
              <span class="text-zinc-500 font-normal">通常为 Flash 擦除默认值 0xFF</span>
            </label>
            <input
              v-model="padByteHex"
              type="text"
              placeholder="0xFF"
              class="w-full bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 font-mono outline-none focus:border-emerald-500"
            />
          </div>

          <!-- Output File Path -->
          <div>
            <label class="block text-zinc-400 mb-1 text-[11px] font-medium">合并后保存路径</label>
            <div class="flex gap-2">
              <input
                v-model="outputPath"
                type="text"
                placeholder="点击右侧按钮选择保存位置"
                class="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 font-mono outline-none focus:border-emerald-500 text-[11px] truncate"
              />
              <button
                @click="selectOutputPath"
                class="px-2.5 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded shrink-0 transition-colors"
                title="浏览选择保存文件"
              >
                <FolderOpen class="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          <!-- Merge Execution Action Button -->
          <div class="pt-2">
            <button
              @click="executeMerge"
              :disabled="isMerging || fileList.length === 0"
              class="w-full py-2.5 rounded bg-emerald-600 hover:bg-emerald-500 text-white font-semibold flex items-center justify-center gap-2 shadow-lg shadow-emerald-950/50 transition-all disabled:opacity-40 disabled:hover:bg-emerald-600"
            >
              <RefreshCw v-if="isMerging" class="w-4 h-4 animate-spin" />
              <Merge v-else class="w-4 h-4" />
              <span>{{ isMerging ? '正在缝合处理固件数据...' : `立即执行合并 (${fileList.length} 个固件)` }}</span>
            </button>
          </div>
        </div>

        <!-- Success Result Card -->
        <div v-if="successResult" class="bg-zinc-900 border border-emerald-800/80 rounded-lg p-3.5 space-y-3">
          <div class="flex items-center justify-between text-emerald-400 font-semibold border-b border-zinc-800 pb-2">
            <div class="flex items-center gap-1.5">
              <CheckCircle2 class="w-4 h-4" />
              <span>合并成功！</span>
            </div>
            <div class="flex items-center gap-1.5">
              <button
                @click="copyResultSummary"
                class="p-1 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors"
                title="复制摘要"
              >
                <Check v-if="isCopied" class="w-3.5 h-3.5 text-emerald-400" />
                <Copy v-else class="w-3.5 h-3.5" />
              </button>
            </div>
          </div>

          <div class="space-y-1.5 text-[11px] font-mono">
            <div class="flex justify-between text-zinc-400">
              <span>最终格式:</span>
              <strong class="text-zinc-200 uppercase">{{ successResult.output_format }}</strong>
            </div>
            <div class="flex justify-between text-zinc-400">
              <span>文件总大小:</span>
              <strong class="text-zinc-200">{{ formatBytes(successResult.file_size) }}</strong>
            </div>
            <div class="flex justify-between text-zinc-400">
              <span>有效数据跨度:</span>
              <span class="text-emerald-400">{{ successResult.min_addr }} ~ {{ successResult.max_addr }}</span>
            </div>
            <div class="flex justify-between text-zinc-400">
              <span>分段数量:</span>
              <span class="text-zinc-200">{{ successResult.segments?.length || 1 }} 块物理段</span>
            </div>
            <div class="pt-1 text-[10px] text-zinc-500 break-all">
              保存至: {{ successResult.output_path }}
            </div>
          </div>

          <!-- Quick Jump to SWD Flasher -->
          <div class="pt-2 border-t border-zinc-800">
            <button
              @click="flashMergedFirmware"
              class="w-full py-1.5 rounded bg-emerald-900/60 hover:bg-emerald-800/80 text-emerald-300 border border-emerald-700/60 font-medium flex items-center justify-center gap-1.5 transition-colors"
            >
              <Zap class="w-3.5 h-3.5 text-emerald-400" />
              <span>载入此固件至 SWD 烧录器</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
