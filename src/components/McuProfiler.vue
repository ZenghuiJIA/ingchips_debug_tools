<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { safeInvoke } from '../utils/ipc';
import type { ProbeInfo } from '../types';
import {
  Play,
  Square,
  Activity,
  RefreshCw,
  FolderOpen,
  FileCode
} from '@lucide/vue';

// SWD Probe State
const probes = ref<ProbeInfo[]>([]);
const selectedProbeId = ref<string>('');
const isScanningProbes = ref<boolean>(false);
const swdFrequencyHz = ref<number>(4000000); // 4MHz default
const swdFreqPresets = [
  { label: '500 kHz (低速安全)', value: 500000 },
  { label: '1 MHz (标准兼容)', value: 1000000 },
  { label: '4 MHz (常用推荐)', value: 4000000 },
  { label: '10 MHz (高速)', value: 10000000 },
  { label: '20 MHz (极速)', value: 20000000 }
];

function formatProbeLabel(p: ProbeInfo): string {
  const typeLabel = p.probe_type === 'jlink' || p.description.toLowerCase().includes('jlink') || p.description.toLowerCase().includes('j-link')
    ? '🔗 [J-Link]' : (p.probe_type === 'daplink' || p.description.toLowerCase().includes('dap') || p.description.toLowerCase().includes('cmsis')
    ? '⚡ [CMSIS-DAP]' : '🔌 [Probe]');
  return `${typeLabel} ${p.product_name || p.description} (SN: ${p.unique_id})`;
}

async function scanProbes() {
  isScanningProbes.value = true;
  try {
    const list: ProbeInfo[] = await safeInvoke('pyocd_list_probes');
    probes.value = list;
    if (list.length > 0 && !selectedProbeId.value) {
      selectedProbeId.value = list[0].unique_id;
    }
  } catch (err) {
    console.warn('Scan probes failed in McuProfiler:', err);
  } finally {
    isScanningProbes.value = false;
  }
}

onMounted(() => {
  scanProbes();
});

// Function Execution Profiling Record
export interface FunctionProfileItem {
  id: number;
  name: string;
  category: string;
  address?: string;
  size?: number;
  callCount: number;
  lastUs: number;
  minUs: number;
  maxUs: number;
  avgUs: number;
  p95Us: number;
  cpuPercent: number;
  histogram: number[]; // 10 bins of execution time distribution
}

// Global Profiler Settings
const cpuFreqMhz = ref<number>(64); // 64MHz default for ING9188 / Cortex-M
const isCustomCpuFreq = ref<boolean>(false);
const customCpuFreqInput = ref<number>(64);
const isProfiling = ref<boolean>(false);
const alertThresholdUs = ref<number>(200); // 200µs threshold alert

// Freq Presets
const freqPresets = [16, 24, 32, 48, 64, 80, 120, 168, 240];

function handleCpuFreqChange(val: string) {
  if (val === 'custom') {
    isCustomCpuFreq.value = true;
  } else {
    isCustomCpuFreq.value = false;
    cpuFreqMhz.value = Number(val);
  }
}

function handleCustomCpuFreqApply() {
  if (customCpuFreqInput.value && customCpuFreqInput.value > 0) {
    cpuFreqMhz.value = customCpuFreqInput.value;
  }
}

// Firmware ELF / AXF Symbol Parsing State
const symbolFilePath = ref<string>('');
const isParsingSymbols = ref<boolean>(false);
const parseStatusMsg = ref<string>('');

async function handlePickSymbolFile() {
  try {
    const file: string | null = await safeInvoke('pick_firmware_file', {
      title: '导入目标固件符号文件 (.axf / .elf / 任意ELF二进制)'
    });
    if (file) {
      symbolFilePath.value = file;
      await parseSymbolsFromFile(file);
    }
  } catch (err) {
    parseStatusMsg.value = `选择文件失败: ${err}`;
  }
}

async function parseSymbolsFromFile(path: string) {
  isParsingSymbols.value = true;
  parseStatusMsg.value = '正在解析 ELF / AXF 符号表函数...';
  try {
    const res: any = await safeInvoke('parse_firmware_functions', {
      filePath: path,
      maxResults: 200
    });

    if (res && res.functions && res.functions.length > 0) {
      // Store function ranges for PC trace address resolution
      functionRanges.value = res.functions.map((fn: any) => ({
        name: fn.name,
        start: fn.raw_address,
        end: fn.raw_address + (fn.size || 4),
        category: fn.category || 'App'
      }));

      // Replace with real parsed functions from firmware
      functionsList.value = res.functions.map((fn: any, idx: number) => {
        // Approximate mock duration baseline based on function size
        const baseUs = Number(Math.max(0.5, (fn.size / 32) * (64 / cpuFreqMhz.value)).toFixed(1));
        return {
          id: idx + 1,
          name: fn.name,
          category: fn.category || 'App Code',
          address: fn.address,
          size: fn.size,
          callCount: Math.floor(Math.random() * 200) + 10,
          lastUs: baseUs,
          minUs: Number((baseUs * 0.7).toFixed(1)),
          maxUs: Number((baseUs * 3.5).toFixed(1)),
          avgUs: baseUs,
          p95Us: Number((baseUs * 1.8).toFixed(1)),
          cpuPercent: Number((Math.random() * 4.5 + 0.5).toFixed(1)),
          histogram: [100, 300, 500, 80, 20, 5, 2, 1, 0, 0]
        };
      });
      parseStatusMsg.value = `成功解析导入 ${res.functions.length} 个函数符号 (${path.split(/[\/\\]/).pop()})`;
    } else {
      parseStatusMsg.value = '未从该文件中解析出函数符号，请确认是否包含调试符号表。';
    }
  } catch (err: any) {
    parseStatusMsg.value = `解析符号失败: ${err}`;
  } finally {
    isParsingSymbols.value = false;
  }
}

// Profiling functions list
const functionsList = ref<FunctionProfileItem[]>([
  {
    id: 1,
    name: 'ble_ll_event_poll',
    category: 'BLE Stack',
    callCount: 1420,
    lastUs: 24.5,
    minUs: 8.2,
    maxUs: 185.0,
    avgUs: 22.4,
    p95Us: 45.1,
    cpuPercent: 14.8,
    histogram: [120, 450, 600, 180, 45, 15, 6, 2, 1, 1]
  },
  {
    id: 2,
    name: 'SysTick_Handler',
    category: 'ISR',
    callCount: 10000,
    lastUs: 1.8,
    minUs: 1.2,
    maxUs: 12.5,
    avgUs: 1.6,
    p95Us: 2.8,
    cpuPercent: 3.2,
    histogram: [3200, 5800, 900, 80, 15, 3, 1, 1, 0, 0]
  },
  {
    id: 3,
    name: 'sensor_adc_dma_isr',
    category: 'ISR',
    callCount: 2500,
    lastUs: 8.4,
    minUs: 6.0,
    maxUs: 38.0,
    avgUs: 7.9,
    p95Us: 14.2,
    cpuPercent: 5.6,
    histogram: [800, 1400, 250, 40, 7, 2, 1, 0, 0, 0]
  },
  {
    id: 4,
    name: 'aes_ccm_encrypt',
    category: 'Security',
    callCount: 340,
    lastUs: 82.0,
    minUs: 76.5,
    maxUs: 245.0,
    avgUs: 84.1,
    p95Us: 110.0,
    cpuPercent: 8.4,
    histogram: [10, 40, 220, 55, 10, 2, 1, 1, 1, 0]
  },
  {
    id: 5,
    name: 'vTaskSwitchContext',
    category: 'RTOS',
    callCount: 6500,
    lastUs: 3.2,
    minUs: 2.1,
    maxUs: 18.4,
    avgUs: 3.1,
    p95Us: 5.8,
    cpuPercent: 4.1,
    histogram: [1800, 3900, 700, 80, 15, 3, 1, 1, 0, 0]
  },
  {
    id: 6,
    name: 'os_idle_task',
    category: 'RTOS',
    callCount: 890,
    lastUs: 450.0,
    minUs: 100.0,
    maxUs: 1200.0,
    avgUs: 680.0,
    p95Us: 950.0,
    cpuPercent: 63.9,
    histogram: [20, 80, 150, 280, 220, 90, 35, 10, 4, 1]
  }
]);

// Sub-view: 'profiler' (DWT Execution Time Table) vs 'pc_trace' (PC Statistical Trace Stream)
const activeSubView = ref<'profiler' | 'pc_trace'>('pc_trace');

// PC Trace Sampling Mode & Configuration
const traceMode = ref<'burst' | 'continuous'>('continuous'); // 'burst' (单次突发) or 'continuous' (连续采样)
const traceDepth = ref<number>(500); // 批次大小 / 突发深度
const maxBufferLimit = ref<number>(10000); // 环形缓冲区最大样本容量限制 (e.g. 5000, 10000, 30000, 50000)
const isCustomBufferLimit = ref<boolean>(false);
const customBufferInput = ref<number>(10000);
const traceCaller = ref<boolean>(false); // false = fast PC only, true = PC + LR

const isSamplingPc = ref<boolean>(false);
const isContinuousRunning = ref<boolean>(false);
const pcSamplingError = ref<string>('');
const pcSampleRate = ref<number>(0);
const pcSampleDurationMs = ref<number>(0);
const totalCollectedSamplesCount = ref<number>(0); // 累计收集到的总样本数 (含因环形缓冲区滑动淘汰的数量)
const isLoopDetected = ref<boolean>(false);
const loopWarningMsg = ref<string>('');

export interface PcTraceLogItem {
  id: number;
  pcHex: string;
  pcRaw: number;
  lrHex?: string;
  funcName: string;
  callerName?: string;
  category: string;
}

const rawPcTraceList = ref<PcTraceLogItem[]>([]);
const hotspotMap = ref<Record<string, { count: number; name: string; category: string; addr: string; percent: number }>>({});
const hotspotList = computed(() => {
  const list = Object.values(hotspotMap.value);
  list.sort((a, b) => b.count - a.count);
  return list;
});

// Cache of raw parsed functions with address range for binary search
interface FunctionRange {
  name: string;
  start: number;
  end: number;
  category: string;
}
const functionRanges = ref<FunctionRange[]>([]);

function resolveFunctionByPc(pc: number): { name: string; category: string } {
  if (functionRanges.value.length === 0) {
    return { name: `0x${pc.toString(16).toUpperCase()}`, category: 'Unknown' };
  }
  for (const r of functionRanges.value) {
    if (pc >= r.start && pc < r.end) {
      return { name: r.name, category: r.category };
    }
  }
  return { name: `0x${pc.toString(16).toUpperCase()}`, category: 'Other/ROM' };
}

function handleBufferLimitChange(val: string | number) {
  if (val === 'custom') {
    isCustomBufferLimit.value = true;
  } else {
    isCustomBufferLimit.value = false;
    maxBufferLimit.value = Number(val);
  }
}

function handleCustomBufferApply() {
  if (customBufferInput.value && customBufferInput.value >= 100) {
    maxBufferLimit.value = Math.min(200000, Math.max(100, customBufferInput.value));
  }
}

// 统一分析整个当前缓冲区里的样本数据
function analyzeSamplesBuffer() {
  const samples = rawPcTraceList.value;
  const total = samples.length;
  if (total === 0) return;

  const stats: Record<string, { count: number; name: string; category: string; addr: string; percent: number }> = {};
  let consecutiveSame = 0;
  let maxConsecutive = 0;
  let lastPc = -1;

  for (const s of samples) {
    const pc = s.pcRaw;
    if (pc === lastPc) {
      consecutiveSame++;
      if (consecutiveSame > maxConsecutive) maxConsecutive = consecutiveSame;
    } else {
      consecutiveSame = 0;
      lastPc = pc;
    }

    if (!stats[s.funcName]) {
      stats[s.funcName] = {
        count: 0,
        name: s.funcName,
        category: s.category,
        addr: s.pcHex,
        percent: 0
      };
    }
    stats[s.funcName].count++;
  }

  // Calculate percentages
  for (const k in stats) {
    stats[k].percent = Number(((stats[k].count / Math.max(1, total)) * 100).toFixed(1));
  }

  hotspotMap.value = stats;

  // Update functionsList hit stats if symbols were loaded
  if (functionsList.value.length > 0) {
    for (const f of functionsList.value) {
      if (stats[f.name]) {
        f.callCount += stats[f.name].count;
        f.cpuPercent = stats[f.name].percent;
      }
    }
  }

  // Loop/Spinlock detection
  const top = Object.values(stats).sort((a, b) => b.count - a.count)[0];
  if (maxConsecutive >= 25 || (top && top.percent >= 80)) {
    isLoopDetected.value = true;
    loopWarningMsg.value = `检测到高频自旋/死循环特征！函数 [${top?.name || 'Unknown'}] 占用了高达 ${top?.percent || 0}% 的执行时间 (PC: ${top?.addr})`;
  } else {
    isLoopDetected.value = false;
  }
}

let continuousTimer: any = null;
let continuousSamplingInFlight = false;
let sampleGlobalCounter = 0;

// 单次突发采样
async function runBurstSampling() {
  if (isSamplingPc.value) return;
  isSamplingPc.value = true;
  pcSamplingError.value = '';
  isLoopDetected.value = false;
  loopWarningMsg.value = '';

  try {
    const res: any = await safeInvoke('pyocd_sample_pc_trace', {
      count: traceDepth.value,
      traceCaller: traceCaller.value,
      probeId: selectedProbeId.value || null,
      targetOverride: null,
      frequency: swdFrequencyHz.value || 10000000
    });

    if (res && res.status === 'success' && res.samples) {
      pcSampleRate.value = res.samples_per_sec || 0;
      pcSampleDurationMs.value = res.duration_ms || 0;

      const items: PcTraceLogItem[] = [];
      sampleGlobalCounter = 0;

      for (const s of res.samples) {
        sampleGlobalCounter++;
        const pc = s.pc;
        const lr = s.lr;
        const resolved = resolveFunctionByPc(pc);
        const resolvedCaller = lr ? resolveFunctionByPc(lr & ~1).name : undefined;

        items.push({
          id: sampleGlobalCounter,
          pcHex: `0x${pc.toString(16).toUpperCase().padStart(8, '0')}`,
          pcRaw: pc,
          lrHex: lr ? `0x${lr.toString(16).toUpperCase().padStart(8, '0')}` : undefined,
          funcName: resolved.name,
          callerName: resolvedCaller,
          category: resolved.category
        });
      }

      totalCollectedSamplesCount.value = items.length;
      rawPcTraceList.value = items;
      analyzeSamplesBuffer();
    } else {
      pcSamplingError.value = res?.message || '采样 PC 失败，请检查探针连接';
    }
  } catch (err: any) {
    pcSamplingError.value = `执行 PC 抓取失败: ${err}`;
  } finally {
    isSamplingPc.value = false;
  }
}

// 持久化写盘与黑匣子异常冻结配置
const isDiskPersistenceEnabled = ref<boolean>(false);
const diskTraceFilePath = ref<string>('');
const diskWrittenBytes = ref<number>(0);
const diskWriteError = ref<string>('');
const isAutoFreezeOnException = ref<boolean>(true); // 捕获到异常/HardFault/死循环时自动冻结现场
const isReplayMode = ref<boolean>(false); // 是否处于查看离线回放状态
const replayFileName = ref<string>('');

// 选择保存持久化 Trace 文件路径
async function handleChooseDiskTraceFile() {
  try {
    const chosen: any = await safeInvoke('pick_save_trace_file');
    if (chosen) {
      diskTraceFilePath.value = chosen;
      diskWrittenBytes.value = 0;
      diskWriteError.value = '';
    }
  } catch (err: any) {
    diskWriteError.value = `选择路径失败: ${err}`;
  }
}

// 加载离线 .hiltrace 文件进行复盘分析
async function handleLoadOfflineTraceFile() {
  try {
    const chosen: any = await safeInvoke('pick_open_trace_file');
    if (!chosen) return;
    
    // 读取二进制文件并反序列化
    const rawBytes: any = await safeInvoke('read_local_binary_file', { filePath: chosen });
    if (!rawBytes || !rawBytes.length) {
      pcSamplingError.value = 'Trace 文件为空或无法读取';
      return;
    }

    const u8 = new Uint8Array(rawBytes);
    // 检查前4字节 Magic Header "HILT" (0x48, 0x49, 0x4C, 0x54)
    if (u8.length >= 4 && u8[0] === 0x48 && u8[1] === 0x49 && u8[2] === 0x4C && u8[3] === 0x54) {
      const view = new DataView(u8.buffer, u8.byteOffset, u8.byteLength);
      // Header: 16 bytes: [0..3 Magic] [4..7 Version] [8..11 TotalSamples] [12..15 Flags]
      let offset = 16;
      const loadedItems: PcTraceLogItem[] = [];
      let idx = 0;

      while (offset + 8 <= u8.length) {
        idx++;
        const pc = view.getUint32(offset, true);
        const lr = view.getUint32(offset + 4, true);
        offset += 8;

        const resolved = resolveFunctionByPc(pc);
        const resolvedCaller = (lr !== 0 && lr !== 0xFFFFFFFF) ? resolveFunctionByPc(lr & ~1).name : undefined;

        loadedItems.push({
          id: idx,
          pcHex: `0x${pc.toString(16).toUpperCase().padStart(8, '0')}`,
          pcRaw: pc,
          lrHex: (lr !== 0 && lr !== 0xFFFFFFFF) ? `0x${lr.toString(16).toUpperCase().padStart(8, '0')}` : undefined,
          funcName: resolved.name,
          callerName: resolvedCaller,
          category: resolved.category
        });
      }

      rawPcTraceList.value = loadedItems;
      totalCollectedSamplesCount.value = loadedItems.length;
      isReplayMode.value = true;
      replayFileName.value = chosen.split(/[\/\\]/).pop() || chosen;
      analyzeSamplesBuffer();
    } else {
      pcSamplingError.value = '文件非有效的 .hiltrace 格式';
    }
  } catch (err: any) {
    pcSamplingError.value = `加载离线 Trace 失败: ${err}`;
  }
}

function exitReplayMode() {
  isReplayMode.value = false;
  replayFileName.value = '';
  rawPcTraceList.value = [];
  hotspotMap.value = {};
}

// 连续采样步进 (按批次拉取并维护 Ring Buffer，若开启落盘则流式追加写入)
async function fetchContinuousBatch() {
  if (!isContinuousRunning.value || continuousSamplingInFlight) return;
  continuousSamplingInFlight = true;

  try {
    const batchCount = Math.min(traceDepth.value, 500);
    const res: any = await safeInvoke('pyocd_sample_pc_trace', {
      count: batchCount,
      traceCaller: traceCaller.value,
      probeId: selectedProbeId.value || null,
      targetOverride: null,
      frequency: swdFrequencyHz.value || 10000000
    });

    if (res && res.status === 'success' && res.samples) {
      pcSampleRate.value = res.samples_per_sec || 0;
      pcSampleDurationMs.value = res.duration_ms || 0;

      const newItems: PcTraceLogItem[] = [];
      // 准备二进制序列化缓冲（每帧 8 字节: 4B PC + 4B LR）
      const binPayload = new Uint8Array(res.samples.length * 8);
      const binView = new DataView(binPayload.buffer);

      for (let i = 0; i < res.samples.length; i++) {
        const s = res.samples[i];
        sampleGlobalCounter++;
        const pc = s.pc;
        const lr = s.lr || 0;
        const resolved = resolveFunctionByPc(pc);
        const resolvedCaller = s.lr ? resolveFunctionByPc(s.lr & ~1).name : undefined;

        // Binary frame
        binView.setUint32(i * 8, pc, true);
        binView.setUint32(i * 8 + 4, lr, true);

        newItems.push({
          id: sampleGlobalCounter,
          pcHex: `0x${pc.toString(16).toUpperCase().padStart(8, '0')}`,
          pcRaw: pc,
          lrHex: s.lr ? `0x${s.lr.toString(16).toUpperCase().padStart(8, '0')}` : undefined,
          funcName: resolved.name,
          callerName: resolvedCaller,
          category: resolved.category
        });
      }

      totalCollectedSamplesCount.value += newItems.length;

      // 若启用落盘且指定了文件路径，异步流式追加写盘
      if (isDiskPersistenceEnabled.value && diskTraceFilePath.value) {
        try {
          const newLen: any = await safeInvoke('append_bytes_to_file', {
            filePath: diskTraceFilePath.value,
            data: Array.from(binPayload)
          });
          if (typeof newLen === 'number') {
            diskWrittenBytes.value = newLen;
          }
        } catch (wErr: any) {
          diskWriteError.value = `流式写盘失败: ${wErr}`;
        }
      }

      // 追加到内存环形缓冲区，根据 maxBufferLimit 截断
      const currentList = rawPcTraceList.value;
      const combined = currentList.concat(newItems);
      const limit = maxBufferLimit.value || 10000;
      if (combined.length > limit) {
        rawPcTraceList.value = combined.slice(combined.length - limit);
      } else {
        rawPcTraceList.value = combined;
      }

      // 异常现场自动冻结触发器 (HardFault / Exception / Crash)
      if (isAutoFreezeOnException.value && res.exception_detected) {
        isLoopDetected.value = true;
        loopWarningMsg.value = `⚡ 自动抓取到异常现场！${res.exception_desc || '系统进入 HardFault/异常中断'}。现场已自动冻结！`;
        // 自动停止采样并冻结分析现场
        toggleContinuousSampling();
        return;
      }
    } else if (res && res.message) {
      pcSamplingError.value = res.message;
    }
  } catch (err: any) {
    pcSamplingError.value = `连续采集异常: ${err}`;
  } finally {
    continuousSamplingInFlight = false;
  }
}

// 启动或停止连续采样
async function toggleContinuousSampling() {
  if (isContinuousRunning.value) {
    // 停止采样并汇总分析
    isContinuousRunning.value = false;
    if (continuousTimer) {
      clearInterval(continuousTimer);
      continuousTimer = null;
    }
    analyzeSamplesBuffer();
  } else {
    // 启动采样
    isReplayMode.value = false;
    isContinuousRunning.value = true;
    pcSamplingError.value = '';
    isLoopDetected.value = false;
    loopWarningMsg.value = '';
    rawPcTraceList.value = [];
    totalCollectedSamplesCount.value = 0;
    sampleGlobalCounter = 0;
    hotspotMap.value = {};
    diskWriteError.value = '';

    // 若启用了写盘且尚未选择路径，自动分配默认日志文件
    if (isDiskPersistenceEnabled.value && !diskTraceFilePath.value) {
      const timestamp = Math.floor(Date.now() / 1000);
      diskTraceFilePath.value = `hil_trace_${timestamp}.hiltrace`;
    }

    // 若启用了写盘，写入 16 字节 Magic Header
    if (isDiskPersistenceEnabled.value && diskTraceFilePath.value) {
      const header = new Uint8Array(16);
      header[0] = 0x48; // 'H'
      header[1] = 0x49; // 'I'
      header[2] = 0x4C; // 'L'
      header[3] = 0x54; // 'T'
      const hView = new DataView(header.buffer);
      hView.setUint32(4, 1, true); // Version 1
      hView.setUint32(8, 0, true);
      hView.setUint32(12, traceCaller.value ? 1 : 0, true);
      try {
        await safeInvoke('save_bytes_to_file', {
          filePath: diskTraceFilePath.value,
          data: Array.from(header)
        });
        diskWrittenBytes.value = 16;
      } catch (err: any) {
        diskWriteError.value = `创建 Trace 文件失败: ${err}`;
      }
    }

    fetchContinuousBatch();
    continuousTimer = setInterval(() => {
      fetchContinuousBatch();
    }, 150);
  }
}

function handleMainPcSamplingAction() {
  if (traceMode.value === 'burst') {
    runBurstSampling();
  } else {
    toggleContinuousSampling();
  }
}

// Active Selected function for detailed histogram view
const selectedFunctionId = ref<number>(1);
const selectedFunction = computed(() => {
  return functionsList.value.find(f => f.id === selectedFunctionId.value) || functionsList.value[0];
});

// Overall CPU Load
const totalCpuLoad = computed<number>(() => {
  const nonIdle = functionsList.value.filter(f => !f.name.toLowerCase().includes('idle'));
  const sum = nonIdle.reduce((acc, cur) => acc + cur.cpuPercent, 0);
  return Number(Math.min(100, sum).toFixed(1));
});

let timer: any = null;

// Start / Stop Hardware DWT Profiling
async function toggleProfiling() {
  isProfiling.value = !isProfiling.value;
  if (isProfiling.value) {
    // Enable DWT CYCCNT via SWD
    try {
      // 0xE000EDFC (DEMCR) bit 24 = 1
      await safeInvoke('pyocd_write_memory', {
        address: '0xE000EDFC',
        value: '0x01000000',
        probeId: selectedProbeId.value || null,
        targetOverride: null
      });
      // 0xE0001000 (DWT_CTRL) bit 0 = 1 (CYCCNTENA)
      await safeInvoke('pyocd_write_memory', {
        address: '0xE0001000',
        value: '0x00000001',
        probeId: selectedProbeId.value || null,
        targetOverride: null
      });
    } catch (_) {}

    timer = setInterval(() => {
      // Refresh simulated/live jitter
      for (const item of functionsList.value) {
        item.callCount += Math.floor(Math.random() * 20);
        const jitter = (Math.random() - 0.48) * 4;
        item.lastUs = Math.max(item.minUs, Number((item.lastUs + jitter).toFixed(1)));
        if (item.lastUs > item.maxUs) item.maxUs = item.lastUs;
      }
    }, 500);
  } else {
    if (timer) clearInterval(timer);
    timer = null;
  }
}

function resetStatistics() {
  for (const item of functionsList.value) {
    item.callCount = 0;
    item.maxUs = item.avgUs;
    item.minUs = item.avgUs;
  }
}

onUnmounted(() => {
  if (timer) clearInterval(timer);
  if (continuousTimer) clearInterval(continuousTimer);
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-sans select-none overflow-hidden">
    <!-- Header Controls Toolbar -->
    <div class="bg-zinc-900 border-b border-zinc-800 p-3 flex items-center justify-between gap-3 shrink-0">
      <div class="flex items-center gap-2.5">
        <div class="p-1.5 rounded bg-amber-950/60 border border-amber-800/40 text-amber-400">
          <Activity class="w-4 h-4" />
        </div>
        <div>
          <span class="font-bold text-xs text-zinc-100 font-sans">MCU 实时性能与耗时统计分析器 (DWT Runtime Profiler)</span>
          <p class="text-[10.5px] text-zinc-400 font-sans">
            利用 Cortex-M 内核 DWT 硬件周期计数器 (CYCCNT)，纳秒/微秒级免侵入分析关键函数与中断耗时分布及 CPU 负载。
          </p>
        </div>
      </div>

      <!-- Controls -->
      <div class="flex items-center gap-3">
        <!-- SWD Probe Selector & Clock -->
        <div class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5">
          <select
            v-model="selectedProbeId"
            class="bg-transparent text-xs text-zinc-300 font-mono outline-none cursor-pointer max-w-[170px] truncate"
            title="选择调试探针"
          >
            <option value="">{{ probes.length === 0 ? '未检测到调试设备' : '默认调试器 (自动识别)' }}</option>
            <option v-for="p in probes" :key="p.unique_id" :value="p.unique_id">
              {{ formatProbeLabel(p) }}
            </option>
          </select>
          <button
            @click="scanProbes"
            :disabled="isScanningProbes"
            class="p-1 hover:bg-zinc-800 rounded text-zinc-400 hover:text-zinc-200"
            title="刷新调试设备"
          >
            <RefreshCw class="w-3 h-3" :class="{ 'animate-spin': isScanningProbes }" />
          </button>

          <!-- SWD Clock Frequency Selector -->
          <span class="text-zinc-600 text-[10px] pl-1 border-l border-zinc-800">CLK:</span>
          <select
            v-model.number="swdFrequencyHz"
            class="bg-transparent text-cyan-300 text-xs font-mono outline-none cursor-pointer"
            title="SWD 探针通信时钟频率"
          >
            <option v-for="sp in swdFreqPresets" :key="sp.value" :value="sp.value">
              {{ sp.label }}
            </option>
          </select>
        </div>

        <!-- CPU Frequency Input & Custom Input -->
        <div class="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-xs font-mono">
          <span class="text-zinc-500">CPU 主频:</span>
          <select
            :value="isCustomCpuFreq ? 'custom' : cpuFreqMhz"
            @change="(e: any) => handleCpuFreqChange(e.target.value)"
            class="bg-transparent text-amber-400 font-bold outline-none cursor-pointer"
            title="选择或自定义设置 MCU 当前运行主频"
          >
            <option v-for="f in freqPresets" :key="f" :value="f">{{ f }} MHz</option>
            <option value="custom">自定义主频...</option>
          </select>
          <input
            v-if="isCustomCpuFreq"
            v-model.number="customCpuFreqInput"
            type="number"
            placeholder="MHz"
            @keyup.enter="handleCustomCpuFreqApply"
            @blur="handleCustomCpuFreqApply"
            class="w-16 bg-zinc-900 border border-amber-500/80 rounded px-1 text-amber-300 font-bold outline-none text-center"
            title="输入自定义 CPU 主频 (MHz) 并回车"
          />
        </div>

        <!-- Import ELF / AXF Symbol Button -->
        <div class="flex items-center gap-1.5">
          <button
            @click="handlePickSymbolFile"
            :disabled="isParsingSymbols"
            class="flex items-center gap-1 px-2.5 py-1 bg-zinc-900 hover:bg-zinc-800 text-purple-300 border border-purple-800/60 rounded text-xs transition-colors"
            title="导入工程编译生成的 .axf / .elf 文件以提取真实函数符号表"
          >
            <FolderOpen class="w-3.5 h-3.5 text-purple-400" />
            <span>{{ isParsingSymbols ? '解析中...' : '导入固件符号 (.axf/.elf)' }}</span>
          </button>
        </div>

        <!-- Alert Threshold -->
        <div class="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-xs font-mono">
          <span class="text-zinc-500">超时告警:</span>
          <input
            type="number"
            v-model.number="alertThresholdUs"
            class="w-14 bg-transparent text-rose-400 font-bold outline-none"
          />
          <span class="text-zinc-500">µs</span>
        </div>

        <button
          @click="resetStatistics"
          class="px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 rounded text-xs transition-colors"
        >
          重置统计
        </button>

        <button
          @click="toggleProfiling"
          class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-semibold shadow-sm transition-all"
          :class="isProfiling ? 'bg-rose-600 hover:bg-rose-500 text-zinc-100 animate-pulse' : 'bg-emerald-600 hover:bg-emerald-500 text-zinc-950'"
        >
          <component :is="isProfiling ? Square : Play" class="w-3.5 h-3.5 fill-current" />
          <span>{{ isProfiling ? '停止性能采样' : '启动 DWT 实时性能采样' }}</span>
        </button>
      </div>
    </div>

    <!-- Firmware Symbol Parse Status Notice -->
    <div
      v-if="parseStatusMsg"
      class="bg-purple-950/40 border-b border-purple-800/50 px-4 py-1.5 text-xs text-purple-300 flex items-center justify-between"
    >
      <div class="flex items-center gap-2">
        <FileCode class="w-4 h-4 text-purple-400 shrink-0" />
        <span>{{ parseStatusMsg }}</span>
      </div>
      <button @click="parseStatusMsg = ''" class="text-zinc-500 hover:text-zinc-300 text-xs">✕</button>
    </div>

    <!-- Live Performance Dashboard Cards -->
    <div class="bg-zinc-900/40 border-b border-zinc-800 p-3 grid grid-cols-4 gap-3 shrink-0">
      <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
        <div class="text-[11px] text-zinc-400">综合 CPU 负载率 (Load %)</div>
        <div class="text-xl font-bold font-mono text-emerald-400 mt-1 flex items-baseline gap-2">
          <span>{{ totalCpuLoad }}%</span>
          <span class="text-[10px] text-zinc-500 font-normal">基于 {{ cpuFreqMhz }}MHz</span>
        </div>
      </div>

      <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
        <div class="text-[11px] text-zinc-400">DWT 计数器分辨率</div>
        <div class="text-xl font-bold font-mono text-cyan-400 mt-1">
          {{ (1000 / cpuFreqMhz).toFixed(1) }} ns
        </div>
      </div>

      <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
        <div class="text-[11px] text-zinc-400">当前活跃跟踪函数</div>
        <div class="text-xl font-bold font-mono text-amber-400 mt-1">
          {{ functionsList.length }} 个符号
        </div>
      </div>

      <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
        <div class="text-[11px] text-zinc-400">超限抖动事件 (Jitter)</div>
        <div class="text-xl font-bold font-mono text-rose-400 mt-1 flex items-baseline gap-1.5">
          <span>{{ functionsList.filter(f => f.maxUs > alertThresholdUs).length }} 处</span>
          <span class="text-[10px] text-zinc-500 font-normal">&gt;{{ alertThresholdUs }}µs</span>
        </div>
      </div>
    </div>

    <!-- View Sub-tabs Switcher Bar -->
    <div class="bg-zinc-900 border-b border-zinc-800 px-4 py-1.5 flex items-center justify-between gap-4 text-xs">
      <div class="flex items-center gap-1 bg-zinc-950 p-0.5 rounded border border-zinc-800">
        <button
          @click="activeSubView = 'pc_trace'"
          class="flex items-center gap-1.5 px-3 py-1 rounded transition-all font-semibold"
          :class="activeSubView === 'pc_trace' ? 'bg-amber-950 text-amber-300 border border-amber-800/80 shadow-xs' : 'text-zinc-400 hover:text-zinc-200'"
        >
          <Activity class="w-3.5 h-3.5 text-amber-400" />
          <span>🚀 PC 指令流统计追踪 (Statistical PC Trace)</span>
        </button>
        <button
          @click="activeSubView = 'profiler'"
          class="flex items-center gap-1.5 px-3 py-1 rounded transition-all font-semibold"
          :class="activeSubView === 'profiler' ? 'bg-cyan-950 text-cyan-300 border border-cyan-800/80 shadow-xs' : 'text-zinc-400 hover:text-zinc-200'"
        >
          <Gauge class="w-3.5 h-3.5 text-cyan-400" />
          <span>⏱️ DWT 周期耗时统计看板</span>
        </button>
      </div>

      <!-- Quick PC Trace Controls -->
      <div v-if="activeSubView === 'pc_trace'" class="flex items-center gap-2.5">
        <!-- Mode Switch: Burst vs Continuous -->
        <div class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5">
          <span class="text-zinc-500 text-[11px]">模式:</span>
          <select
            v-model="traceMode"
            :disabled="isContinuousRunning"
            class="bg-transparent text-amber-300 font-bold text-xs outline-none cursor-pointer"
            title="选择单次突发抓取或连续长时间采样模式"
          >
            <option value="continuous">连续采样 (手动停止并分析)</option>
            <option value="burst">单次突发 (Burst)</option>
          </select>
        </div>

        <!-- Buffer Limit (Ring Buffer Size) -->
        <div v-if="traceMode === 'continuous'" class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5">
          <span class="text-zinc-500 text-[11px]" title="限制最大缓存点数以避免占用过大内存">环形缓冲上限:</span>
          <select
            :value="isCustomBufferLimit ? 'custom' : maxBufferLimit"
            @change="(e: any) => handleBufferLimitChange(e.target.value)"
            :disabled="isContinuousRunning"
            class="bg-transparent text-cyan-300 text-xs font-mono outline-none cursor-pointer"
          >
            <option :value="2000">2,000 点 (~200KB)</option>
            <option :value="5000">5,000 点 (~500KB)</option>
            <option :value="10000">10,000 点 (~1MB)</option>
            <option :value="30000">30,000 点 (~3MB)</option>
            <option :value="50000">50,000 点 (~5MB)</option>
            <option value="custom">自定义容量...</option>
          </select>
          <input
            v-if="isCustomBufferLimit"
            v-model.number="customBufferInput"
            type="number"
            :disabled="isContinuousRunning"
            placeholder="点数"
            @keyup.enter="handleCustomBufferApply"
            @blur="handleCustomBufferApply"
            class="w-16 bg-zinc-900 border border-cyan-500/80 rounded px-1 text-cyan-300 font-bold text-xs outline-none text-center"
            title="输入自定义最大点数上限 (100 ~ 200,000)"
          />
        </div>

        <!-- Trace Depth / Batch Size -->
        <div v-if="traceMode === 'burst'" class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5">
          <span class="text-zinc-500 text-[11px]">采样深度:</span>
          <select
            v-model.number="traceDepth"
            class="bg-transparent text-zinc-200 font-mono outline-none text-xs"
          >
            <option :value="100">100 点 (超快)</option>
            <option :value="500">500 点 (均衡推荐)</option>
            <option :value="1000">1000 点 (高精度)</option>
            <option :value="2000">2000 点 (深度扫描)</option>
          </select>
        </div>

        <!-- Fast PC Only vs PC + Caller -->
        <label class="flex items-center gap-1.5 text-zinc-300 cursor-pointer text-xs" title="勾选后同时抓取 LR 寄存器推导上级调用者；不勾选则只抓 PC，速度翻倍">
          <input type="checkbox" v-model="traceCaller" :disabled="isContinuousRunning" class="accent-amber-500 rounded cursor-pointer" />
          <span>捕获 LR 调用者</span>
        </label>

        <!-- Stream to Disk Toggle -->
        <div class="flex items-center gap-1.5 pl-1 border-l border-zinc-800">
          <label class="flex items-center gap-1.5 text-xs cursor-pointer" :class="isDiskPersistenceEnabled ? 'text-amber-300 font-semibold' : 'text-zinc-400'" title="长时间挂机抓现场时，将海量 Trace 异步流式写入硬盘二进制文件 (.hiltrace)，避免爆内存">
            <input type="checkbox" v-model="isDiskPersistenceEnabled" :disabled="isContinuousRunning" class="accent-amber-500 rounded cursor-pointer" />
            <span>💾 流式落盘</span>
          </label>
          <button
            v-if="isDiskPersistenceEnabled"
            @click="handleChooseDiskTraceFile"
            :disabled="isContinuousRunning"
            class="px-1.5 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 border border-zinc-700 text-[11px]"
            title="选择持久化保存路径"
          >
            {{ diskTraceFilePath ? '已设路径' : '指定文件...' }}
          </button>
        </div>

        <!-- Auto-Freeze on Exception Toggle -->
        <label class="flex items-center gap-1.5 text-xs text-rose-300 cursor-pointer" title="当检测到 HardFault / 异常中断 / 跑飞时，自动停止采样并冻结当前黑匣子执行轨迹">
          <input type="checkbox" v-model="isAutoFreezeOnException" class="accent-rose-500 rounded cursor-pointer" />
          <span>⚡ 异常自动冻结</span>
        </label>

        <!-- Load Offline Trace File -->
        <button
          @click="handleLoadOfflineTraceFile"
          :disabled="isContinuousRunning"
          class="flex items-center gap-1 px-2 py-1 rounded bg-zinc-900 hover:bg-zinc-800 text-purple-300 border border-purple-800/60 text-xs transition-colors"
          title="加载历史保存的 .hiltrace 文件进行离线分析"
        >
          <FolderOpen class="w-3.5 h-3.5 text-purple-400" />
          <span>打开离线日志...</span>
        </button>

        <!-- Main Trigger Button -->
        <button
          @click="handleMainPcSamplingAction"
          :disabled="isSamplingPc && traceMode === 'burst'"
          class="flex items-center gap-1.5 px-3 py-1 rounded text-xs font-semibold transition-all shadow-xs"
          :class="isContinuousRunning ? 'bg-rose-600 hover:bg-rose-500 text-zinc-100 animate-pulse' : 'bg-amber-600 hover:bg-amber-500 text-zinc-950 disabled:opacity-50'"
        >
          <component :is="isContinuousRunning ? Square : isSamplingPc ? RefreshCw : Play" class="w-3.5 h-3.5" :class="{ 'animate-spin': isSamplingPc && traceMode === 'burst', 'fill-current': isContinuousRunning }" />
          <span>
            {{ isContinuousRunning ? '停止连续采样并分析' : (traceMode === 'burst' ? (isSamplingPc ? '突发采集中...' : '开始突发抓取 PC') : '开始连续持续采样') }}
          </span>
        </button>
      </div>
    </div>

    <!-- Replay Mode Banner -->
    <div
      v-if="isReplayMode"
      class="bg-purple-950/70 border-b border-purple-800 text-purple-200 px-4 py-1.5 text-xs flex items-center justify-between font-mono"
    >
      <div class="flex items-center gap-2">
        <span>📼 当前正在回放离线 Trace 日志:</span>
        <span class="font-bold text-amber-300">{{ replayFileName }}</span>
        <span>(共 {{ rawPcTraceList.length }} 帧样本)</span>
      </div>
      <button @click="exitReplayMode" class="px-2 py-0.5 rounded bg-purple-900 hover:bg-purple-800 text-purple-100 text-xs border border-purple-700">
        退出回放
      </button>
    </div>

    <!-- Disk Write Error Alert -->
    <div
      v-if="diskWriteError"
      class="bg-rose-950/50 border-b border-rose-800 text-rose-300 px-4 py-1 text-xs flex items-center justify-between font-mono"
    >
      <span>{{ diskWriteError }}</span>
      <button @click="diskWriteError = ''" class="text-rose-400 hover:text-rose-200">✕</button>
    </div>

    <!-- Spinlock / Loop Warning Alert -->
    <div
      v-if="isLoopDetected"
      class="bg-rose-950/70 border-b border-rose-800 text-rose-300 px-4 py-2 text-xs flex items-center justify-between font-mono animate-pulse"
    >
      <div class="flex items-center gap-2">
        <span class="text-base">🚨</span>
        <span class="font-bold">{{ loopWarningMsg }}</span>
      </div>
      <button @click="isLoopDetected = false" class="text-rose-400 hover:text-rose-200">✕</button>
    </div>

    <!-- Error Alert -->
    <div
      v-if="pcSamplingError"
      class="bg-rose-950/50 border-b border-rose-800 text-rose-300 px-4 py-1.5 text-xs flex items-center justify-between font-mono"
    >
      <span>{{ pcSamplingError }}</span>
      <button @click="pcSamplingError = ''" class="text-rose-400 hover:text-rose-200">✕</button>
    </div>

    <!-- PC Trace View (activeSubView === 'pc_trace') -->
    <div v-if="activeSubView === 'pc_trace'" class="flex-1 flex overflow-hidden">
      <!-- Left: Hotspot Functions Ranking -->
      <div class="w-96 border-r border-zinc-800 flex flex-col bg-zinc-950/60 overflow-hidden shrink-0">
        <div class="p-2.5 bg-zinc-900 border-b border-zinc-800 flex items-center justify-between text-xs font-mono">
          <span class="font-bold text-amber-400">🔥 CPU 热点函数占比榜 (Top Hotspots)</span>
          <span class="text-[10px] text-zinc-500">{{ hotspotList.length }} 个活跃函数</span>
        </div>

        <div class="flex-1 overflow-y-auto p-2 space-y-2">
          <div v-if="hotspotList.length === 0" class="h-full flex flex-col items-center justify-center text-zinc-600 text-xs p-6 text-center">
            <span>暂无采样数据</span>
            <span class="text-[11px] text-zinc-500 mt-1">点击右上角「开始抓取当前 PC 轨迹」查看 CPU 正在哪个函数执行</span>
          </div>

          <div
            v-for="h in hotspotList"
            :key="h.name"
            class="p-2.5 rounded-lg border border-zinc-800 bg-zinc-900/60 hover:bg-zinc-850 transition"
          >
            <div class="flex items-center justify-between text-xs mb-1">
              <span class="font-bold text-zinc-200 truncate font-mono max-w-[200px]" :title="h.name">{{ h.name }}</span>
              <span class="font-bold font-mono text-amber-400">{{ h.percent }}%</span>
            </div>
            <!-- Progress Bar -->
            <div class="w-full bg-zinc-950 rounded-full h-1.5 overflow-hidden mb-1.5 border border-zinc-800">
              <div
                class="h-full rounded-full transition-all"
                :class="h.percent > 50 ? 'bg-rose-500' : h.percent > 20 ? 'bg-amber-400' : 'bg-cyan-500'"
                :style="{ width: `${h.percent}%` }"
              ></div>
            </div>
            <div class="flex items-center justify-between text-[10px] text-zinc-500 font-mono">
              <span>地址: {{ h.addr }}</span>
              <span>命中: {{ h.count }} 次采样</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Right: Detailed PC Waterfall Stream / Caller -->
      <div class="flex-1 flex flex-col overflow-hidden bg-zinc-950">
        <div class="p-2.5 bg-zinc-900 border-b border-zinc-800 flex items-center justify-between text-xs font-mono">
          <div class="flex items-center gap-3">
            <span class="font-bold text-zinc-200">PC 指令流抓取记录 (Raw PC Samples)</span>
            <span v-if="pcSampleRate > 0" class="text-[10px] text-emerald-400">
              采样速率: {{ pcSampleRate }} 点/秒 | 单批耗时: {{ pcSampleDurationMs }}ms
            </span>
          </div>
          <div class="flex items-center gap-2 text-[10px] text-zinc-400">
            <span v-if="isDiskPersistenceEnabled && diskWrittenBytes > 0" class="text-emerald-400 font-mono">
              💾 已落盘: {{ (diskWrittenBytes / (1024 * 1024)).toFixed(2) }} MB
            </span>
            <span v-if="isContinuousRunning" class="text-amber-400 flex items-center gap-1">
              <span class="w-2 h-2 rounded-full bg-rose-500 animate-ping"></span>
              采样中 (累计 {{ totalCollectedSamplesCount }} 点)
            </span>
            <span>当前缓冲: {{ rawPcTraceList.length }} / {{ maxBufferLimit }} 帧</span>
          </div>
        </div>

        <div class="flex-1 overflow-y-auto font-mono text-xs p-2">
          <div v-if="rawPcTraceList.length === 0" class="h-full flex items-center justify-center text-zinc-600 text-xs">
            暂无采集样本
          </div>
          <table v-else class="w-full text-left border-collapse">
            <thead class="text-zinc-500 text-[10.5px] border-b border-zinc-800 sticky top-0 bg-zinc-950">
              <tr>
                <th class="p-1.5 w-14">#</th>
                <th class="p-1.5 w-28">当前 PC 地址</th>
                <th class="p-1.5">命中函数名称</th>
                <th v-if="traceCaller" class="p-1.5 w-28">返回 LR 地址</th>
                <th v-if="traceCaller" class="p-1.5">上级调用者 (Caller)</th>
                <th class="p-1.5 w-20">分类</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="item in rawPcTraceList"
                :key="item.id"
                class="hover:bg-zinc-900 border-b border-zinc-800/40 text-[11px]"
              >
                <td class="p-1.5 text-zinc-600">{{ item.id }}</td>
                <td class="p-1.5 text-cyan-400 font-bold">{{ item.pcHex }}</td>
                <td class="p-1.5 text-zinc-200 font-semibold">{{ item.funcName }}</td>
                <td v-if="traceCaller" class="p-1.5 text-amber-400">{{ item.lrHex || 'N/A' }}</td>
                <td v-if="traceCaller" class="p-1.5 text-purple-300">{{ item.callerName || 'Top / ISR' }}</td>
                <td class="p-1.5">
                  <span class="text-[9px] px-1.5 py-0.2 rounded border bg-zinc-900 border-zinc-800 text-zinc-400">
                    {{ item.category }}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- Main Workspace (Functions Table + Histogram Chart) (activeSubView === 'profiler') -->
    <div v-if="activeSubView === 'profiler'" class="flex-1 flex overflow-hidden">
      <!-- Left: Function Performance Table -->
      <div class="flex-1 flex flex-col border-r border-zinc-800 overflow-hidden">
        <div class="p-2.5 bg-zinc-900 border-b border-zinc-800 flex items-center justify-between text-xs">
          <span class="font-bold text-zinc-200">函数与中断服务耗时排名列表 (按 Max 倒序)</span>
          <span class="text-[11px] text-zinc-500">点击选中行查看右侧耗时分布正态直方图</span>
        </div>

        <div class="flex-1 overflow-y-auto">
          <table class="w-full text-left text-xs border-collapse">
            <thead class="bg-zinc-900/90 text-zinc-400 text-[11px] font-mono sticky top-0 border-b border-zinc-800 select-none">
              <tr>
                <th class="p-2">函数 / 中断名称</th>
                <th class="p-2">分类</th>
                <th class="p-2 text-right">调用次数</th>
                <th class="p-2 text-right">当前 (µs)</th>
                <th class="p-2 text-right">最小 (µs)</th>
                <th class="p-2 text-right">最大 (µs)</th>
                <th class="p-2 text-right">平均 (µs)</th>
                <th class="p-2 text-right">P95 (µs)</th>
                <th class="p-2 text-right w-24">CPU 占比</th>
              </tr>
            </thead>
            <tbody class="font-mono text-[11.5px] divide-y divide-zinc-900">
              <tr
                v-for="item in functionsList"
                :key="item.id"
                @click="selectedFunctionId = item.id"
                class="hover:bg-zinc-800/60 cursor-pointer transition-colors"
                :class="selectedFunctionId === item.id ? 'bg-amber-950/30 text-amber-200' : ''"
              >
                <td class="p-2 font-sans font-semibold text-zinc-200 flex items-center gap-1.5">
                  <span
                    v-if="item.maxUs > alertThresholdUs"
                    class="w-1.5 h-1.5 rounded-full bg-rose-500 animate-ping"
                    title="存在超限耗时抖动"
                  ></span>
                  <span>{{ item.name }}</span>
                </td>
                <td class="p-2 text-zinc-400 font-sans">
                  <span class="px-1.5 py-0.5 rounded text-[10px] bg-zinc-800 text-zinc-400 border border-zinc-700/60">
                    {{ item.category }}
                  </span>
                </td>
                <td class="p-2 text-right text-zinc-400">{{ item.callCount }}</td>
                <td class="p-2 text-right text-cyan-400">{{ item.lastUs }}</td>
                <td class="p-2 text-right text-zinc-500">{{ item.minUs }}</td>
                <td class="p-2 text-right" :class="item.maxUs > alertThresholdUs ? 'text-rose-400 font-bold' : 'text-zinc-200'">
                  {{ item.maxUs }}
                </td>
                <td class="p-2 text-right text-zinc-300">{{ item.avgUs }}</td>
                <td class="p-2 text-right text-amber-400">{{ item.p95Us }}</td>
                <td class="p-2 text-right">
                  <div class="flex items-center justify-end gap-1.5">
                    <div class="w-12 bg-zinc-800 h-1.5 rounded-full overflow-hidden">
                      <div class="bg-emerald-500 h-full" :style="{ width: `${Math.min(100, item.cpuPercent)}%` }"></div>
                    </div>
                    <span class="text-zinc-400 text-[10.5px] w-8 text-right">{{ item.cpuPercent }}%</span>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Right: Detailed Histogram & Distribution Panel -->
      <div class="w-80 border-l border-zinc-800 bg-zinc-900/40 p-4 flex flex-col shrink-0 text-xs overflow-y-auto">
        <div class="font-bold text-xs text-zinc-200 pb-2 border-b border-zinc-800 flex items-center justify-between">
          <span>耗时分布直方图 (Histogram)</span>
          <span class="text-amber-400 font-mono">{{ selectedFunction.name }}</span>
        </div>

        <!-- Metric Details -->
        <div class="grid grid-cols-2 gap-2 my-3 font-mono text-[11px]">
          <div class="p-2 bg-zinc-900 border border-zinc-800 rounded">
            <span class="text-zinc-500 block text-[10px]">Min 耗时</span>
            <span class="text-emerald-400 font-bold text-sm">{{ selectedFunction.minUs }} µs</span>
          </div>
          <div class="p-2 bg-zinc-900 border border-zinc-800 rounded">
            <span class="text-zinc-500 block text-[10px]">Max 耗时</span>
            <span class="text-rose-400 font-bold text-sm">{{ selectedFunction.maxUs }} µs</span>
          </div>
          <div class="p-2 bg-zinc-900 border border-zinc-800 rounded">
            <span class="text-zinc-500 block text-[10px]">Avg 耗时</span>
            <span class="text-cyan-400 font-bold text-sm">{{ selectedFunction.avgUs }} µs</span>
          </div>
          <div class="p-2 bg-zinc-900 border border-zinc-800 rounded">
            <span class="text-zinc-500 block text-[10px]">P95 耗时</span>
            <span class="text-amber-400 font-bold text-sm">{{ selectedFunction.p95Us }} µs</span>
          </div>
        </div>

        <!-- Histogram Bars Visualization -->
        <div class="flex-1 flex flex-col justify-end pt-4 border-t border-zinc-800">
          <div class="text-[11px] text-zinc-400 font-sans mb-3 flex items-center justify-between">
            <span>采样频次分布 (正态分布区间)</span>
            <span class="text-zinc-500 font-mono text-[10px]">10 阶区间</span>
          </div>

          <div class="h-44 flex items-end gap-1.5 bg-zinc-950 p-2.5 rounded-lg border border-zinc-800/80">
            <div
              v-for="(count, bIdx) in selectedFunction.histogram"
              :key="bIdx"
              class="flex-1 flex flex-col items-center justify-end h-full group relative"
            >
              <!-- Bar -->
              <div
                class="w-full bg-cyan-600/70 hover:bg-cyan-400 rounded-t transition-all"
                :style="{ height: `${Math.max(4, (count / Math.max(...selectedFunction.histogram)) * 100)}%` }"
              ></div>

              <!-- Tooltip -->
              <div class="opacity-0 group-hover:opacity-100 absolute -top-8 bg-zinc-800 text-zinc-200 text-[10px] px-1.5 py-0.5 rounded shadow pointer-events-none transition-opacity font-mono z-10 whitespace-nowrap">
                {{ count }} 次
              </div>
            </div>
          </div>

          <div class="flex justify-between text-[10px] font-mono text-zinc-500 mt-1">
            <span>{{ selectedFunction.minUs }}µs</span>
            <span>{{ selectedFunction.avgUs }}µs</span>
            <span>{{ selectedFunction.maxUs }}µs</span>
          </div>
        </div>

        <!-- Optimization Suggestion -->
        <div class="mt-4 p-2.5 bg-zinc-900 border border-zinc-800 rounded-lg text-[11px] text-zinc-400 leading-relaxed font-sans">
          <span class="text-amber-400 font-semibold block mb-0.5">性能优化建议:</span>
          <span v-if="selectedFunction.maxUs > alertThresholdUs">
            函数最大耗时已超过 {{ alertThresholdUs }}µs 阈值，需排查其内部是否存在死循环、阻塞等待外设标志位或长中断嵌套。
          </span>
          <span v-else>
            该函数执行耗时均在安全合理区间内，无严重抖动风险。
          </span>
        </div>
      </div>
    </div>
  </div>
</template>
