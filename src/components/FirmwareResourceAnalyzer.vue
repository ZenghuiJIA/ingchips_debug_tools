<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { safeInvoke } from '../utils/ipc';
import type {
  FirmwareResourceAnalysis,
  FirmwareModule,
  LinearMemoryBlock
} from '../types';
import {
  PieChart,
  HardDrive,
  Cpu,
  FileCode,
  Search,
  Download,
  Copy,
  Check,
  ChevronRight,
  ChevronDown,
  RefreshCw,
  Layers,
  ArrowUpDown,
  FolderOpen,
  LayoutGrid,
  BarChart3,
  ShieldAlert,
  Sparkles,
  Box,
  Info,
  CheckCircle2,
  AlertTriangle,
  Maximize2,
  Minimize2
} from 'lucide-vue-next';

const props = defineProps<{
  initialFilePath?: string;
}>();

const emit = defineEmits<{
  (e: 'switch-tab', tab: string): void;
}>();

// File & Chip configuration
const filePath = ref<string>(props.initialFilePath || '');
const isAnalyzing = ref<boolean>(false);
const errorMsg = ref<string>('');
const isCopied = ref<boolean>(false);

// Chip Memory Presets (INGChips series prioritized at top)
interface ChipPreset {
  label: string;
  flashBytes: number;
  ramBytes: number;
}

const chipPresets: ChipPreset[] = [
  { label: 'ING9188xx / ING91800 (512KB Flash / 64KB RAM)', flashBytes: 512 * 1024, ramBytes: 64 * 1024 },
  { label: 'ING9168xx / ING91600 (2048KB Flash / 32KB RAM)', flashBytes: 2048 * 1024, ramBytes: 32 * 1024 },
  { label: 'ING208xx / ING2000 (2048KB Flash / 32KB RAM)', flashBytes: 2048 * 1024, ramBytes: 32 * 1024 },
  { label: 'STM32F103C8 (64KB Flash / 20KB RAM)', flashBytes: 64 * 1024, ramBytes: 20 * 1024 },
  { label: 'STM32F407VG (1024KB Flash / 128KB RAM)', flashBytes: 1024 * 1024, ramBytes: 128 * 1024 },
  { label: 'STM32H743VI (2048KB Flash / 1024KB RAM)', flashBytes: 2048 * 1024, ramBytes: 1024 * 1024 },
  { label: 'RP2040 (2048KB Flash / 264KB RAM)', flashBytes: 2048 * 1024, ramBytes: 264 * 1024 },
  { label: 'NRF52840 (1024KB Flash / 256KB RAM)', flashBytes: 1024 * 1024, ramBytes: 256 * 1024 },
  { label: '自定义容量 (手动指定)', flashBytes: 0, ramBytes: 0 },
];

const selectedPreset = ref<number>(0);
const customFlashKB = ref<number>(512);
const customRamKB = ref<number>(64);

const effectiveFlashBytes = computed<number>(() => {
  if (selectedPreset.value === chipPresets.length - 1) {
    return (customFlashKB.value || 0) * 1024;
  }
  return chipPresets[selectedPreset.value]?.flashBytes || 512 * 1024;
});

const effectiveRamBytes = computed<number>(() => {
  if (selectedPreset.value === chipPresets.length - 1) {
    return (customRamKB.value || 0) * 1024;
  }
  return chipPresets[selectedPreset.value]?.ramBytes || 64 * 1024;
});

// Analysis results
const analysisData = ref<FirmwareResourceAnalysis | null>(null);

// Sub Tabs view state
const activeSubTab = ref<'treemap' | 'linear' | 'modules' | 'sections'>('treemap');
const treemapRegion = ref<'flash' | 'ram'>('flash');
const selectedItem = ref<{
  name: string;
  category?: string;
  size: number;
  size_str: string;
  percent?: number;
  object?: string;
  library?: string;
  address?: string;
  start?: string;
  end?: string;
} | null>(null);

// Modules table state
const searchQuery = ref<string>('');
const sortField = ref<'rom_total' | 'ram_total' | 'code' | 'zi_data' | 'name'>('rom_total');
const sortAsc = ref<boolean>(false);
const expandedModules = ref<Set<string>>(new Set());

// Tree expanded state
const expandedTreeNodes = ref<Set<string>>(new Set(['flash-root', 'ram-root']));

function toggleTreeNode(id: string) {
  if (expandedTreeNodes.value.has(id)) {
    expandedTreeNodes.value.delete(id);
  } else {
    expandedTreeNodes.value.add(id);
  }
}

// Toggle expand symbol list in module
function toggleExpandModule(modName: string) {
  if (expandedModules.value.has(modName)) {
    expandedModules.value.delete(modName);
  } else {
    expandedModules.value.add(modName);
  }
}

function expandAllModules() {
  if (!analysisData.value) return;
  analysisData.value.modules.forEach(m => expandedModules.value.add(m.name));
}

function collapseAllModules() {
  expandedModules.value.clear();
}

// Filtered & Sorted Modules
const filteredModules = computed<FirmwareModule[]>(() => {
  if (!analysisData.value) return [];
  let list = analysisData.value.modules;

  if (searchQuery.value.trim()) {
    const q = searchQuery.value.trim().toLowerCase();
    list = list.filter(m =>
      m.name.toLowerCase().includes(q) ||
      m.full_path.toLowerCase().includes(q) ||
      (m.symbols && m.symbols.some(s => s.name.toLowerCase().includes(q)))
    );
  }

  return [...list].sort((a, b) => {
    let valA = a[sortField.value];
    let valB = b[sortField.value];
    if (typeof valA === 'string') {
      return sortAsc.value
        ? (valA as string).localeCompare(valB as string)
        : (valB as string).localeCompare(valA as string);
    }
    return sortAsc.value ? (valA as number) - (valB as number) : (valB as number) - (valA as number);
  });
});

// Perform Analysis
async function analyzeFirmware(pathOverride?: string) {
  const targetPath = pathOverride || filePath.value.trim();
  if (!targetPath) {
    errorMsg.value = '请先输入或选择 .axf / .elf / .map 固件文件路径';
    return;
  }

  isAnalyzing.value = true;
  errorMsg.value = '';

  try {
    const res: FirmwareResourceAnalysis = await safeInvoke('analyze_firmware_resources', {
      filePath: targetPath,
      chipFlashSize: effectiveFlashBytes.value,
      chipRamSize: effectiveRamBytes.value,
    });
    analysisData.value = res;
    if (pathOverride) {
      filePath.value = pathOverride;
    }
    // Select the max function or first item by default for details card
    if (res.top_metrics?.max_function) {
      selectedItem.value = {
        name: res.top_metrics.max_function.name,
        category: 'Code',
        size: res.top_metrics.max_function.size,
        size_str: res.top_metrics.max_function.size_str,
        object: res.top_metrics.max_function.object,
        address: res.top_metrics.max_function.address
      };
    }
  } catch (err: any) {
    errorMsg.value = `固件资源分析失败: ${err}`;
    console.error('Firmware analysis error:', err);
  } finally {
    isAnalyzing.value = false;
  }
}

async function handlePickFile() {
  try {
    const selected: string | null = await safeInvoke('pick_firmware_file', {
      title: '选择要分析的固件或链接映射文件 (.axf / .elf / .map / .hex / .bin)'
    });
    if (selected) {
      filePath.value = selected;
      await analyzeFirmware(selected);
    }
  } catch (err: any) {
    console.error('File pick error:', err);
  }
}

// Toolchain badge styling
function getToolchainBadge(type: string) {
  switch (type.toLowerCase()) {
    case 'gcc':
      return { label: 'GNU Arm GCC', bg: 'bg-blue-500/20 text-blue-300 border-blue-500/40' };
    case 'armcc':
      return { label: 'Keil ARMCC (AC5)', bg: 'bg-amber-500/20 text-amber-300 border-amber-500/40' };
    case 'armclang':
      return { label: 'ARMClang (AC6)', bg: 'bg-purple-500/20 text-purple-300 border-purple-500/40' };
    case 'map_file':
      return { label: 'Keil Linker MAP 映射', bg: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/40' };
    default:
      return { label: 'ELF 编译器', bg: 'bg-zinc-700/50 text-zinc-300 border-zinc-600' };
  }
}

// Category Color Helper
function getCategoryColor(cat?: string) {
  switch ((cat || '').toUpperCase()) {
    case 'CODE':
      return { bg: 'bg-blue-600', border: 'border-blue-400', text: 'text-blue-300', badge: 'bg-blue-950 text-blue-400 border-blue-800' };
    case 'RO-DATA':
    case 'RO_DATA':
    case 'CONST':
      return { bg: 'bg-amber-600', border: 'border-amber-400', text: 'text-amber-300', badge: 'bg-amber-950 text-amber-400 border-amber-800' };
    case 'RW-DATA':
    case 'RW_DATA':
    case 'DATA':
      return { bg: 'bg-purple-600', border: 'border-purple-400', text: 'text-purple-300', badge: 'bg-purple-950 text-purple-400 border-purple-800' };
    case 'ZI-DATA':
    case 'ZI_DATA':
    case 'BSS':
      return { bg: 'bg-emerald-600', border: 'border-emerald-400', text: 'text-emerald-300', badge: 'bg-emerald-950 text-emerald-400 border-emerald-800' };
    case 'PAD':
    case 'ALIGN':
      return { bg: 'bg-slate-600', border: 'border-slate-400', text: 'text-slate-300', badge: 'bg-slate-800 text-slate-400 border-slate-700' };
    case 'HEAP':
    case 'STACK':
      return { bg: 'bg-cyan-600', border: 'border-cyan-400', text: 'text-cyan-300', badge: 'bg-cyan-950 text-cyan-400 border-cyan-800' };
    case 'FREE':
    case 'GAP':
      return { bg: 'bg-zinc-800', border: 'border-zinc-700', text: 'text-zinc-400', badge: 'bg-zinc-900 text-zinc-400 border-zinc-700' };
    default:
      return { bg: 'bg-indigo-600', border: 'border-indigo-400', text: 'text-indigo-300', badge: 'bg-indigo-950 text-indigo-400 border-indigo-800' };
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

// Squarified Treemap Computation for visual grid
interface LayoutTile {
  name: string;
  size: number;
  size_str: string;
  category: string;
  color?: string;
  percent: number;
  object?: string;
  library?: string;
  address?: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

const treemapTiles = computed<LayoutTile[]>(() => {
  if (!analysisData.value?.treemap) return [];
  const source = treemapRegion.value === 'flash'
    ? analysisData.value.treemap.flash
    : analysisData.value.treemap.ram;

  if (!source?.categories || source.categories.length === 0) return [];

  const rawList: Array<{
    name: string;
    size: number;
    size_str: string;
    category: string;
    color?: string;
    percent: number;
    object?: string;
  }> = [];

  const regionTotal = source.size || 1;

  for (const cat of source.categories) {
    if (cat.items && cat.items.length > 0) {
      let itemsTotal = 0;
      for (const it of cat.items) {
        if (it.size > 0) {
          itemsTotal += it.size;
          rawList.push({
            name: it.name,
            size: it.size,
            size_str: it.size_str,
            category: cat.name,
            color: cat.color,
            percent: parseFloat(((it.size / regionTotal) * 100).toFixed(2)),
            object: it.object
          });
        }
      }
      const remainder = cat.size - itemsTotal;
      if (remainder > 0) {
        rawList.push({
          name: `${cat.name} (其余微小项)`,
          size: remainder,
          size_str: formatBytes(remainder),
          category: cat.name,
          color: cat.color,
          percent: parseFloat(((remainder / regionTotal) * 100).toFixed(2))
        });
      }
    } else if (cat.size > 0) {
      rawList.push({
        name: cat.name,
        size: cat.size,
        size_str: cat.size_str,
        category: cat.name,
        color: cat.color,
        percent: parseFloat(((cat.size / regionTotal) * 100).toFixed(2))
      });
    }
  }

  if (rawList.length === 0) return [];

  // Sort descending by size to ensure optimal squarified aspect ratios
  rawList.sort((a, b) => b.size - a.size);

  // Canvas bounds: 1000 x 600
  const W = 1000;
  const H = 600;

  // Squarify / slice-and-dice recursive partition
  const tiles: LayoutTile[] = [];

  function layoutRow(items: typeof rawList, x: number, y: number, w: number, h: number) {
    if (items.length === 0 || w <= 0 || h <= 0) return;
    if (items.length === 1) {
      const it = items[0];
      tiles.push({
        name: it.name,
        size: it.size,
        size_str: it.size_str,
        category: it.category,
        color: it.color,
        percent: it.percent,
        object: it.object,
        x,
        y,
        w,
        h
      });
      return;
    }

    const subTotal = items.reduce((s, it) => s + it.size, 0);
    if (subTotal <= 0) return;

    // Split items into two balanced halves
    let running = 0;
    let splitIdx = 0;
    for (let i = 0; i < items.length; i++) {
      running += items[i].size;
      if (running >= subTotal / 2) {
        splitIdx = i;
        break;
      }
    }
    if (splitIdx === items.length - 1 && items.length > 1) {
      splitIdx = items.length - 2;
    }

    const firstGroup = items.slice(0, splitIdx + 1);
    const secondGroup = items.slice(splitIdx + 1);
    const firstVal = firstGroup.reduce((s, it) => s + it.size, 0);
    const ratio = firstVal / subTotal;

    if (w >= h) {
      // Split horizontally (left / right)
      const w1 = w * ratio;
      const w2 = w - w1;
      layoutRow(firstGroup, x, y, w1, h);
      layoutRow(secondGroup, x + w1, y, w2, h);
    } else {
      // Split vertically (top / bottom)
      const h1 = h * ratio;
      const h2 = h - h1;
      layoutRow(firstGroup, x, y, w, h1);
      layoutRow(secondGroup, x, y + h1, w, h2);
    }
  }

  layoutRow(rawList, 0, 0, W, H);
  return tiles;
});

// Treemap Interactive State & Style Helpers
const isTreemapExpanded = ref<boolean>(false);
const hoveredTile = ref<LayoutTile | null>(null);
const activeInspectItem = computed<any>(() => hoveredTile.value || selectedItem.value || null);

function getTileBgColor(tile: any): string {
  if (!tile) return '#334155';
  if (tile.color) return tile.color;
  const cat = (tile.category || '').toUpperCase();
  if (cat.includes('CODE') || cat.includes('.TEXT')) return '#1e40af'; // Blue-700
  if (cat.includes('RO') || cat.includes('CONST')) return '#b45309';   // Amber-700
  if (cat.includes('RW') || cat.includes('DATA')) return '#7e22ce';   // Purple-700
  if (cat.includes('ZI') || cat.includes('BSS')) return '#065f46';    // Emerald-700
  return '#334155'; // Slate-700
}

function getCategoryPillClass(category: string): string {
  const cat = (category || '').toUpperCase();
  if (cat.includes('CODE') || cat.includes('.TEXT')) return 'bg-blue-950/90 text-blue-200 border border-blue-600/70';
  if (cat.includes('RO') || cat.includes('CONST')) return 'bg-amber-950/90 text-amber-200 border border-amber-600/70';
  if (cat.includes('RW') || cat.includes('DATA')) return 'bg-purple-950/90 text-purple-200 border border-purple-600/70';
  if (cat.includes('ZI') || cat.includes('BSS')) return 'bg-emerald-950/90 text-emerald-200 border border-emerald-600/70';
  return 'bg-slate-800 text-slate-300 border border-slate-700';
}

// Linear Memory Blocks
const linearFlashBlocks = computed<LinearMemoryBlock[]>(() => {
  return analysisData.value?.linear_memory?.flash_blocks || [];
});

const linearRamBlocks = computed<LinearMemoryBlock[]>(() => {
  return analysisData.value?.linear_memory?.ram_blocks || [];
});

// Export Markdown Report
function exportMarkdownReport() {
  if (!analysisData.value) return;
  const d = analysisData.value;
  const s = d.summary;

  let md = `# 固件资源占用分析报告\n\n`;
  md += `- **固件文件**: \`${d.file_name}\` (${d.file_size_str})\n`;
  md += `- **完整路径**: \`${d.file_path}\`\n`;
  md += `- **编译器**: ${d.toolchain.name}\n`;
  md += `- **目标架构**: ${d.architecture}\n\n`;

  md += `## 1. 总体内存与存储开销 (Memory Footprint)\n\n`;
  md += `| 资源类型 | 总占用 | 组成细分 | 芯片规格 | 使用率 | 剩余空间 |\n`;
  md += `| :--- | :--- | :--- | :--- | :--- | :--- |\n`;
  md += `| **ROM (Flash)** | **${s.rom_total_str}** | Code: ${s.code_str} (${s.rom_code_ratio}%)<br>RO-Data: ${s.ro_data_str} (${s.rom_ro_ratio}%)<br>RW-Data: ${s.rw_data_str} (${s.rom_rw_ratio}%) | ${s.chip_flash_str} | **${s.flash_usage_percent ?? 'N/A'}%** | ${s.flash_free_str} |\n`;
  md += `| **RAM (SRAM)** | **${s.ram_total_str}** | RW-Data: ${s.rw_data_str} (${s.ram_rw_ratio}%)<br>ZI-Data: ${s.zi_data_str} (${s.ram_zi_ratio}%) | ${s.chip_ram_str} | **${s.ram_usage_percent ?? 'N/A'}%** | ${s.ram_free_str} |\n\n`;

  if (d.top_metrics) {
    const tm = d.top_metrics;
    md += `## 2. 核心指标概览 (Key Metrics)\n\n`;
    md += `- **⚡ 最大函数**: \`${tm.max_function?.name || 'N/A'}\` (${tm.max_function?.size_str || '0 B'}) - \`${tm.max_function?.object || ''}\`\n`;
    md += `- **📦 最大对象**: \`${tm.max_object?.name || 'N/A'}\` (${tm.max_object?.size_str || '0 B'}) - \`${tm.max_object?.section || ''}\`\n`;
    md += `- **🛡️ 对齐填充 (PAD)**: ${tm.total_padding?.size_str || '0 B'}\n`;
    md += `- **⚖️ 堆栈安全间隙**: ${tm.heap_stack_gap?.size_str || '0 B'} (${tm.heap_stack_gap?.low_margin ? '⚠️ 存在溢出风险' : '空间充裕'})\n\n`;
  }

  md += `## 3. 模块级资源占用排行 (前 20 大模块)\n\n`;
  md += `| 模块文件 | ROM 占用 | ROM 占比 | RAM 占用 | RAM 占比 | Code | RO-Data | RW-Data | ZI-Data |\n`;
  md += `| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n`;

  const topModules = [...d.modules].sort((a, b) => b.rom_total - a.rom_total).slice(0, 20);
  for (const m of topModules) {
    md += `| \`${m.name}\` | **${m.rom_total_str}** | ${m.rom_percent}% | **${m.ram_total_str}** | ${m.ram_percent}% | ${m.code_str} | ${m.ro_data_str} | ${m.rw_data_str} | ${m.zi_data_str} |\n`;
  }

  md += `\n*分析时间: ${new Date().toLocaleString()}*\n`;

  navigator.clipboard.writeText(md);
  isCopied.value = true;
  setTimeout(() => {
    isCopied.value = false;
  }, 2500);
}

// Export CSV
function exportCsv() {
  if (!analysisData.value) return;
  const d = analysisData.value;

  let csv = `Module,Full Path,ROM Total (Bytes),ROM Percent (%),RAM Total (Bytes),RAM Percent (%),Code (Bytes),RO Data (Bytes),RW Data (Bytes),ZI Data (Bytes),Symbols Count\n`;
  for (const m of d.modules) {
    csv += `"${m.name}","${m.full_path.replace(/"/g, '""')}",${m.rom_total},${m.rom_percent},${m.ram_total},${m.ram_percent},${m.code},${m.ro_data},${m.rw_data},${m.zi_data},${m.symbols_count}\n`;
  }

  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${d.file_name}_resource_analysis.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

onMounted(() => {
  if (props.initialFilePath) {
    analyzeFirmware(props.initialFilePath);
  }
});
</script>

<template>
  <div class="h-full flex flex-col p-3 sm:p-4 bg-slate-950 text-slate-100 text-xs overflow-y-auto space-y-3">
    <!-- Top Control Bar: File Path & Chip Presets -->
    <div class="bg-slate-900 border border-slate-800 rounded-lg p-3 space-y-3 shadow-sm">
      <div class="flex items-center justify-between border-b border-slate-800 pb-2">
        <div class="flex items-center gap-2 font-semibold text-slate-200">
          <PieChart class="w-4 h-4 text-emerald-400" />
          <span>固件与链接映射资源智能可视化分析器 (Keil MDK Map / ELF / AXF / GCC)</span>
        </div>
        <div class="flex items-center gap-2 text-slate-400 text-[11px]">
          <span>支持 ING916/ING918/ING20 系列、Keil MDK & GCC MAP 文件秒级解析</span>
        </div>
      </div>

      <!-- File Path & Selectors -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
        <!-- File Path Input -->
        <div class="md:col-span-2 space-y-1">
          <label class="block text-slate-400 text-[11px] font-medium">
            目标固件或 MAP 链接映射文件 (.map / .axf / .elf)
          </label>
          <div class="flex gap-2">
            <div class="relative flex-1 flex items-center">
              <input
                v-model="filePath"
                type="text"
                placeholder="点击右侧浏览选择文件，或粘贴绝对路径 (.map / .axf / .elf)"
                class="w-full bg-slate-950 border border-slate-800 rounded px-3 py-1.5 pr-24 text-slate-200 outline-none focus:border-emerald-500 font-mono text-xs placeholder:text-slate-600"
                @keydown.enter="analyzeFirmware()"
              />
              <button
                @click="handlePickFile"
                type="button"
                class="absolute right-1 px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-emerald-400 rounded text-xs flex items-center gap-1 transition-colors border border-slate-700"
                title="打开系统文件选择对话框"
              >
                <FolderOpen class="w-3.5 h-3.5" />
                <span>浏览选择</span>
              </button>
            </div>
            <button
              @click="analyzeFirmware()"
              :disabled="isAnalyzing || !filePath.trim()"
              class="flex items-center gap-1.5 px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white rounded font-medium transition-colors shadow-sm shrink-0"
            >
              <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isAnalyzing }" />
              <span>{{ isAnalyzing ? '分析中...' : '开始分析' }}</span>
            </button>
          </div>
        </div>

        <!-- Target Chip Presets -->
        <div class="space-y-1">
          <label class="block text-slate-400 text-[11px] font-medium">芯片规格预设 (计算物理容量占比)</label>
          <select
            v-model="selectedPreset"
            @change="analysisData && analyzeFirmware()"
            class="w-full bg-slate-950 border border-slate-800 rounded px-3 py-1.5 text-slate-200 outline-none focus:border-emerald-500 text-xs"
          >
            <option v-for="(p, idx) in chipPresets" :key="idx" :value="idx">
              {{ p.label }}
            </option>
          </select>
        </div>
      </div>

      <!-- Custom Chip Input if Custom selected -->
      <div v-if="selectedPreset === chipPresets.length - 1" class="flex items-center gap-4 bg-slate-950/60 p-2.5 rounded border border-slate-800">
        <span class="text-slate-400 text-[11px] font-medium">自定义容量:</span>
        <div class="flex items-center gap-2">
          <span class="text-slate-400 text-[11px]">Flash:</span>
          <input
            v-model.number="customFlashKB"
            type="number"
            class="w-24 bg-slate-900 border border-slate-800 rounded px-2 py-1 text-slate-200 font-mono text-xs outline-none focus:border-emerald-500"
          />
          <span class="text-slate-500 text-[11px]">KB</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-slate-400 text-[11px]">RAM:</span>
          <input
            v-model.number="customRamKB"
            type="number"
            class="w-24 bg-slate-900 border border-slate-800 rounded px-2 py-1 text-slate-200 font-mono text-xs outline-none focus:border-emerald-500"
          />
          <span class="text-slate-500 text-[11px]">KB</span>
        </div>
        <button
          @click="analysisData && analyzeFirmware()"
          class="px-2.5 py-1 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded text-[11px] transition-colors"
        >
          重新测算
        </button>
      </div>

      <!-- Error alert -->
      <div v-if="errorMsg" class="bg-rose-950/40 border border-rose-800 text-rose-300 px-3 py-2 rounded text-xs">
        {{ errorMsg }}
      </div>
    </div>

    <!-- Main Results Section -->
    <template v-if="analysisData">
      <!-- High-level Metric Cards (Top KPI) -->
      <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
        <!-- Card 1: Toolchain & Binary Metadata -->
        <div class="bg-slate-900 border border-slate-800 rounded-lg p-3.5 flex flex-col justify-between shadow-sm">
          <div class="flex items-center justify-between pb-2 border-b border-slate-800">
            <div class="flex items-center gap-2">
              <Cpu class="w-4 h-4 text-emerald-400" />
              <span class="font-semibold text-slate-200">目标编译环境</span>
            </div>
            <span
              class="px-2 py-0.5 rounded border text-[10px] font-mono font-medium"
              :class="getToolchainBadge(analysisData.toolchain.type).bg"
            >
              {{ getToolchainBadge(analysisData.toolchain.type).label }}
            </span>
          </div>

          <div class="space-y-1.5 mt-2.5 text-xs">
            <div class="flex justify-between items-center">
              <span class="text-slate-400">固件文件:</span>
              <span class="font-mono text-slate-200 font-medium truncate max-w-[170px]" :title="analysisData.file_path">
                {{ analysisData.file_name }}
              </span>
            </div>
            <div class="flex justify-between items-center">
              <span class="text-slate-400">目标架构:</span>
              <span class="font-mono text-slate-200">{{ analysisData.architecture }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span class="text-slate-400">固件大小:</span>
              <span class="font-mono text-slate-300">{{ analysisData.file_size_str }}</span>
            </div>
            <div class="flex justify-between items-center">
              <span class="text-slate-400">模块总计:</span>
              <span class="font-mono text-emerald-400 font-semibold">{{ analysisData.modules.length }} 个编译单元</span>
            </div>
          </div>

          <div class="mt-2.5 pt-2 border-t border-slate-800 text-[10px] text-slate-500 font-mono truncate" :title="analysisData.toolchain.raw_producer">
            {{ analysisData.toolchain.raw_producer || analysisData.toolchain.name }}
          </div>
        </div>

        <!-- Card 2: ROM (Flash) Usage Card -->
        <div class="bg-slate-900 border border-slate-800 rounded-lg p-3.5 flex flex-col justify-between shadow-sm">
          <div class="flex items-center justify-between pb-2 border-b border-slate-800">
            <div class="flex items-center gap-2">
              <HardDrive class="w-4 h-4 text-cyan-400" />
              <span class="font-semibold text-slate-200">ROM 占用 (Flash)</span>
            </div>
            <span class="text-xs font-mono font-bold text-cyan-400">
              {{ analysisData.summary.rom_total_str }}
            </span>
          </div>

          <!-- Flash Progress Gauge -->
          <div class="mt-2.5 space-y-1">
            <div class="flex justify-between items-center text-[11px]">
              <span class="text-slate-400">Flash 占用率:</span>
              <span class="font-mono font-bold" :class="analysisData.summary.flash_usage_percent && analysisData.summary.flash_usage_percent > 90 ? 'text-rose-400' : 'text-cyan-300'">
                {{ analysisData.summary.flash_usage_percent !== null ? `${analysisData.summary.flash_usage_percent}%` : '未指定' }}
              </span>
            </div>
            <!-- Progress Bar -->
            <div class="w-full bg-slate-800 rounded-full h-2 overflow-hidden flex">
              <div
                class="bg-cyan-500 h-full transition-all duration-500"
                :style="{ width: `${Math.min(analysisData.summary.flash_usage_percent || 0, 100)}%` }"
              ></div>
            </div>
            <div class="flex justify-between text-[10px] text-slate-500 font-mono">
              <span>已用: {{ analysisData.summary.rom_total_str }}</span>
              <span>规格: {{ analysisData.summary.chip_flash_str }} (余 {{ analysisData.summary.flash_free_str }})</span>
            </div>
          </div>

          <!-- Breakdown: Code + RO + RW -->
          <div class="mt-2.5 pt-2 border-t border-slate-800 grid grid-cols-3 gap-1.5 text-center">
            <div class="bg-slate-950/70 p-1 rounded border border-slate-800">
              <div class="text-[9px] text-blue-400 font-medium">Code (代码)</div>
              <div class="font-mono font-semibold text-slate-200 text-[10px]">{{ analysisData.summary.code_str }}</div>
              <div class="text-[8px] text-slate-500 font-mono">{{ analysisData.summary.rom_code_ratio }}%</div>
            </div>
            <div class="bg-slate-950/70 p-1 rounded border border-slate-800">
              <div class="text-[9px] text-amber-400 font-medium">RO-Data</div>
              <div class="font-mono font-semibold text-slate-200 text-[10px]">{{ analysisData.summary.ro_data_str }}</div>
              <div class="text-[8px] text-slate-500 font-mono">{{ analysisData.summary.rom_ro_ratio }}%</div>
            </div>
            <div class="bg-slate-950/70 p-1 rounded border border-slate-800">
              <div class="text-[9px] text-purple-400 font-medium">RW-Data</div>
              <div class="font-mono font-semibold text-slate-200 text-[10px]">{{ analysisData.summary.rw_data_str }}</div>
              <div class="text-[8px] text-slate-500 font-mono">{{ analysisData.summary.rom_rw_ratio }}%</div>
            </div>
          </div>
        </div>

        <!-- Card 3: RAM (SRAM) Usage Card -->
        <div class="bg-slate-900 border border-slate-800 rounded-lg p-3.5 flex flex-col justify-between shadow-sm">
          <div class="flex items-center justify-between pb-2 border-b border-slate-800">
            <div class="flex items-center gap-2">
              <Layers class="w-4 h-4 text-emerald-400" />
              <span class="font-semibold text-slate-200">RAM 静态占用 (SRAM)</span>
            </div>
            <span class="text-xs font-mono font-bold text-emerald-400">
              {{ analysisData.summary.ram_total_str }}
            </span>
          </div>

          <!-- RAM Progress Gauge -->
          <div class="mt-2.5 space-y-1">
            <div class="flex justify-between items-center text-[11px]">
              <span class="text-slate-400">RAM 占用率:</span>
              <span class="font-mono font-bold" :class="analysisData.summary.ram_usage_percent && analysisData.summary.ram_usage_percent > 90 ? 'text-rose-400' : 'text-emerald-300'">
                {{ analysisData.summary.ram_usage_percent !== null ? `${analysisData.summary.ram_usage_percent}%` : '未指定' }}
              </span>
            </div>
            <!-- Progress Bar -->
            <div class="w-full bg-slate-800 rounded-full h-2 overflow-hidden flex">
              <div
                class="bg-emerald-500 h-full transition-all duration-500"
                :style="{ width: `${Math.min(analysisData.summary.ram_usage_percent || 0, 100)}%` }"
              ></div>
            </div>
            <div class="flex justify-between text-[10px] text-slate-500 font-mono">
              <span>已用: {{ analysisData.summary.ram_total_str }}</span>
              <span>规格: {{ analysisData.summary.chip_ram_str }} (余 {{ analysisData.summary.ram_free_str }})</span>
            </div>
          </div>

          <!-- Breakdown: RW-Data + ZI-Data -->
          <div class="mt-2.5 pt-2 border-t border-slate-800 grid grid-cols-2 gap-2 text-center">
            <div class="bg-slate-950/70 p-1 rounded border border-slate-800">
              <div class="text-[9px] text-purple-400 font-medium">RW-Data (初始变量)</div>
              <div class="font-mono font-semibold text-slate-200 text-[10px]">{{ analysisData.summary.rw_data_str }}</div>
              <div class="text-[8px] text-slate-500 font-mono">{{ analysisData.summary.ram_rw_ratio }}%</div>
            </div>
            <div class="bg-slate-950/70 p-1 rounded border border-slate-800">
              <div class="text-[9px] text-emerald-400 font-medium">ZI-Data (BSS 清零)</div>
              <div class="font-mono font-semibold text-slate-200 text-[10px]">{{ analysisData.summary.zi_data_str }}</div>
              <div class="text-[8px] text-slate-500 font-mono">{{ analysisData.summary.ram_zi_ratio }}%</div>
            </div>
          </div>
        </div>
      </div>

      <!-- Top Metrics Pill Banner (Absorbing key metrics card style from reference image) -->
      <div v-if="analysisData.top_metrics" class="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
        <!-- Top 1: Max Function -->
        <div
          @click="analysisData.top_metrics.max_function && (selectedItem = {
            name: analysisData.top_metrics.max_function.name,
            category: 'Code',
            size: analysisData.top_metrics.max_function.size,
            size_str: analysisData.top_metrics.max_function.size_str,
            object: analysisData.top_metrics.max_function.object,
            address: analysisData.top_metrics.max_function.address
          })"
          class="bg-slate-900/90 border border-slate-800 hover:border-blue-500/50 p-2.5 rounded-lg flex items-center gap-2.5 cursor-pointer transition"
        >
          <div class="p-2 rounded bg-blue-500/10 text-blue-400 border border-blue-500/20">
            <Sparkles class="w-4 h-4" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="text-[10px] text-slate-400">最大函数 (Max Func)</div>
            <div class="font-bold text-slate-200 text-xs truncate" :title="analysisData.top_metrics.max_function.name">
              {{ analysisData.top_metrics.max_function.name }}
            </div>
            <div class="text-[10px] text-blue-400 font-mono font-semibold">
              {{ analysisData.top_metrics.max_function.size_str }}
            </div>
          </div>
        </div>

        <!-- Top 2: Max Object -->
        <div
          @click="analysisData.top_metrics.max_object && (selectedItem = {
            name: analysisData.top_metrics.max_object.name,
            category: 'Data',
            size: analysisData.top_metrics.max_object.size,
            size_str: analysisData.top_metrics.max_object.size_str,
            object: analysisData.top_metrics.max_object.object,
            address: analysisData.top_metrics.max_object.address
          })"
          class="bg-slate-900/90 border border-slate-800 hover:border-purple-500/50 p-2.5 rounded-lg flex items-center gap-2.5 cursor-pointer transition"
        >
          <div class="p-2 rounded bg-purple-500/10 text-purple-400 border border-purple-500/20">
            <Box class="w-4 h-4" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="text-[10px] text-slate-400">最大变量/对象 (Max Obj)</div>
            <div class="font-bold text-slate-200 text-xs truncate" :title="analysisData.top_metrics.max_object.name">
              {{ analysisData.top_metrics.max_object.name }}
            </div>
            <div class="text-[10px] text-purple-400 font-mono font-semibold">
              {{ analysisData.top_metrics.max_object.size_str }}
            </div>
          </div>
        </div>

        <!-- Top 3: Total Padding -->
        <div class="bg-slate-900/90 border border-slate-800 p-2.5 rounded-lg flex items-center gap-2.5">
          <div class="p-2 rounded bg-slate-800 text-slate-400 border border-slate-700">
            <ShieldAlert class="w-4 h-4" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="text-[10px] text-slate-400">总对齐填充 (Padding)</div>
            <div class="font-bold text-slate-300 text-xs font-mono">
              {{ analysisData.top_metrics.total_padding.size_str }}
            </div>
            <div class="text-[10px] text-slate-500">段对齐与字节空隙</div>
          </div>
        </div>

        <!-- Top 4: Heap-Stack Gap -->
        <div class="bg-slate-900/90 border border-slate-800 p-2.5 rounded-lg flex items-center gap-2.5">
          <div
            class="p-2 rounded border"
            :class="analysisData.top_metrics.heap_stack_gap.low_margin ? 'bg-rose-500/10 text-rose-400 border-rose-500/30' : 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'"
          >
            <AlertTriangle v-if="analysisData.top_metrics.heap_stack_gap.low_margin" class="w-4 h-4" />
            <CheckCircle2 v-else class="w-4 h-4" />
          </div>
          <div class="min-w-0 flex-1">
            <div class="text-[10px] text-slate-400 flex items-center justify-between">
              <span>堆栈安全间隙</span>
              <span
                v-if="analysisData.top_metrics.heap_stack_gap.low_margin"
                class="text-[9px] px-1 bg-rose-950 text-rose-400 rounded border border-rose-800"
              >
                ⚠️ 低余量
              </span>
            </div>
            <div class="font-bold text-slate-200 text-xs font-mono">
              {{ analysisData.top_metrics.heap_stack_gap.size_str }}
            </div>
            <div class="text-[10px] text-slate-500">Heap-Stack Margin</div>
          </div>
        </div>
      </div>

      <!-- Action Toolbar & Tabs Bar -->
      <div class="bg-slate-900 border border-slate-800 rounded-lg p-2.5 flex flex-wrap items-center justify-between gap-2.5">
        <!-- Sub Tabs -->
        <div class="flex items-center gap-1 bg-slate-950 p-1 rounded-md border border-slate-800">
          <button
            @click="activeSubTab = 'treemap'"
            class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors"
            :class="activeSubTab === 'treemap' ? 'bg-indigo-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'"
          >
            <LayoutGrid class="w-3.5 h-3.5" />
            <span>Treemap 矩阵树图</span>
          </button>
          <button
            @click="activeSubTab = 'linear'"
            class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors"
            :class="activeSubTab === 'linear' ? 'bg-indigo-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'"
          >
            <BarChart3 class="w-3.5 h-3.5" />
            <span>线性物理内存布局</span>
          </button>
          <button
            @click="activeSubTab = 'modules'"
            class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors"
            :class="activeSubTab === 'modules' ? 'bg-indigo-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'"
          >
            <FileCode class="w-3.5 h-3.5" />
            <span>模块明细表 ({{ analysisData.modules.length }})</span>
          </button>
          <button
            @click="activeSubTab = 'sections'"
            class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium transition-colors"
            :class="activeSubTab === 'sections' ? 'bg-indigo-600 text-white shadow-sm' : 'text-slate-400 hover:text-slate-200'"
          >
            <Layers class="w-3.5 h-3.5" />
            <span>物理段分布 ({{ analysisData.sections.length }})</span>
          </button>
        </div>

        <!-- Treemap Region Switcher (when treemap is active) -->
        <div v-if="activeSubTab === 'treemap'" class="flex items-center gap-1.5 bg-slate-950 px-2 py-1 rounded border border-slate-800 text-xs">
          <span class="text-slate-400 text-[11px]">观察域:</span>
          <button
            @click="treemapRegion = 'flash'"
            class="px-2 py-0.5 rounded text-xs transition"
            :class="treemapRegion === 'flash' ? 'bg-cyan-600 text-white font-semibold' : 'text-slate-400 hover:text-slate-200'"
          >
            FLASH ({{ analysisData.summary.rom_total_str }})
          </button>
          <button
            @click="treemapRegion = 'ram'"
            class="px-2 py-0.5 rounded text-xs transition"
            :class="treemapRegion === 'ram' ? 'bg-emerald-600 text-white font-semibold' : 'text-slate-400 hover:text-slate-200'"
          >
            RAM ({{ analysisData.summary.ram_total_str }})
          </button>
        </div>

        <!-- Search Box (only for modules) -->
        <div v-if="activeSubTab === 'modules'" class="flex items-center gap-2 flex-1 max-w-sm">
          <div class="relative w-full">
            <Search class="w-3.5 h-3.5 text-slate-500 absolute left-2.5 top-2.5" />
            <input
              v-model="searchQuery"
              type="text"
              placeholder="搜索源文件、函数名或变量..."
              class="w-full bg-slate-950 border border-slate-800 rounded pl-8 pr-3 py-1.5 text-slate-200 outline-none focus:border-indigo-500 text-xs"
            />
          </div>
        </div>

        <!-- Export & Quick Actions -->
        <div class="flex items-center gap-2">
          <button
            v-if="activeSubTab === 'modules'"
            @click="expandedModules.size > 0 ? collapseAllModules() : expandAllModules()"
            class="flex items-center gap-1 px-2.5 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 transition-colors text-xs"
          >
            <span>{{ expandedModules.size > 0 ? '全部折叠' : '全部展开' }}</span>
          </button>

          <button
            @click="exportMarkdownReport"
            class="flex items-center gap-1 px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors text-xs font-medium border border-slate-700"
            title="生成 Markdown 格式分析总结并复制到剪贴板"
          >
            <component :is="isCopied ? Check : Copy" class="w-3.5 h-3.5 text-emerald-400" />
            <span>{{ isCopied ? '报告已复制!' : '导出 Markdown 报告' }}</span>
          </button>

          <button
            @click="exportCsv"
            class="flex items-center gap-1 px-3 py-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-200 transition-colors text-xs font-medium border border-slate-700"
            title="导出 CSV 数据表便于在 Excel 中透视分析"
          >
            <Download class="w-3.5 h-3.5 text-cyan-400" />
            <span>导出 CSV 表格</span>
          </button>
        </div>
      </div>

      <!-- Tab Content 1: Visual Treemap & Linear Memory Layout with Hierarchy & Details Inspector -->
      <div v-if="activeSubTab === 'treemap' || activeSubTab === 'linear'" class="grid grid-cols-1 lg:grid-cols-4 gap-3">
        <!-- Left: Hierarchy Tree (1 col) -->
        <div class="bg-slate-900 border border-slate-800 rounded-lg p-3 flex flex-col h-[560px] overflow-hidden">
          <div class="flex items-center justify-between pb-2 border-b border-slate-800 text-xs font-semibold text-slate-200">
            <span class="flex items-center gap-1.5">
              <Layers class="w-3.5 h-3.5 text-indigo-400" />
              <span>层级导航树 (Hierarchy)</span>
            </span>
          </div>

          <div class="flex-1 overflow-y-auto mt-2 space-y-1 text-xs">
            <template v-if="analysisData.hierarchy && analysisData.hierarchy.length > 0">
              <div v-for="node in analysisData.hierarchy" :key="node.id" class="space-y-0.5">
                <!-- Root Level -->
                <div
                  @click="toggleTreeNode(node.id)"
                  class="flex items-center justify-between px-2 py-1.5 rounded hover:bg-slate-800/80 cursor-pointer text-slate-200 font-semibold"
                >
                  <div class="flex items-center gap-1.5">
                    <component
                      :is="expandedTreeNodes.has(node.id) ? ChevronDown : ChevronRight"
                      class="w-3.5 h-3.5 text-slate-400"
                    />
                    <span>{{ node.label }}</span>
                  </div>
                  <span class="text-[10px] font-mono text-cyan-400">{{ node.size_str }}</span>
                </div>

                <!-- Children Level -->
                <div v-if="expandedTreeNodes.has(node.id) && node.children" class="pl-4 space-y-0.5 border-l border-slate-800 ml-3">
                  <div
                    v-for="child in node.children"
                    :key="child.id"
                    @click="selectedItem = {
                      name: child.label,
                      category: child.type,
                      size: child.size,
                      size_str: child.size_str
                    }"
                    class="flex items-center justify-between px-2 py-1 rounded hover:bg-slate-800/60 cursor-pointer text-[11px] group transition"
                    :class="selectedItem?.name === child.label ? 'bg-indigo-950/60 text-indigo-300 font-medium' : 'text-slate-300'"
                  >
                    <span class="truncate group-hover:text-white" :title="child.label">{{ child.label }}</span>
                    <span class="text-[10px] font-mono text-slate-400 group-hover:text-cyan-300 shrink-0 ml-1">
                      {{ child.size_str }}
                    </span>
                  </div>
                </div>
              </div>
            </template>
            <div v-else class="text-slate-500 text-center py-6">
              解析器正在整理层级树...
            </div>
          </div>
        </div>

        <!-- Center: Main Canvas (Treemap or Linear) (2 cols) -->
        <div
          class="lg:col-span-2 bg-slate-900 border border-slate-800 rounded-lg p-3 flex flex-col overflow-hidden transition-all duration-200"
          :class="isTreemapExpanded && activeSubTab === 'treemap' ? 'h-[780px]' : 'h-[560px]'"
        >
          <!-- View 1: Treemap Interactive Matrix (HTML Responsive Cards) -->
          <template v-if="activeSubTab === 'treemap'">
            <div class="flex items-center justify-between pb-2 border-b border-slate-800 text-xs gap-2">
              <div class="flex items-center gap-2">
                <span class="font-semibold text-slate-200">
                  {{ treemapRegion === 'flash' ? 'Flash 固件占用矩阵树图' : 'RAM 运行时静态内存矩阵树图' }}
                </span>
                <span class="text-[10px] text-slate-500 font-mono hidden md:inline">
                  (按面积成正比，点击方块查看右侧属性)
                </span>
              </div>
              <div class="flex items-center gap-3">
                <div class="flex items-center gap-2 text-[10px]">
                  <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-blue-500 inline-block"></span> Code</span>
                  <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-amber-500 inline-block"></span> RO-Data</span>
                  <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-purple-500 inline-block"></span> RW-Data</span>
                  <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-emerald-500 inline-block"></span> ZI-Data</span>
                </div>
                <button
                  @click="isTreemapExpanded = !isTreemapExpanded"
                  class="flex items-center gap-1 px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 text-[11px] transition shadow-sm"
                  :title="isTreemapExpanded ? '还原默认高度 (560px)' : '放大展开树图高度 (780px)'"
                >
                  <Maximize2 v-if="!isTreemapExpanded" class="w-3 h-3" />
                  <Minimize2 v-else class="w-3 h-3" />
                  <span>{{ isTreemapExpanded ? '还原' : '放大' }}</span>
                </button>
              </div>
            </div>

            <!-- Treemap Interactive Canvas (Crisp HTML Cards with Zero Font Distortion) -->
            <div class="flex-1 mt-2 relative bg-slate-950 rounded-lg border border-slate-800 overflow-hidden select-none">
              <div
                v-for="(tile, i) in treemapTiles"
                :key="i"
                class="absolute box-border p-1.5 flex flex-col justify-between transition-all duration-100 cursor-pointer overflow-hidden group rounded-[3px] border"
                :style="{
                  left: `${(tile.x / 1000 * 100).toFixed(3)}%`,
                  top: `${(tile.y / 600 * 100).toFixed(3)}%`,
                  width: `${(tile.w / 1000 * 100).toFixed(3)}%`,
                  height: `${(tile.h / 600 * 100).toFixed(3)}%`,
                  backgroundColor: getTileBgColor(tile),
                  borderColor: selectedItem?.name === tile.name ? '#38bdf8' : 'rgba(15, 23, 42, 0.85)'
                }"
                :class="[
                  selectedItem?.name === tile.name
                    ? 'ring-2 ring-cyan-400 z-20 shadow-lg brightness-110'
                    : 'hover:z-10 hover:brightness-125 hover:border-cyan-400/60'
                ]"
                @click="selectedItem = tile"
                @mouseenter="hoveredTile = tile"
                @mouseleave="hoveredTile = null"
                :title="`${tile.name}\n分类: ${tile.category}\n大小: ${tile.size_str} (${tile.percent}%)\n所属目标: ${tile.object || 'Linker'}`"
              >
                <!-- Large tile: Name + Category badge + Size + Percent -->
                <div v-if="tile.w >= 100 && tile.h >= 45" class="flex flex-col justify-between h-full overflow-hidden pointer-events-none">
                  <div class="flex items-start justify-between gap-1">
                    <span class="font-bold text-white text-xs leading-snug truncate font-mono tracking-tight drop-shadow-sm">
                      {{ tile.name }}
                    </span>
                    <span
                      v-if="tile.w >= 140"
                      class="text-[9px] px-1 py-0.2 rounded font-mono font-medium shrink-0 shadow-sm"
                      :class="getCategoryPillClass(tile.category)"
                    >
                      {{ tile.category }}
                    </span>
                  </div>
                  <div class="flex items-baseline justify-between mt-auto gap-1">
                    <span class="text-cyan-300 font-mono font-bold text-xs">
                      {{ tile.size_str }}
                    </span>
                    <span class="text-slate-200/90 font-mono text-[10px]">
                      {{ tile.percent }}%
                    </span>
                  </div>
                </div>

                <!-- Medium tile: Name + Size -->
                <div v-else-if="tile.w >= 60 && tile.h >= 28" class="flex flex-col justify-between h-full overflow-hidden pointer-events-none">
                  <span class="font-semibold text-white text-[11px] leading-tight truncate font-mono">
                    {{ tile.name }}
                  </span>
                  <span class="text-cyan-300 font-mono text-[10px] font-bold truncate">
                    {{ tile.size_str }}
                  </span>
                </div>

                <!-- Small tile: Name only -->
                <div v-else-if="tile.w >= 36 && tile.h >= 18" class="flex items-center justify-center h-full overflow-hidden pointer-events-none">
                  <span class="text-slate-100 font-mono text-[10px] truncate px-0.5 font-medium">
                    {{ tile.name }}
                  </span>
                </div>

                <!-- Micro tiles: color block only, tooltip/inspector shows details -->
              </div>

              <!-- Bottom Floating Live Hover Inspector -->
              <div
                v-if="activeInspectItem"
                class="absolute bottom-2 left-2 right-2 bg-slate-900/95 backdrop-blur border border-slate-700/80 rounded-md px-3 py-1.5 flex items-center justify-between text-xs z-30 shadow-2xl pointer-events-none transition-opacity"
              >
                <div class="flex items-center gap-2 truncate">
                  <span
                    class="w-2.5 h-2.5 rounded-full shrink-0 shadow"
                    :style="{ backgroundColor: getTileBgColor(activeInspectItem) }"
                  />
                  <span class="font-bold text-white font-mono truncate text-xs">
                    {{ activeInspectItem.name }}
                  </span>
                  <span
                    class="text-[10px] px-1.5 py-0.2 rounded font-mono font-medium shrink-0"
                    :class="getCategoryPillClass(activeInspectItem.category || '')"
                  >
                    {{ activeInspectItem.category }}
                  </span>
                  <span v-if="activeInspectItem.object" class="text-slate-400 text-[11px] truncate hidden sm:inline">
                    [{{ activeInspectItem.object }}]
                  </span>
                </div>
                <div class="flex items-center gap-3 font-mono shrink-0 ml-2">
                  <span class="text-cyan-300 font-bold text-xs">
                    {{ activeInspectItem.size_str }}
                  </span>
                  <span v-if="activeInspectItem.percent !== undefined" class="text-indigo-300 font-semibold text-[11px]">
                    占比: {{ activeInspectItem.percent }}%
                  </span>
                </div>
              </div>
            </div>
          </template>

          <!-- View 2: Linear Physical Memory Layout (Flash & RAM Contiguous Bars) -->
          <template v-else-if="activeSubTab === 'linear'">
            <div class="flex items-center justify-between pb-2 border-b border-slate-800 text-xs">
              <span class="font-semibold text-slate-200">物理连续地址空间线性分布</span>
              <span class="text-[10px] text-slate-500 font-mono">从低地址到高地址连续排布</span>
            </div>

            <div class="flex-1 mt-3 space-y-6 overflow-y-auto pr-1">
              <!-- Flash Linear Bar -->
              <div class="space-y-2">
                <div class="flex justify-between items-center text-xs">
                  <span class="font-bold text-cyan-400 flex items-center gap-1.5">
                    <HardDrive class="w-3.5 h-3.5" />
                    <span>FLASH 物理线性空间 (0x00000000 ~ )</span>
                  </span>
                  <span class="font-mono text-slate-400 text-[11px]">
                    总容量: {{ analysisData.summary.chip_flash_str }} (已用 {{ analysisData.summary.rom_total_str }})
                  </span>
                </div>

                <!-- Contiguous Memory Bar -->
                <div class="h-9 w-full bg-slate-950 border border-slate-800 rounded-lg overflow-hidden flex shadow-inner">
                  <div
                    v-for="(block, idx) in linearFlashBlocks"
                    :key="idx"
                    :style="{ width: `${block.percent || 10}%` }"
                    :class="getCategoryColor(block.type).bg"
                    class="h-full border-r border-slate-950/60 transition-all hover:opacity-90 cursor-pointer flex items-center justify-center text-[10px] font-mono text-white font-semibold truncate px-1"
                    :title="`${block.name}: ${block.size_str} (${block.percent || 0}%)\n地址: ${block.start || ''} - ${block.end || ''}`"
                    @click="selectedItem = {
                      name: block.name,
                      category: block.type,
                      size: block.size,
                      size_str: block.size_str,
                      percent: block.percent,
                      start: block.start,
                      end: block.end
                    }"
                  >
                    <span v-if="(block.percent || 0) > 4">{{ block.name }}</span>
                  </div>
                </div>

                <!-- Blocks details list -->
                <div class="grid grid-cols-2 sm:grid-cols-3 gap-1.5 text-[11px] font-mono">
                  <div
                    v-for="(block, idx) in linearFlashBlocks"
                    :key="idx"
                    @click="selectedItem = {
                      name: block.name,
                      category: block.type,
                      size: block.size,
                      size_str: block.size_str,
                      percent: block.percent,
                      start: block.start,
                      end: block.end
                    }"
                    class="bg-slate-950/80 p-1.5 rounded border border-slate-800 hover:border-slate-700 cursor-pointer flex items-center justify-between"
                  >
                    <div class="flex items-center gap-1.5 truncate">
                      <span class="w-2 h-2 rounded-full shrink-0" :class="getCategoryColor(block.type).bg"></span>
                      <span class="truncate text-slate-300 font-semibold">{{ block.name }}</span>
                    </div>
                    <span class="text-cyan-400 shrink-0 ml-1">{{ block.size_str }}</span>
                  </div>
                </div>
              </div>

              <!-- RAM Linear Bar -->
              <div class="space-y-2 pt-2 border-t border-slate-800">
                <div class="flex justify-between items-center text-xs">
                  <span class="font-bold text-emerald-400 flex items-center gap-1.5">
                    <Layers class="w-3.5 h-3.5" />
                    <span>SRAM 物理线性空间 (0x20000000 ~ )</span>
                  </span>
                  <span class="font-mono text-slate-400 text-[11px]">
                    总容量: {{ analysisData.summary.chip_ram_str }} (已用 {{ analysisData.summary.ram_total_str }})
                  </span>
                </div>

                <!-- Contiguous Memory Bar -->
                <div class="h-9 w-full bg-slate-950 border border-slate-800 rounded-lg overflow-hidden flex shadow-inner">
                  <div
                    v-for="(block, idx) in linearRamBlocks"
                    :key="idx"
                    :style="{ width: `${block.percent || 10}%` }"
                    :class="getCategoryColor(block.type).bg"
                    class="h-full border-r border-slate-950/60 transition-all hover:opacity-90 cursor-pointer flex items-center justify-center text-[10px] font-mono text-white font-semibold truncate px-1"
                    :title="`${block.name}: ${block.size_str} (${block.percent || 0}%)\n地址: ${block.start || ''} - ${block.end || ''}`"
                    @click="selectedItem = {
                      name: block.name,
                      category: block.type,
                      size: block.size,
                      size_str: block.size_str,
                      percent: block.percent,
                      start: block.start,
                      end: block.end
                    }"
                  >
                    <span v-if="(block.percent || 0) > 4">{{ block.name }}</span>
                  </div>
                </div>

                <!-- Blocks details list -->
                <div class="grid grid-cols-2 sm:grid-cols-3 gap-1.5 text-[11px] font-mono">
                  <div
                    v-for="(block, idx) in linearRamBlocks"
                    :key="idx"
                    @click="selectedItem = {
                      name: block.name,
                      category: block.type,
                      size: block.size,
                      size_str: block.size_str,
                      percent: block.percent,
                      start: block.start,
                      end: block.end
                    }"
                    class="bg-slate-950/80 p-1.5 rounded border border-slate-800 hover:border-slate-700 cursor-pointer flex items-center justify-between"
                  >
                    <div class="flex items-center gap-1.5 truncate">
                      <span class="w-2 h-2 rounded-full shrink-0" :class="getCategoryColor(block.type).bg"></span>
                      <span class="truncate text-slate-300 font-semibold">{{ block.name }}</span>
                    </div>
                    <span class="text-emerald-400 shrink-0 ml-1">{{ block.size_str }}</span>
                  </div>
                </div>
              </div>
            </div>
          </template>
        </div>

        <!-- Right: Details Card (1 col) -->
        <div class="bg-slate-900 border border-slate-800 rounded-lg p-3 flex flex-col h-[560px] overflow-hidden">
          <div class="flex items-center justify-between pb-2 border-b border-slate-800 text-xs font-semibold text-slate-200">
            <span class="flex items-center gap-1.5">
              <Info class="w-3.5 h-3.5 text-indigo-400" />
              <span>所选条目详情 (Details)</span>
            </span>
          </div>

          <div v-if="selectedItem" class="mt-3 space-y-3 text-xs overflow-y-auto">
            <!-- Name & Category -->
            <div class="bg-slate-950 p-2.5 rounded border border-slate-800 space-y-1">
              <div class="text-[10px] text-slate-500 uppercase tracking-wider">符号 / 段名称</div>
              <div class="font-bold text-white text-sm break-all font-mono">
                {{ selectedItem.name }}
              </div>
              <div v-if="selectedItem.category" class="pt-1">
                <span
                  class="text-[10px] px-2 py-0.5 rounded border font-mono font-semibold"
                  :class="getCategoryColor(selectedItem.category).badge"
                >
                  {{ selectedItem.category }}
                </span>
              </div>
            </div>

            <!-- Size & Percent -->
            <div class="bg-slate-950 p-2.5 rounded border border-slate-800 space-y-2 font-mono">
              <div class="flex justify-between items-center">
                <span class="text-slate-400 font-sans">占用大小:</span>
                <span class="font-bold text-cyan-400 text-sm">{{ selectedItem.size_str }}</span>
              </div>
              <div class="flex justify-between items-center text-[11px]">
                <span class="text-slate-500 font-sans">字节数:</span>
                <span class="text-slate-300">{{ selectedItem.size.toLocaleString() }} Bytes</span>
              </div>
              <div v-if="selectedItem.percent" class="flex justify-between items-center text-[11px]">
                <span class="text-slate-500 font-sans">总占比:</span>
                <span class="text-amber-400 font-semibold">{{ selectedItem.percent }}%</span>
              </div>
            </div>

            <!-- Address / Range -->
            <div v-if="selectedItem.address || selectedItem.start" class="bg-slate-950 p-2.5 rounded border border-slate-800 space-y-1.5 font-mono text-[11px]">
              <div v-if="selectedItem.address" class="flex justify-between">
                <span class="text-slate-500 font-sans">物理地址 (VMA):</span>
                <span class="text-slate-200">{{ selectedItem.address }}</span>
              </div>
              <div v-if="selectedItem.start" class="flex justify-between">
                <span class="text-slate-500 font-sans">起始地址:</span>
                <span class="text-slate-200">{{ selectedItem.start }}</span>
              </div>
              <div v-if="selectedItem.end" class="flex justify-between">
                <span class="text-slate-500 font-sans">终止地址:</span>
                <span class="text-slate-200">{{ selectedItem.end }}</span>
              </div>
            </div>

            <!-- Object / Library Info -->
            <div v-if="selectedItem.object || selectedItem.library" class="bg-slate-950 p-2.5 rounded border border-slate-800 space-y-1.5 text-[11px]">
              <div v-if="selectedItem.object">
                <div class="text-slate-500 text-[10px]">所属目标文件 (Object):</div>
                <div class="font-mono text-slate-200 break-all">{{ selectedItem.object }}</div>
              </div>
              <div v-if="selectedItem.library">
                <div class="text-slate-500 text-[10px]">所属静态库 (Library):</div>
                <div class="font-mono text-slate-200 break-all">{{ selectedItem.library }}</div>
              </div>
            </div>
          </div>

          <div v-else class="flex-1 flex flex-col items-center justify-center text-slate-500 text-center p-4">
            <LayoutGrid class="w-8 h-8 text-slate-700 mb-2" />
            <p>在左侧树图或中间矩阵树图中点击任意代码块查看深入属性。</p>
          </div>
        </div>
      </div>

      <!-- Tab Content 2: Modules Breakdown Table (Preserved existing rich table with sorting, search, symbol expansion) -->
      <div v-if="activeSubTab === 'modules'" class="flex-1 bg-slate-900 border border-slate-800 rounded-lg overflow-hidden flex flex-col shadow-sm">
        <div class="overflow-x-auto flex-1">
          <table class="w-full text-left border-collapse text-xs">
            <thead>
              <tr class="bg-slate-950/80 border-b border-slate-800 text-slate-400 text-[11px] select-none font-medium">
                <th class="p-2.5 w-10 text-center">#</th>
                <th class="p-2.5 cursor-pointer hover:text-slate-200" @click="sortField = 'name'; sortAsc = !sortAsc">
                  <div class="flex items-center gap-1">
                    <span>模块源文件名 (Module / File)</span>
                    <ArrowUpDown class="w-3 h-3 text-slate-500" />
                  </div>
                </th>
                <th class="p-2.5 cursor-pointer hover:text-slate-200" @click="sortField = 'rom_total'; sortAsc = !sortAsc">
                  <div class="flex items-center gap-1 justify-end">
                    <span>ROM 总计</span>
                    <ArrowUpDown class="w-3 h-3 text-cyan-400" />
                  </div>
                </th>
                <th class="p-2.5 cursor-pointer hover:text-slate-200" @click="sortField = 'code'; sortAsc = !sortAsc">
                  <div class="flex items-center gap-1 justify-end">
                    <span>Code (代码)</span>
                    <ArrowUpDown class="w-3 h-3 text-slate-500" />
                  </div>
                </th>
                <th class="p-2.5 text-right">RO-Data</th>
                <th class="p-2.5 cursor-pointer hover:text-slate-200" @click="sortField = 'ram_total'; sortAsc = !sortAsc">
                  <div class="flex items-center gap-1 justify-end">
                    <span>RAM 总计</span>
                    <ArrowUpDown class="w-3 h-3 text-emerald-400" />
                  </div>
                </th>
                <th class="p-2.5 text-right">RW-Data</th>
                <th class="p-2.5 cursor-pointer hover:text-slate-200" @click="sortField = 'zi_data'; sortAsc = !sortAsc">
                  <div class="flex items-center gap-1 justify-end">
                    <span>ZI-Data (BSS)</span>
                    <ArrowUpDown class="w-3 h-3 text-slate-500" />
                  </div>
                </th>
                <th class="p-2.5 text-center w-24">函数/变量数</th>
                <th class="p-2.5 text-center w-20">操作</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60 font-mono">
              <template v-for="(mod, index) in filteredModules" :key="mod.name">
                <tr
                  class="hover:bg-slate-800/40 transition-colors group cursor-pointer"
                  @click="toggleExpandModule(mod.name)"
                >
                  <td class="p-2.5 text-center text-slate-500 text-[11px]">{{ index + 1 }}</td>
                  <td class="p-2.5">
                    <div class="flex items-center gap-1.5">
                      <component
                        :is="expandedModules.has(mod.name) ? ChevronDown : ChevronRight"
                        class="w-3.5 h-3.5 text-slate-500 group-hover:text-emerald-400 transition-colors shrink-0"
                      />
                      <span class="font-semibold text-slate-200 group-hover:text-emerald-300 transition-colors">
                        {{ mod.name }}
                      </span>
                    </div>
                    <div class="text-[10px] text-slate-500 truncate max-w-sm pl-5 font-normal" :title="mod.full_path">
                      {{ mod.full_path }}
                    </div>
                  </td>
                  <td class="p-2.5 text-right">
                    <div class="font-bold text-cyan-400">{{ mod.rom_total_str }}</div>
                    <div class="text-[10px] text-slate-500">{{ mod.rom_percent }}%</div>
                  </td>
                  <td class="p-2.5 text-right text-slate-300">{{ mod.code_str }}</td>
                  <td class="p-2.5 text-right text-amber-300/90">{{ mod.ro_data_str }}</td>
                  <td class="p-2.5 text-right">
                    <div class="font-bold text-emerald-400">{{ mod.ram_total_str }}</div>
                    <div class="text-[10px] text-slate-500">{{ mod.ram_percent }}%</div>
                  </td>
                  <td class="p-2.5 text-right text-purple-300/90">{{ mod.rw_data_str }}</td>
                  <td class="p-2.5 text-right text-emerald-300/90">{{ mod.zi_data_str }}</td>
                  <td class="p-2.5 text-center text-slate-400">{{ mod.symbols_count }}</td>
                  <td class="p-2.5 text-center" @click.stop>
                    <button
                      @click="toggleExpandModule(mod.name)"
                      class="px-2 py-0.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 text-[11px] transition-colors"
                    >
                      {{ expandedModules.has(mod.name) ? '收起' : '明细' }}
                    </button>
                  </td>
                </tr>

                <!-- Expanded Symbols List -->
                <tr v-if="expandedModules.has(mod.name)" class="bg-slate-950/90">
                  <td colspan="10" class="p-3 pl-10">
                    <div class="bg-slate-900 border border-slate-800 rounded p-3 space-y-2">
                      <div class="flex items-center justify-between text-[11px] border-b border-slate-800 pb-1.5">
                        <span class="font-semibold text-slate-300">
                          📦 模块符号明细: {{ mod.name }} (共 {{ mod.symbols.length }} 个符号)
                        </span>
                        <span class="text-slate-500 font-mono text-[10px]">
                          源路径: {{ mod.full_path }}
                        </span>
                      </div>

                      <div v-if="mod.symbols.length === 0" class="text-slate-500 py-2 text-center text-xs">
                        该模块没有符号映射或由汇编静态分配
                      </div>

                      <div v-else class="max-h-60 overflow-y-auto pr-1">
                        <table class="w-full text-left border-collapse text-[11px] font-mono">
                          <thead>
                            <tr class="text-slate-500 border-b border-slate-800">
                              <th class="py-1">符号名称 (Symbol Name)</th>
                              <th class="py-1 w-24">类型</th>
                              <th class="py-1 w-24">内存分类</th>
                              <th class="py-1 w-28 text-right">物理地址</th>
                              <th class="py-1 w-24 text-right">占用大小</th>
                            </tr>
                          </thead>
                          <tbody class="divide-y divide-slate-800/60">
                            <tr v-for="sym in mod.symbols" :key="sym.name" class="hover:bg-slate-800/40">
                              <td class="py-1 text-slate-300 font-medium truncate max-w-xs" :title="sym.name">
                                {{ sym.name }}
                              </td>
                              <td class="py-1">
                                <span
                                  class="px-1.5 py-0.5 rounded text-[10px]"
                                  :class="sym.kind === 'func' ? 'bg-blue-900/40 text-blue-300' : 'bg-purple-900/40 text-purple-300'"
                                >
                                  {{ sym.kind === 'func' ? '函数 (Func)' : '对象 (Object)' }}
                                </span>
                              </td>
                              <td class="py-1">
                                <span
                                  class="px-1.5 py-0.5 rounded text-[10px]"
                                  :class="
                                    sym.category === 'Code' ? 'bg-blue-950 text-blue-400' :
                                    sym.category === 'RO-Data' ? 'bg-amber-950 text-amber-400' :
                                    sym.category === 'RW-Data' ? 'bg-purple-950 text-purple-400' :
                                    'bg-emerald-950 text-emerald-400'
                                  "
                                >
                                  {{ sym.category }}
                                </span>
                              </td>
                              <td class="py-1 text-right text-slate-400">{{ sym.address }}</td>
                              <td class="py-1 text-right font-semibold" :class="sym.size > 1024 ? 'text-cyan-400' : 'text-slate-300'">
                                {{ sym.size_str }}
                              </td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Tab Content 3: Raw ELF Sections Table (Preserved) -->
      <div v-if="activeSubTab === 'sections'" class="flex-1 bg-slate-900 border border-slate-800 rounded-lg overflow-hidden flex flex-col shadow-sm">
        <div class="overflow-x-auto flex-1">
          <table class="w-full text-left border-collapse text-xs font-mono">
            <thead>
              <tr class="bg-slate-950/80 border-b border-slate-800 text-slate-400 text-[11px] font-medium">
                <th class="p-2.5 w-10 text-center">#</th>
                <th class="p-2.5">段名称 (Section Name)</th>
                <th class="p-2.5">ELF 类型 (Type)</th>
                <th class="p-2.5">标志位 (Flags)</th>
                <th class="p-2.5 text-right">加载基地址 (Address)</th>
                <th class="p-2.5 text-right">段大小 (Size)</th>
                <th class="p-2.5 text-center">存储目标</th>
                <th class="p-2.5 text-center">归类属性</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-slate-800/60">
              <tr
                v-for="(sec, idx) in analysisData.sections"
                :key="sec.name + idx"
                class="hover:bg-slate-800/40 transition-colors"
              >
                <td class="p-2.5 text-center text-slate-500 text-[11px]">{{ idx + 1 }}</td>
                <td class="p-2.5 font-bold text-slate-200">{{ sec.name }}</td>
                <td class="p-2.5 text-slate-400 text-[11px]">{{ sec.type }}</td>
                <td class="p-2.5 text-slate-400 font-mono">{{ sec.flags }}</td>
                <td class="p-2.5 text-right text-slate-300">{{ sec.address }}</td>
                <td class="p-2.5 text-right font-semibold" :class="sec.size > 4096 ? 'text-cyan-400' : 'text-slate-200'">
                  {{ sec.size_str }}
                </td>
                <td class="p-2.5 text-center">
                  <span
                    class="px-2 py-0.5 rounded text-[10px] font-sans font-medium"
                    :class="
                      sec.target === 'ROM' ? 'bg-cyan-950 border border-cyan-800 text-cyan-300' :
                      sec.target === 'RAM' ? 'bg-emerald-950 border border-emerald-800 text-emerald-300' :
                      sec.target === 'ROM+RAM' ? 'bg-purple-950 border border-purple-800 text-purple-300' :
                      'bg-slate-800 text-slate-400'
                    "
                  >
                    {{ sec.target }}
                  </span>
                </td>
                <td class="p-2.5 text-center">
                  <span
                    class="px-2 py-0.5 rounded text-[10px] font-sans font-medium"
                    :class="
                      sec.category === 'Code' ? 'bg-blue-950 text-blue-300' :
                      sec.category === 'RO-Data' ? 'bg-amber-950 text-amber-300' :
                      sec.category === 'RW-Data' ? 'bg-purple-950 text-purple-300' :
                      sec.category === 'ZI-Data' ? 'bg-emerald-950 text-emerald-300' :
                      'bg-slate-800 text-slate-400'
                    "
                  >
                    {{ sec.category }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- Empty State / Guide when no file analyzed yet -->
    <div
      v-else-if="!isAnalyzing"
      class="flex-1 bg-slate-900 border border-slate-800 border-dashed rounded-lg p-8 flex flex-col items-center justify-center text-center space-y-4"
    >
      <div class="w-16 h-16 rounded-full bg-slate-800 flex items-center justify-center text-emerald-400 shadow-inner">
        <PieChart class="w-8 h-8" />
      </div>
      <div class="space-y-1 max-w-md">
        <div class="font-semibold text-slate-200 text-sm">选择并分析固件或 Keil Linker MAP 映射</div>
        <p class="text-slate-400 text-xs">
          全面支持加载 Keil MDK (ARMCC / ARMClang) 导出的 <code class="text-emerald-400 bg-slate-800 px-1 py-0.5 rounded">*.map</code> 文件以及 ELF/AXF 目标文件。自动计算 Treemap 树图矩阵、物理线性内存分布以及最大函数/变量排行。
        </p>
      </div>
      <button
        @click="handlePickFile"
        class="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded font-medium text-xs flex items-center gap-2 shadow-md transition-colors"
      >
        <FolderOpen class="w-4 h-4" />
        <span>点击浏览选择本地 .map / .axf / .elf 文件</span>
      </button>
      <div class="grid grid-cols-1 md:grid-cols-2 gap-3 text-left max-w-lg w-full pt-2">
        <div class="bg-slate-950/80 p-3 rounded border border-slate-800 space-y-1">
          <div class="font-semibold text-cyan-400 text-[11px] flex items-center gap-1.5">
            <HardDrive class="w-3.5 h-3.5" />
            <span>ROM (Flash) 开销计算规则</span>
          </div>
          <p class="text-slate-400 text-[10px] font-mono leading-relaxed">
            ROM = Code + RO-Data + RW-Data<br />
            (包含机器代码指令、只读静态常量及数据初始化烧录镜像)
          </p>
        </div>
        <div class="bg-slate-950/80 p-3 rounded border border-slate-800 space-y-1">
          <div class="font-semibold text-emerald-400 text-[11px] flex items-center gap-1.5">
            <Layers class="w-3.5 h-3.5" />
            <span>RAM (SRAM) 开销计算规则</span>
          </div>
          <p class="text-slate-400 text-[10px] font-mono leading-relaxed">
            RAM = RW-Data + ZI-Data (BSS)<br />
            (包含可读写变量及上电时需由启动汇编清零的未初始化静态内存)
          </p>
        </div>
      </div>
    </div>
  </div>
</template>
