<script setup lang="ts">
import { ref, shallowRef, watch, onMounted, onUnmounted, nextTick } from 'vue';
import { safeInvoke, isTauri } from '../utils/ipc';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import type { SerialRxPayload, SerialLogItem } from '../types';
import {
  Trash2,
  Download,
  ArrowDown,
  Send,
  Binary,
  Clock,
  Terminal,
  Layers,
  RotateCcw,
  Zap,
  Activity,
  Copy,
  Check,
  Power,
  WrapText,
  Sliders
} from '@lucide/vue';
import CommandGroupPanel from './CommandGroupPanel.vue';
import TriggerPanel from './TriggerPanel.vue';
import SerialXtermView from './SerialXtermView.vue';
import ModbusDrawer from './ModbusDrawer.vue';
import ProtocolDashboard from './ProtocolDashboard.vue';
import { encodeCommand } from '../utils/commandEncoder';
import { appendChecksum, type ChecksumAlgorithm } from '../utils/crc';
import type { CommandGroup, CommandItem, TriggerRule, PortInfo } from '../types';

const props = defineProps<{
  portName: string;
  baudRate: number;
  isConnected: boolean;
  isDaplink: boolean;
  availablePorts?: PortInfo[];
}>();

const emit = defineEmits<{
  (e: 'switch-tab', tab: string): void;
  (e: 'update-stats', stats: { rx: number; tx: number }): void;
  (e: 'toggle-connection'): void;
  (e: 'change-baud', baud: number): void;
  (e: 'change-port', port: string): void;
}>();

const dtrState = ref<boolean>(false);
const rtsState = ref<boolean>(false);
const isResetting = ref<boolean>(false);
const baudRates = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600];

async function refreshPinStates() {
  if (!props.isConnected || props.portName.startsWith('RTT')) return;
  try {
    const [_, __, dtr, rts]: [boolean, string | null, boolean, boolean, boolean] = await safeInvoke('get_serial_status', {
      portName: props.portName
    });
    dtrState.value = dtr;
    rtsState.value = rts;
  } catch (err) {
    // Ignore error if port is disconnected
  }
}

async function toggleDtr() {
  if (!props.isConnected) return;
  const next = !dtrState.value;
  try {
    await safeInvoke('set_dtr', { level: next, portName: props.portName });
    dtrState.value = next;
    appendLog(`[硬件引脚] DTR(RST) -> ${next ? '1 (拉低复位)' : '0 (释放)'}`, 'info');
  } catch (err) {
    appendLog(`设置 DTR 失败: ${err}`, 'error');
  }
}

async function toggleRts() {
  if (!props.isConnected) return;
  const next = !rtsState.value;
  try {
    await safeInvoke('set_rts', { level: next, portName: props.portName });
    rtsState.value = next;
    appendLog(`[硬件引脚] RTS(BOOT) -> ${next ? '1 (进入BOOT模式)' : '0 (正常模式)'}`, 'info');
  } catch (err) {
    appendLog(`设置 RTS 失败: ${err}`, 'error');
  }
}

async function triggerReset(seqType: string) {
  if (!props.isConnected) return;
  if (!props.isDaplink) {
    alert('当前串口设备不是 DAPLink 探针，仅 DAPLink 具备 DTR/RTS 硬件引脚控制能力。');
    return;
  }
  isResetting.value = true;
  try {
    await safeInvoke('execute_reset_sequence', { seqType, portName: props.portName });
    appendLog(`[硬件复位] 已向 ${props.portName} 发送 ${seqType === 'bootloader_reset' ? '进入 BOOT 引导复位' : '普通系统复位'} 序列`, 'info');
    await refreshPinStates();
  } catch (err) {
    appendLog(`硬件复位执行失败: ${err}`, 'error');
  } finally {
    isResetting.value = false;
  }
}

const isCopiedAll = ref<boolean>(false);

function copyAllLogs() {
  if (logs.value.length === 0) return;
  const text = logs.value.map(l => {
    if (!showTimestamps.value && l.type === 'rx') {
      return l.text;
    }
    const ts = showTimestamps.value ? `[${l.timestamp}] ` : '';
    return `${ts}[${l.type.toUpperCase()}] ${l.text}`;
  }).join('\n');
  navigator.clipboard.writeText(text);
  isCopiedAll.value = true;
  setTimeout(() => isCopiedAll.value = false, 2000);
}

const isCommandPanelOpen = ref<boolean>(false);
const isTriggerPanelOpen = ref<boolean>(false);
const isModbusDrawerOpen = ref<boolean>(false);
const isDashboardOpen = ref<boolean>(false);
const cmdPanelRef = ref<any>(null);
const triggerPanelRef = ref<any>(null);
const modbusDrawerRef = ref<any>(null);
const xtermRef = ref<any>(null);
const activeGroup = ref<CommandGroup | null>(null);

const PREF_KEY_SESSION_MODE = 'ai_hil_pref_session_mode';
const sessionMode = ref<'log' | 'vt100'>(
  (localStorage.getItem(PREF_KEY_SESSION_MODE) as 'log' | 'vt100') || 'log'
);
watch(sessionMode, (m) => {
  localStorage.setItem(PREF_KEY_SESSION_MODE, m);
  if (m === 'vt100') {
    nextTick(() => {
      xtermRef.value?.fit();
      xtermRef.value?.focus();
    });
  }
});

const checksumAlgo = ref<ChecksumAlgorithm>('none');

function handleSendSingleGroupCommand(cmd: CommandItem) {
  if (cmdPanelRef.value) {
    cmdPanelRef.value.sendSingleCommand(cmd);
  }
}

async function executeTriggerResponse(rule: TriggerRule) {
  const encoded = encodeCommand({
    id: rule.id,
    label: rule.name,
    payload: rule.responsePayload,
    format: rule.responseFormat,
    lineEnding: rule.responseEnding,
    delayAfterMs: 0,
    enabled: true
  });

  setTimeout(async () => {
    try {
      const sentCount: number = await safeInvoke('send_serial_data', { 
        data: encoded.bytes,
        portName: props.portName
      });
      txBytesCount.value += sentCount;
      emit('update-stats', { rx: rxBytesCount.value, tx: txBytesCount.value });
      appendLog(`⚡ [触发器: ${rule.name}] 命中规则，自动应答 -> ${encoded.textDisplay}`, 'tx');
    } catch (err) {
      appendLog(`⚡ [触发器: ${rule.name}] 自动应答发送失败: ${err}`, 'error');
    }
  }, rule.delayMs);
}

function handleIncomingRxText(text: string) {
  if (triggerPanelRef.value) {
    const matched = triggerPanelRef.value.checkAndMatchTriggers(text);
    for (const rule of matched) {
      executeTriggerResponse(rule);
    }
  }
}

const logContainer = ref<HTMLElement | null>(null);
const logs = shallowRef<SerialLogItem[]>([]);
let nextLogId = 1;
// Optimized: Limit to 1200 lines per tab to keep DOM node count < 2000 and prevent Renderer memory bloat
const MAX_LOG_LINES = 1200;

// Preferences persistence keys
const PREF_KEY_TIMESTAMPS = 'ai_hil_pref_timestamps';
const PREF_KEY_AUTOSCROLL = 'ai_hil_pref_autoscroll';
const PREF_KEY_AUTOWRAP = 'ai_hil_pref_autowrap';
const PREF_KEY_VIEWMODE = 'ai_hil_pref_viewmode';
const PREF_KEY_LINE_ENDING = 'ai_hil_pref_line_ending';

const viewMode = ref<'string' | 'hex'>(
  (localStorage.getItem(PREF_KEY_VIEWMODE) as 'string' | 'hex') || 'string'
);
const showTimestamps = ref<boolean>(
  localStorage.getItem(PREF_KEY_TIMESTAMPS) !== null
    ? localStorage.getItem(PREF_KEY_TIMESTAMPS) === 'true'
    : true
);
const autoScroll = ref<boolean>(
  localStorage.getItem(PREF_KEY_AUTOSCROLL) !== null
    ? localStorage.getItem(PREF_KEY_AUTOSCROLL) === 'true'
    : true
);
const autoWrap = ref<boolean>(
  localStorage.getItem(PREF_KEY_AUTOWRAP) !== null
    ? localStorage.getItem(PREF_KEY_AUTOWRAP) === 'true'
    : true
);

watch(viewMode, (v) => localStorage.setItem(PREF_KEY_VIEWMODE, v));
watch(showTimestamps, (v) => localStorage.setItem(PREF_KEY_TIMESTAMPS, String(v)));
watch(autoScroll, (v) => localStorage.setItem(PREF_KEY_AUTOSCROLL, String(v)));
watch(autoWrap, (v) => localStorage.setItem(PREF_KEY_AUTOWRAP, String(v)));

const inputMessage = ref<string>('');
const inputMode = ref<'string' | 'hex'>('string');
const lineEnding = ref<string>(
  localStorage.getItem(PREF_KEY_LINE_ENDING) || 'crlf'
);
watch(lineEnding, (v) => localStorage.setItem(PREF_KEY_LINE_ENDING, v));

const rxBytesCount = ref<number>(0);
const txBytesCount = ref<number>(0);

let unlistenRx: UnlistenFn | null = null;
let worker: Worker | null = null;

function formatTimestamp(): string {
  const d = new Date();
  return d.toTimeString().split(' ')[0] + '.' + d.getMilliseconds().toString().padStart(3, '0');
}

function scrollToBottom() {
  if (!autoScroll.value || !logContainer.value) return;
  nextTick(() => {
    if (logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight;
    }
  });
}

function appendLog(text: string, type: 'rx' | 'tx' | 'info' | 'error', customTime?: string) {
  // If receiving RX stream chunk and the previous log item is also RX:
  // If showTimestamps is disabled, merge continuous RX chunks seamlessly into the last item
  // unless user or incoming data explicitly contains newlines, or in line-mode.
  // Even if showTimestamps is enabled, if the previous RX didn't end with newline,
  // append in-place so buffer slicing never creates separate rows or broken words!
  if (type === 'rx' && logs.value.length > 0) {
    const lastItem = logs.value[logs.value.length - 1];
    if (lastItem.type === 'rx') {
      if (!showTimestamps.value) {
        // Without timestamps, continuous RX is one continuous terminal output stream
        lastItem.text += text;
        logs.value = [...logs.value];
        scrollToBottom();
        return;
      } else if (!lastItem.text.endsWith('\n') && !lastItem.text.endsWith('\r')) {
        // With timestamps, if the line hasn't finished yet, append in-place
        lastItem.text += text;
        logs.value = [...logs.value];
        scrollToBottom();
        return;
      }
    }
  }

  const newItem: SerialLogItem = {
    id: nextLogId++,
    timestamp: customTime || formatTimestamp(),
    text,
    type
  };

  let current = [...logs.value, newItem];
  if (current.length > MAX_LOG_LINES) {
    current = current.slice(current.length - MAX_LOG_LINES);
  }
  logs.value = current;
  scrollToBottom();
}

function clearLogs() {
  logs.value = [];
  rxBytesCount.value = 0;
  txBytesCount.value = 0;
  emit('update-stats', { rx: 0, tx: 0 });
}

function exportLogs() {
  const content = logs.value.map(l => {
    if (!showTimestamps.value && l.type === 'rx') {
      return l.text;
    }
    const ts = showTimestamps.value ? `[${l.timestamp}] ` : '';
    return `${ts}[${l.type.toUpperCase()}] ${l.text}`;
  }).join('\n');
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `serial_log_${props.portName}_${new Date().toISOString().replace(/[:.]/g, '-')}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

async function handleSendMessage(customText?: string) {
  const textToSend = customText !== undefined ? customText : inputMessage.value;
  if (!textToSend || !props.isConnected) return;

  let bytes: number[] = [];

  if (inputMode.value === 'hex' && customText === undefined) {
    const cleanHex = textToSend.replace(/\s+/g, '');
    if (!/^[0-9a-fA-F]*$/.test(cleanHex)) {
      appendLog('HEX 格式无效，必须为十六进制字符', 'error');
      return;
    }
    for (let i = 0; i < cleanHex.length; i += 2) {
      bytes.push(parseInt(cleanHex.substring(i, i + 2), 16));
    }
  } else {
    let payload = textToSend;
    if (lineEnding.value === 'crlf') payload += '\r\n';
    else if (lineEnding.value === 'lf') payload += '\n';
    else if (lineEnding.value === 'cr') payload += '\r';

    bytes = Array.from(new TextEncoder().encode(payload));
  }

  // Automatically append checksum if selected
  if (checksumAlgo.value !== 'none') {
    bytes = await appendChecksum(bytes, checksumAlgo.value);
  }

  try {
    const sentCount: number = await safeInvoke('send_serial_data', { 
      data: bytes,
      portName: props.portName
    });
    txBytesCount.value += sentCount;
    emit('update-stats', { rx: rxBytesCount.value, tx: txBytesCount.value });
    
    // If checksum was appended, log formatted hex
    if (checksumAlgo.value !== 'none') {
      const displayHex = bytes.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');
      appendLog(`${textToSend} [追加校验: ${displayHex}]`, 'tx');
    } else {
      appendLog(textToSend, 'tx');
    }
    if (customText === undefined) {
      inputMessage.value = '';
    }
  } catch (err: any) {
    appendLog(`发送失败: ${err}`, 'error');
  }
}

function handleBytesSent(count: number) {
  txBytesCount.value += count;
  emit('update-stats', { rx: rxBytesCount.value, tx: txBytesCount.value });
}

onMounted(async () => {
  // Initialize Web Worker
  try {
    worker = new Worker(new URL('../workers/serialParser.worker.ts', import.meta.url), { type: 'module' });
    worker.onmessage = (e) => {
      if (e.data.type === 'formatted_chunk') {
        rxBytesCount.value += e.data.rawLength;
        emit('update-stats', { rx: rxBytesCount.value, tx: txBytesCount.value });
        appendLog(e.data.text, 'rx', e.data.timestamp);
        handleIncomingRxText(e.data.text);
      }
    };
  } catch (err) {
    console.error('Failed to instantiate Web Worker:', err);
  }

  // Listen to Tauri serial-rx event, filter by current portName
  if (isTauri()) {
    try {
      unlistenRx = await listen<SerialRxPayload>('serial-rx', (event) => {
        if (event.payload.port && event.payload.port !== props.portName) {
          return; // Ignore other ports
        }
        const raw = new Uint8Array(event.payload.data);
        const ts = formatTimestamp();

        // 1. Dispatch to Modbus Drawer if open
        if (isModbusDrawerOpen.value && modbusDrawerRef.value) {
          modbusDrawerRef.value.feedIncomingBytes(raw);
        }

        // 2. Dispatch to xterm terminal if in VT100 mode
        if (sessionMode.value === 'vt100') {
          if (xtermRef.value) {
            xtermRef.value.writeRawBytes(raw);
          }
          rxBytesCount.value += raw.length;
          emit('update-stats', { rx: rxBytesCount.value, tx: txBytesCount.value });
          return;
        }

        // 3. Normal Log Stream mode
        if (worker) {
          worker.postMessage({
            rawBytes: raw,
            mode: viewMode.value,
            timestamp: ts
          });
        } else {
          const text = new TextDecoder('utf-8', { fatal: false }).decode(raw);
          rxBytesCount.value += raw.length;
          emit('update-stats', { rx: rxBytesCount.value, tx: txBytesCount.value });
          appendLog(text, 'rx', ts);
          handleIncomingRxText(text);
        }
      });
    } catch (err) {
      console.warn('Failed to attach serial-rx listener:', err);
    }
  }

  if (props.isConnected) {
    refreshPinStates();
  }
});

watch(() => props.isConnected, (connected: boolean) => {
  if (connected) {
    refreshPinStates();
  } else {
    dtrState.value = false;
    rtsState.value = false;
  }
});

onUnmounted(() => {
  if (unlistenRx) unlistenRx();
  if (worker) {
    worker.terminate();
    worker = null;
  }
  // Thorough GC release: clear retained log arrays to free DOM and string heap
  logs.value = [];
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-mono text-xs">
    <!-- Terminal Header Toolbar -->
    <div class="bg-zinc-900 border-b border-zinc-800 px-3 py-1.5 flex items-center justify-between gap-3 select-none">
      <!-- Left: Title, Port & Baud Selectors, Connect Toggle & Hardware Pin Controls -->
      <div class="flex items-center gap-2 flex-wrap">
        <div class="flex items-center gap-1.5 text-zinc-300 font-semibold">
          <Terminal class="w-4 h-4 text-emerald-400 shrink-0" />
          
          <!-- Switch Port Dropdown (Enabled if disconnected, or available ports provided) -->
          <select
            v-if="availablePorts && availablePorts.length > 0 && !portName.startsWith('RTT')"
            :value="portName"
            @change="(e: any) => emit('change-port', e.target.value)"
            :disabled="isConnected"
            class="bg-zinc-950 border border-zinc-800 text-[11px] text-zinc-200 py-0.5 px-1.5 rounded outline-none font-mono cursor-pointer disabled:opacity-75 disabled:cursor-not-allowed hover:border-zinc-700"
            title="选择切换端口 (断开状态下可直接换COM口)"
          >
            <option v-for="p in availablePorts" :key="p.port_name" :value="p.port_name">
              {{ p.port_name }} {{ p.is_daplink ? '[DAPLink]' : '' }}
            </option>
          </select>
          <span v-else class="text-zinc-200 font-mono">{{ portName }}</span>

          <!-- Switch Baud Rate Dropdown (Enabled even if connected, supports runtime adjustment) -->
          <select
            v-if="!portName.startsWith('RTT')"
            :value="baudRate"
            @change="(e: any) => emit('change-baud', Number(e.target.value))"
            class="bg-zinc-950 border border-zinc-800 text-[10px] text-zinc-300 py-0.5 px-1.5 rounded outline-none font-mono cursor-pointer hover:border-zinc-700"
            :title="isConnected ? '在线调整波特率 (自动重连以新波特率生效)' : '设置该会话波特率'"
          >
            <option v-for="b in baudRates" :key="b" :value="b">
              {{ b }}
            </option>
          </select>

          <!-- Direct Open / Close Port Button inside Tab -->
          <button
            @click="emit('toggle-connection')"
            class="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold transition-colors border shadow-xs ml-0.5 cursor-pointer"
            :class="isConnected 
              ? 'bg-rose-950/80 text-rose-300 border-rose-800 hover:bg-rose-900' 
              : 'bg-emerald-950/90 text-emerald-300 border-emerald-700 hover:bg-emerald-900'"
            :title="isConnected ? '关闭当前端口连接 (保留历史日志与会话标签)' : '打开/重新连接当前端口'"
          >
            <Power class="w-3 h-3" />
            <span>{{ isConnected ? '关闭' : '打开' }}</span>
          </button>
        </div>

        <!-- Hardware Pin Controls inside Tab (DTR / RTS / Reset) -->
        <div v-if="!portName.startsWith('RTT')" class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5">
          <!-- DTR Button: DTR 1 = RESET low, DTR 0 = release -->
          <button
            @click="toggleDtr"
            :disabled="!isConnected"
            title="DTR 控制 (RESET引脚: 1=拉低复位, 0=释放)"
            class="flex items-center gap-1 px-1.5 py-0.2 rounded text-[10px] font-mono transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            :class="dtrState ? 'bg-rose-950 text-rose-300 border border-rose-800 font-bold' : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'"
          >
            <span class="w-1.5 h-1.5 rounded-full" :class="dtrState ? 'bg-rose-500 animate-pulse' : 'bg-zinc-500'"></span>
            <span>DTR:{{ dtrState ? '1' : '0' }}</span>
          </button>

          <!-- RTS Button: RTS 1 = BOOT mode, RTS 0 = Normal mode -->
          <button
            @click="toggleRts"
            :disabled="!isConnected"
            title="RTS 控制 (BOOT引脚: 1=BOOT模式, 0=正常运行)"
            class="flex items-center gap-1 px-1.5 py-0.2 rounded text-[10px] font-mono transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            :class="rtsState ? 'bg-amber-950 text-amber-300 border border-amber-800 font-bold' : 'bg-zinc-900 text-zinc-400 hover:text-zinc-200'"
          >
            <span class="w-1.5 h-1.5 rounded-full" :class="rtsState ? 'bg-amber-500 animate-pulse' : 'bg-zinc-500'"></span>
            <span>RTS:{{ rtsState ? '1' : '0' }}</span>
          </button>

          <!-- Hardware Reset for DAPLink -->
          <div v-if="isDaplink" class="flex items-center gap-1 pl-1 border-l border-zinc-800">
            <button
              @click="triggerReset('normal_reset')"
              :disabled="!isConnected || isResetting"
              class="flex items-center gap-1 px-1.5 py-0.2 rounded text-[10px] bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border border-zinc-700/60 transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              title="普通复位: RTS 0 (正常态) -> DTR 产生 100ms 复位脉冲"
            >
              <RotateCcw class="w-2.5 h-2.5" :class="{ 'animate-spin': isResetting }" />
              <span>复位</span>
            </button>
            <button
              @click="triggerReset('bootloader_reset')"
              :disabled="!isConnected || isResetting"
              class="flex items-center gap-1 px-1.5 py-0.2 rounded text-[10px] bg-amber-950/60 hover:bg-amber-900 text-amber-300 border border-amber-800/60 transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              title="进入 BOOT 引导复位: RTS 1 -> 延时 500ms 建立电平 -> DTR 产生 100ms 复位脉冲"
            >
              <Zap class="w-2.5 h-2.5 text-amber-400" />
              <span>BOOT</span>
            </button>
          </div>
        </div>

        <!-- Session Mode Switcher: Log Stream vs VT100 Terminal -->
        <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded p-0.5 ml-1">
          <button
            @click="sessionMode = 'log'"
            class="px-2 py-0.5 rounded text-[11px] transition-colors"
            :class="sessionMode === 'log' ? 'bg-zinc-800 text-emerald-400 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            title="日志模式: 适合抓包、时间戳记录与调试日志流"
          >
            日志流
          </button>
          <button
            @click="sessionMode = 'vt100'"
            class="px-2 py-0.5 rounded text-[11px] transition-colors flex items-center gap-1"
            :class="sessionMode === 'vt100' ? 'bg-zinc-800 text-cyan-400 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            title="VT100 终端: 原生 Linux 控制台、Shell 交互、Tab补全与 ANSI 颜色"
          >
            <Terminal class="w-3 h-3" />
            <span>VT100 终端</span>
          </button>
        </div>

        <div v-show="sessionMode === 'log'" class="flex items-center bg-zinc-950 border border-zinc-800 rounded p-0.5 ml-1">
          <button
            @click="viewMode = 'string'"
            class="px-2 py-0.5 rounded text-[11px] transition-colors"
            :class="viewMode === 'string' ? 'bg-zinc-800 text-emerald-400 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
          >
            ASCII 文本
          </button>
          <button
            @click="viewMode = 'hex'"
            class="px-2 py-0.5 rounded text-[11px] transition-colors flex items-center gap-1"
            :class="viewMode === 'hex' ? 'bg-zinc-800 text-emerald-400 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
          >
            <Binary class="w-3 h-3" />
            <span>HEX</span>
          </button>
        </div>

        <!-- Toggles for Log Stream -->
        <template v-if="sessionMode === 'log'">
          <label class="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-200 cursor-pointer ml-1">
            <input type="checkbox" v-model="showTimestamps" class="rounded bg-zinc-800 border-zinc-700 text-emerald-500 focus:ring-0">
            <Clock class="w-3 h-3" />
            <span>时间戳</span>
          </label>

          <label class="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-200 cursor-pointer">
            <input type="checkbox" v-model="autoScroll" class="rounded bg-zinc-800 border-zinc-700 text-emerald-500 focus:ring-0">
            <ArrowDown class="w-3 h-3" />
            <span>自动滚动</span>
          </label>

          <label class="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-200 cursor-pointer">
            <input type="checkbox" v-model="autoWrap" class="rounded bg-zinc-800 border-zinc-700 text-emerald-500 focus:ring-0">
            <WrapText class="w-3 h-3" />
            <span>自动换行</span>
          </label>
        </template>

        <!-- Protocol Dashboard Toggle Button -->
        <button
          @click="isDashboardOpen = !isDashboardOpen"
          class="px-2 py-0.5 rounded text-[11px] transition-colors border flex items-center gap-1 ml-1"
          :class="isDashboardOpen ? 'bg-emerald-950 text-emerald-300 border-emerald-700/80 font-bold' : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
          title="切换自定义交互操控台 (滑动条/开关下发控制)"
        >
          <Sliders class="w-3.5 h-3.5 text-emerald-400" />
          <span>交互操控</span>
        </button>

        <!-- Modbus RTU Drawer Toggle Button -->
        <button
          @click="isModbusDrawerOpen = !isModbusDrawerOpen"
          class="px-2 py-0.5 rounded text-[11px] transition-colors border flex items-center gap-1 ml-0.5"
          :class="isModbusDrawerOpen ? 'bg-amber-950 text-amber-300 border-amber-700/80 font-bold' : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
          title="切换 Modbus RTU 读写与寄存器可视化抽屉"
        >
          <Layers class="w-3.5 h-3.5 text-amber-400" />
          <span>Modbus</span>
        </button>

        <!-- Command Group Toggle Button -->
        <button
          @click="isCommandPanelOpen = !isCommandPanelOpen"
          class="px-2 py-0.5 rounded text-[11px] transition-colors border flex items-center gap-1 ml-0.5"
          :class="isCommandPanelOpen ? 'bg-emerald-950 text-emerald-300 border-emerald-700/80 font-bold' : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
          title="切换右侧命令组管理面板"
        >
          <Layers class="w-3.5 h-3.5 text-emerald-400" />
          <span>命令组 {{ activeGroup ? `(${activeGroup.commands.length})` : '' }}</span>
        </button>

        <!-- Smart Trigger / Auto-Responder Toggle Button -->
        <button
          @click="isTriggerPanelOpen = !isTriggerPanelOpen"
          class="px-2 py-0.5 rounded text-[11px] transition-colors border flex items-center gap-1"
          :class="isTriggerPanelOpen ? 'bg-amber-950 text-amber-300 border-amber-700/80 font-bold' : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
          title="切换智能应答触发器面板"
        >
          <Zap class="w-3.5 h-3.5 text-amber-400" />
          <span>自动应答</span>
        </button>

        <!-- Quick Jump to Waveform Plotter -->
        <button
          @click="emit('switch-tab', 'plotter')"
          class="px-2 py-0.5 rounded text-[11px] bg-zinc-800 hover:bg-zinc-700 text-cyan-300 border border-cyan-800/60 transition-colors flex items-center gap-1 ml-1"
          title="切换到实时波形示波器"
        >
          <Activity class="w-3.5 h-3.5 text-cyan-400" />
          <span>波形曲线</span>
        </button>
      </div>

      <!-- Right: Stats & Actions -->
      <div class="flex items-center gap-2">
        <div class="text-[11px] text-zinc-500 flex items-center gap-2 font-mono">
          <span>RX: <strong class="text-zinc-300">{{ rxBytesCount }}</strong> B</span>
          <span>TX: <strong class="text-zinc-300">{{ txBytesCount }}</strong> B</span>
          <span>行数: <strong class="text-zinc-300">{{ logs.length }}</strong></span>
        </div>

        <div class="h-3 w-px bg-zinc-800"></div>

        <button
          @click="copyAllLogs"
          :disabled="logs.length === 0"
          :title="isCopiedAll ? '已复制到剪贴板' : '复制终端全部日志'"
          class="p-1 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded transition-colors disabled:opacity-40"
        >
          <component :is="isCopiedAll ? Check : Copy" class="w-3.5 h-3.5" :class="{ 'text-emerald-400': isCopiedAll }" />
        </button>

        <button
          @click="exportLogs"
          title="导出日志文件"
          class="p-1 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded transition-colors"
        >
          <Download class="w-3.5 h-3.5" />
        </button>

        <button
          @click="clearLogs"
          title="清空终端"
          class="p-1 text-zinc-400 hover:text-rose-400 hover:bg-zinc-800 rounded transition-colors"
        >
          <Trash2 class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- Main Center Viewport: Split Terminal Logs / VT100 & Drawers -->
    <div class="flex-1 flex overflow-hidden min-h-0">
      <!-- Left: Terminal Log Viewport or VT100 Terminal View -->
      <div v-show="sessionMode === 'vt100'" class="flex-1 h-full overflow-hidden">
        <SerialXtermView
          ref="xtermRef"
          :port-name="portName"
          :is-connected="isConnected"
          @bytes-sent="handleBytesSent"
          @log="appendLog"
        />
      </div>

      <div
        v-show="sessionMode === 'log'"
        ref="logContainer"
        class="flex-1 overflow-auto p-3 space-y-0.5 select-text bg-zinc-950 font-mono text-[11.5px] leading-relaxed"
      >
        <div v-if="logs.length === 0" class="h-full flex flex-col items-center justify-center text-zinc-600 select-none">
          <Terminal class="w-10 h-10 mb-2 stroke-1 opacity-40" />
          <p>[{{ portName }}] 串口就绪，等待数据输入或发送测试命令...</p>
          <p class="text-[10px] text-zinc-700 mt-1">独立后台会话运行，多串口并发收发互不影响</p>
        </div>

        <div
          v-for="item in logs"
          :key="item.id"
          class="flex items-start gap-1.5 hover:bg-zinc-900/50 rounded px-1 -mx-1"
        >
          <!-- Timestamp -->
          <span v-if="showTimestamps" class="text-zinc-600 text-[10px] shrink-0 select-none">
            [{{ item.timestamp }}]
          </span>

          <!-- Direction Badge (only shown if timestamps are on or message is non-rx) -->
          <span
            v-if="showTimestamps || item.type !== 'rx'"
            class="text-[9px] px-1 py-0.2 rounded font-bold uppercase shrink-0 select-none"
            :class="{
              'bg-emerald-950/80 text-emerald-400 border border-emerald-800/40': item.type === 'rx',
              'bg-sky-950/80 text-sky-400 border border-sky-800/40': item.type === 'tx',
              'bg-amber-950/80 text-amber-400 border border-amber-800/40': item.type === 'info',
              'bg-rose-950/80 text-rose-400 border border-rose-800/40': item.type === 'error',
            }"
          >
            {{ item.type }}
          </span>

          <!-- Content: switch between whitespace-pre-wrap (wrapping) and whitespace-pre (no-wrap horizontal scroll) -->
          <span
            class="flex-1"
            :class="[
              autoWrap ? 'whitespace-pre-wrap break-all' : 'whitespace-pre overflow-x-visible',
              {
                'text-emerald-300': item.type === 'rx',
                'text-sky-300 font-medium': item.type === 'tx',
                'text-amber-300': item.type === 'info',
                'text-rose-400 font-semibold': item.type === 'error',
              }
            ]"
          >{{ item.text }}</span>
        </div>
      </div>

      <!-- Right: Collapsible Custom Protocol Dashboard -->
      <div
        v-show="isDashboardOpen"
        class="shrink-0 overflow-hidden"
      >
        <ProtocolDashboard
          :port-name="portName"
          :is-connected="isConnected"
          @close="isDashboardOpen = false"
          @log="appendLog"
          @bytes-sent="handleBytesSent"
        />
      </div>

      <!-- Right: Collapsible Modbus RTU Drawer -->
      <div
        v-show="isModbusDrawerOpen"
        class="shrink-0 overflow-hidden"
      >
        <ModbusDrawer
          ref="modbusDrawerRef"
          :port-name="portName"
          :is-connected="isConnected"
          @close="isModbusDrawerOpen = false"
          @log="appendLog"
          @bytes-sent="handleBytesSent"
        />
      </div>

      <!-- Right: Collapsible Command Group Panel -->
      <div
        v-show="isCommandPanelOpen"
        class="w-88 border-l border-zinc-800 flex flex-col shrink-0 overflow-hidden"
      >
        <CommandGroupPanel
          ref="cmdPanelRef"
          :is-connected="isConnected"
          :port-name="portName"
          @log="appendLog"
          @bytes-sent="handleBytesSent"
          @group-changed="(g) => activeGroup = g"
        />
      </div>

      <!-- Right: Collapsible Smart Trigger Panel -->
      <div
        v-show="isTriggerPanelOpen"
        class="flex flex-col shrink-0 overflow-hidden"
      >
        <TriggerPanel
          ref="triggerPanelRef"
          @close="isTriggerPanelOpen = false"
        />
      </div>
    </div>

    <!-- Quick Commands Bar -->
    <div class="bg-zinc-900/70 border-t border-zinc-800 px-3 py-1 flex items-center gap-1.5 overflow-x-auto select-none">
      <span class="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold shrink-0">
        {{ activeGroup ? activeGroup.name : '快捷指令' }}:
      </span>

      <!-- Commands in active group -->
      <template v-if="activeGroup && activeGroup.commands.length > 0">
        <button
          v-for="cmd in activeGroup.commands"
          :key="cmd.id"
          @click="handleSendSingleGroupCommand(cmd)"
          :disabled="!isConnected"
          :title="`[单击单发] ${cmd.label} | ${cmd.payload} (${cmd.format}, ${cmd.lineEnding})`"
          class="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-[10.5px] border border-zinc-700/60 transition-colors disabled:opacity-40 flex items-center gap-1 shrink-0 group/btn"
        >
          <span class="font-medium group-hover/btn:text-white">{{ cmd.label }}</span>
          <span
            class="text-[9px] px-1 rounded font-mono font-bold"
            :class="{
              'text-cyan-400 bg-cyan-950/80 border border-cyan-800/40': cmd.lineEnding === 'crlf',
              'text-blue-400 bg-blue-950/80 border border-blue-800/40': cmd.lineEnding === 'lf',
              'text-teal-400 bg-teal-950/80 border border-teal-800/40': cmd.lineEnding === 'cr',
              'text-amber-400 bg-amber-950/80 border border-amber-800/40': cmd.lineEnding === 'none' && cmd.format === 'string',
              'text-purple-400 bg-purple-950/80 border border-purple-800/40': cmd.format === 'hex',
            }"
          >
            {{ cmd.format === 'hex' ? 'HEX' : cmd.lineEnding === 'crlf' ? '+CRLF' : cmd.lineEnding === 'lf' ? '+LF' : cmd.lineEnding === 'cr' ? '+CR' : 'RAW' }}
          </span>
        </button>
      </template>

      <!-- Fallback default buttons if no group -->
      <template v-else>
        <button
          v-for="cmd in ['help', 'AT', 'reboot', 'status', 'version']"
          :key="cmd"
          @click="handleSendMessage(cmd)"
          :disabled="!isConnected"
          class="px-2 py-0.5 rounded bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-[10.5px] border border-zinc-700/60 transition-colors disabled:opacity-40 shrink-0"
        >
          {{ cmd }}
        </button>
      </template>

      <!-- Toggle command group panel button -->
      <button
        @click="isCommandPanelOpen = !isCommandPanelOpen"
        class="ml-auto px-2 py-0.5 rounded text-[10.5px] text-emerald-400 hover:bg-emerald-950/60 border border-emerald-800/40 transition-colors shrink-0 flex items-center gap-1 font-medium"
      >
        <Layers class="w-3 h-3" />
        <span>{{ isCommandPanelOpen ? '隐藏抽屉' : '管理命令组' }}</span>
      </button>
    </div>

    <!-- Bottom Input & Send Bar -->
    <div class="bg-zinc-900 border-t border-zinc-800 p-2.5 flex items-center gap-2 select-none">
      <select
        v-model="inputMode"
        class="bg-zinc-950 border border-zinc-800 text-zinc-200 text-xs py-1.5 px-2 rounded outline-none"
      >
        <option value="string">文本 (String)</option>
        <option value="hex">HEX 格式</option>
      </select>

      <select
        v-if="inputMode === 'string'"
        v-model="lineEnding"
        class="bg-zinc-950 border border-zinc-800 text-zinc-200 text-xs py-1.5 px-2 rounded outline-none"
      >
        <option value="crlf">+CRLF (\r\n)</option>
        <option value="lf">+LF (\n)</option>
        <option value="cr">+CR (\r)</option>
        <option value="none">无换行</option>
      </select>

      <!-- Automatic Checksum Append Selector -->
      <select
        v-model="checksumAlgo"
        class="bg-zinc-950 border border-zinc-800 text-[11px] py-1.5 px-2 rounded outline-none font-mono transition-colors"
        :class="checksumAlgo !== 'none' ? 'text-amber-400 border-amber-700/80 font-bold bg-amber-950/30' : 'text-zinc-400'"
        title="发送时在数据末尾自动追加校验码 (Rust 原生高性能查表法加速)"
      >
        <option value="none">校验: 无</option>
        <option value="modbus_crc16">校验: Modbus CRC16 (低位在前)</option>
        <option value="crc16_ccitt">校验: CRC16-CCITT / XModem</option>
        <option value="checksum8">校验: Checksum-8 (累加和)</option>
        <option value="xor8">校验: XOR-8 (异或和)</option>
      </select>

      <div class="flex-1 relative">
        <input
          v-model="inputMessage"
          @keydown.enter="handleSendMessage()"
          type="text"
          :placeholder="inputMode === 'hex' ? '输入HEX字节，如: 01 03 00 00 00 02 C4 0B' : '输入发送指令，回车直接发送...'"
          class="w-full bg-zinc-950 border border-zinc-800 focus:border-emerald-500 rounded px-3 py-1.5 text-xs text-zinc-100 placeholder-zinc-600 outline-none transition-colors"
          :disabled="!isConnected"
        />
      </div>

      <button
        @click="handleSendMessage()"
        :disabled="!isConnected || !inputMessage"
        class="flex items-center gap-1 px-4 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded text-xs font-semibold transition-colors disabled:opacity-40 disabled:hover:bg-emerald-600"
      >
        <Send class="w-3.5 h-3.5" />
        <span>发送</span>
      </button>
    </div>
  </div>
</template>
