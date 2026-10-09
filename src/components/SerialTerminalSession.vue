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
  Sliders,
  Cpu
} from '@lucide/vue';
import CommandGroupPanel from './CommandGroupPanel.vue';
import TriggerPanel from './TriggerPanel.vue';
import SerialXtermView from './SerialXtermView.vue';
import ModbusDrawer from './ModbusDrawer.vue';
import ProtocolDashboard from './ProtocolDashboard.vue';
import IngSerialFlasher from './IngSerialFlasher.vue';
import { encodeCommand } from '../utils/commandEncoder';
import { appendChecksum, type ChecksumAlgorithm } from '../utils/crc';
import { t } from '../utils/i18n';
import type { CommandGroup, CommandItem, TriggerRule, PortInfo } from '../types';

const props = defineProps<{
  tabId?: string;
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
    appendLog(t('term_log_pin_dtr', { val: next ? t('term_log_dtr_low') : t('term_log_dtr_high') }), 'info');
  } catch (err) {
    appendLog(t('term_log_set_dtr_fail', { err: String(err) }), 'error');
  }
}

async function toggleRts() {
  if (!props.isConnected) return;
  const next = !rtsState.value;
  try {
    await safeInvoke('set_rts', { level: next, portName: props.portName });
    rtsState.value = next;
    appendLog(t('term_log_pin_rts', { val: next ? t('term_log_rts_boot') : t('term_log_rts_norm') }), 'info');
  } catch (err) {
    appendLog(t('term_log_set_rts_fail', { err: String(err) }), 'error');
  }
}

async function triggerReset(seqType: string) {
  if (!props.isConnected) return;
  if (!props.isDaplink) {
    alert(t('term_not_daplink_tip'));
    return;
  }
  isResetting.value = true;
  try {
    await safeInvoke('execute_reset_sequence', { seqType, portName: props.portName });
    appendLog(t('term_log_reset_sent', { 
      port: props.portName, 
      seq: seqType === 'bootloader_reset' ? t('term_seq_boot') : t('term_seq_normal') 
    }), 'info');
    await refreshPinStates();
  } catch (err) {
    appendLog(t('term_log_reset_fail', { err: String(err) }), 'error');
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
const isIngFlasherOpen = ref<boolean>(false);
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
      appendLog(t('term_log_trigger_hit', { name: rule.name, text: encoded.textDisplay }), 'tx');
    } catch (err) {
      appendLog(t('term_log_trigger_fail', { name: rule.name, err: String(err) }), 'error');
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
let unlistenDisconnect: UnlistenFn | null = null;
let unlistenFlashActive: UnlistenFn | null = null;
let unlistenFlashDone: UnlistenFn | null = null;
let worker: Worker | null = null;

const isFlashingActive = ref<boolean>(false);

// Right-click context menu state
const contextMenuVisible = ref<boolean>(false);
const contextMenuX = ref<number>(0);
const contextMenuY = ref<number>(0);

function handleContextMenu(e: MouseEvent) {
  e.preventDefault();
  contextMenuX.value = e.clientX;
  contextMenuY.value = e.clientY;
  contextMenuVisible.value = true;
}

function closeContextMenu() {
  contextMenuVisible.value = false;
}

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
  if (xtermRef.value) {
    try {
      if (typeof xtermRef.value.clear === 'function') {
        xtermRef.value.clear();
      } else if (typeof xtermRef.value.clearTerminal === 'function') {
        xtermRef.value.clearTerminal();
      }
    } catch (_) {}
  }
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
      appendLog(t('term_log_invalid_hex'), 'error');
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
      appendLog(`${textToSend} ${t('term_log_checksum_appended', { hex: displayHex })}`, 'tx');
    } else {
      appendLog(textToSend, 'tx');
    }
    if (customText === undefined) {
      inputMessage.value = '';
    }
  } catch (err: any) {
    appendLog(t('term_log_send_fail', { err: String(err) }), 'error');
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

      unlistenDisconnect = await listen<{ port: string; reason: string }>('serial-disconnected', (event) => {
        if (event.payload.port && event.payload.port === props.portName) {
          appendLog(t('term_log_disconnected', { port: props.portName }), 'error');
          if (props.isConnected) {
            emit('toggle-connection');
          }
        }
      });

      unlistenFlashActive = await listen<{ port: string; original_baud?: number; message: string }>('serial-flash-active', (event) => {
        if (event.payload.port && event.payload.port === props.portName) {
          isFlashingActive.value = true;
          appendLog(t('term_log_flash_active', { message: event.payload.message }), 'info');
        }
      });

      unlistenFlashDone = await listen<{ port: string; original_baud?: number; message: string }>('serial-flash-done', (event) => {
        if (event.payload.port && event.payload.port === props.portName) {
          isFlashingActive.value = false;
          appendLog(t('term_log_flash_done', { message: event.payload.message }), 'info');
          if (event.payload.original_baud && event.payload.original_baud !== props.baudRate) {
            emit('change-baud', event.payload.original_baud);
          }
        }
      });
    } catch (err) {
      console.warn('Failed to attach serial event listeners:', err);
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
  if (unlistenDisconnect) unlistenDisconnect();
  if (unlistenFlashActive) unlistenFlashActive();
  if (unlistenFlashDone) unlistenFlashDone();
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
            :title="t('term_switch_port_tip')"
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
            :title="isConnected ? t('term_baud_adjust_tip') : t('term_baud_set_tip')"
          >
            <option v-for="b in baudRates" :key="b" :value="b">
              {{ b }}
            </option>
          </select>

          <!-- Direct Open / Close Port Button inside Tab -->
          <button
            @click="emit('toggle-connection')"
            :disabled="isFlashingActive"
            class="flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-semibold transition-colors border shadow-xs ml-0.5 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            :class="isFlashingActive
              ? 'bg-amber-950/80 text-amber-300 border-amber-800 animate-pulse'
              : isConnected 
                ? 'bg-rose-950/80 text-rose-300 border-rose-800 hover:bg-rose-900' 
                : 'bg-emerald-950/90 text-emerald-300 border-emerald-700 hover:bg-emerald-900'"
            :title="isFlashingActive ? t('term_flash_running_tip') : (isConnected ? t('term_close_port_tip') : t('term_open_port_tip'))"
          >
            <Power class="w-3 h-3" />
            <span>{{ isFlashingActive ? t('term_flashing') : (isConnected ? t('term_close') : t('term_open')) }}</span>
          </button>
        </div>

        <!-- Hardware Pin Controls inside Tab (DTR / RTS / Reset) -->
        <div v-if="!portName.startsWith('RTT')" class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5">
          <!-- DTR Button: DTR 1 = RESET low, DTR 0 = release -->
          <button
            @click="toggleDtr"
            :disabled="!isConnected"
            :title="t('term_pin_dtr_title')"
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
            :title="t('term_pin_rts_title')"
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
              :title="t('term_reset_normal_tip')"
            >
              <RotateCcw class="w-2.5 h-2.5" :class="{ 'animate-spin': isResetting }" />
              <span>{{ t('term_reset') }}</span>
            </button>
            <button
              @click="triggerReset('bootloader_reset')"
              :disabled="!isConnected || isResetting"
              class="flex items-center gap-1 px-1.5 py-0.2 rounded text-[10px] bg-amber-950/60 hover:bg-amber-900 text-amber-300 border border-amber-800/60 transition-colors disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
              :title="t('term_reset_boot_tip')"
            >
              <Zap class="w-2.5 h-2.5 text-amber-400" />
              <span>{{ t('term_boot') }}</span>
            </button>
          </div>
        </div>

        <!-- Session Mode Switcher: Log Stream vs VT100 Terminal -->
        <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded p-0.5 ml-1">
          <button
            @click="sessionMode = 'log'"
            class="px-2 py-0.5 rounded text-[11px] transition-colors"
            :class="sessionMode === 'log' ? 'bg-zinc-800 text-emerald-400 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            :title="t('term_log_mode_tip')"
          >
            {{ t('term_log_stream') }}
          </button>
          <button
            @click="sessionMode = 'vt100'"
            class="px-2 py-0.5 rounded text-[11px] transition-colors flex items-center gap-1"
            :class="sessionMode === 'vt100' ? 'bg-zinc-800 text-cyan-400 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            :title="t('term_vt100_mode_tip')"
          >
            <Terminal class="w-3 h-3" />
            <span>{{ t('term_vt100') }}</span>
          </button>
        </div>

        <div v-show="sessionMode === 'log'" class="flex items-center bg-zinc-950 border border-zinc-800 rounded p-0.5 ml-1">
          <button
            @click="viewMode = 'string'"
            class="px-2 py-0.5 rounded text-[11px] transition-colors"
            :class="viewMode === 'string' ? 'bg-zinc-800 text-emerald-400 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
          >
            {{ t('term_ascii') }}
          </button>
          <button
            @click="viewMode = 'hex'"
            class="px-2 py-0.5 rounded text-[11px] transition-colors flex items-center gap-1"
            :class="viewMode === 'hex' ? 'bg-zinc-800 text-emerald-400 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
          >
            <Binary class="w-3 h-3" />
            <span>{{ t('term_hex') }}</span>
          </button>
        </div>

        <!-- Toggles for Log Stream -->
        <template v-if="sessionMode === 'log'">
          <label class="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-200 cursor-pointer ml-1">
            <input type="checkbox" v-model="showTimestamps" class="rounded bg-zinc-800 border-zinc-700 text-emerald-500 focus:ring-0">
            <Clock class="w-3 h-3" />
            <span>{{ t('term_timestamps') }}</span>
          </label>

          <label class="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-200 cursor-pointer">
            <input type="checkbox" v-model="autoScroll" class="rounded bg-zinc-800 border-zinc-700 text-emerald-500 focus:ring-0">
            <ArrowDown class="w-3 h-3" />
            <span>{{ t('term_autoscroll') }}</span>
          </label>

          <label class="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-200 cursor-pointer">
            <input type="checkbox" v-model="autoWrap" class="rounded bg-zinc-800 border-zinc-700 text-emerald-500 focus:ring-0">
            <WrapText class="w-3 h-3" />
            <span>{{ t('term_autowrap') }}</span>
          </label>
        </template>

        <!-- Protocol Dashboard Toggle Button -->
        <button
          @click="isDashboardOpen = !isDashboardOpen"
          class="px-2 py-0.5 rounded text-[11px] transition-colors border flex items-center gap-1 ml-1"
          :class="isDashboardOpen ? 'bg-emerald-950 text-emerald-300 border-emerald-700/80 font-bold' : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
          :title="t('term_dashboard_tip')"
        >
          <Sliders class="w-3.5 h-3.5 text-emerald-400" />
          <span>{{ t('term_dashboard') }}</span>
        </button>

        <!-- Modbus RTU Drawer Toggle Button -->
        <button
          @click="isModbusDrawerOpen = !isModbusDrawerOpen"
          class="px-2 py-0.5 rounded text-[11px] transition-colors border flex items-center gap-1 ml-0.5"
          :class="isModbusDrawerOpen ? 'bg-amber-950 text-amber-300 border-amber-700/80 font-bold' : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
          :title="t('term_modbus_tip')"
        >
          <Layers class="w-3.5 h-3.5 text-amber-400" />
          <span>{{ t('term_modbus') }}</span>
        </button>

        <!-- Command Group Toggle Button -->
        <button
          @click="isCommandPanelOpen = !isCommandPanelOpen"
          class="px-2 py-0.5 rounded text-[11px] transition-colors border flex items-center gap-1 ml-0.5"
          :class="isCommandPanelOpen ? 'bg-emerald-950 text-emerald-300 border-emerald-700/80 font-bold' : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
          :title="t('term_cmd_group_tip')"
        >
          <Layers class="w-3.5 h-3.5 text-emerald-400" />
          <span>{{ t('term_cmd_group') }} {{ activeGroup ? `(${activeGroup.commands.length})` : '' }}</span>
        </button>

        <!-- Smart Trigger / Auto-Responder Toggle Button -->
        <button
          @click="isTriggerPanelOpen = !isTriggerPanelOpen"
          class="px-2 py-0.5 rounded text-[11px] transition-colors border flex items-center gap-1"
          :class="isTriggerPanelOpen ? 'bg-amber-950 text-amber-300 border-amber-700/80 font-bold' : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
          :title="t('term_trigger_tip')"
        >
          <Zap class="w-3.5 h-3.5 text-amber-400" />
          <span>{{ t('term_auto_reply') }}</span>
        </button>

        <!-- Quick Jump to Waveform Plotter -->
        <button
          @click="emit('switch-tab', 'plotter')"
          class="px-2 py-0.5 rounded text-[11px] bg-zinc-800 hover:bg-zinc-700 text-cyan-300 border border-cyan-800/60 transition-colors flex items-center gap-1 ml-1 cursor-pointer"
          :title="t('term_waveform_tip')"
        >
          <Activity class="w-3.5 h-3.5 text-cyan-400" />
          <span>{{ t('term_waveform') }}</span>
        </button>

        <!-- INGChips 芯片串口烧录面板入口 -->
        <button
          @click="isIngFlasherOpen = true"
          class="px-2 py-0.5 rounded text-[11px] bg-indigo-950/80 hover:bg-indigo-900 text-indigo-300 border border-indigo-700/80 transition-colors flex items-center gap-1 ml-1 cursor-pointer font-medium"
          :title="t('term_ing_flasher_tip')"
        >
          <Cpu class="w-3.5 h-3.5 text-indigo-400" />
          <span>{{ t('term_ing_flasher') }}</span>
        </button>

        <!-- 显式清屏按钮 -->
        <button
          @click="clearLogs"
          class="px-2 py-0.5 rounded text-[11px] bg-zinc-900 hover:bg-zinc-800 text-zinc-300 border border-zinc-700/80 hover:text-rose-300 transition-colors flex items-center gap-1 ml-1 cursor-pointer"
          :title="t('term_clear_screen_tip')"
        >
          <Trash2 class="w-3 h-3 text-rose-400" />
          <span>{{ t('term_clear') }}</span>
        </button>
      </div>

      <!-- Right: Stats & Actions -->
      <div class="flex items-center gap-2">
        <div class="text-[11px] text-zinc-500 flex items-center gap-2 font-mono">
          <span>RX: <strong class="text-zinc-300">{{ rxBytesCount }}</strong> B</span>
          <span>TX: <strong class="text-zinc-300">{{ txBytesCount }}</strong> B</span>
          <span>{{ t('term_lines_count') }}: <strong class="text-zinc-300">{{ logs.length }}</strong></span>
        </div>

        <div class="h-3 w-px bg-zinc-800"></div>

        <button
          @click="copyAllLogs"
          :disabled="logs.length === 0"
          :title="isCopiedAll ? t('term_copied_toast') : t('term_copy_title')"
          class="p-1 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded transition-colors disabled:opacity-40"
        >
          <component :is="isCopiedAll ? Check : Copy" class="w-3.5 h-3.5" :class="{ 'text-emerald-400': isCopiedAll }" />
        </button>

        <button
          @click="exportLogs"
          :title="t('term_export_title')"
          class="p-1 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded transition-colors"
        >
          <Download class="w-3.5 h-3.5" />
        </button>

        <button
          @click="clearLogs"
          :title="t('term_clear_title')"
          class="p-1 text-zinc-400 hover:text-rose-400 hover:bg-zinc-800 rounded transition-colors"
        >
          <Trash2 class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <!-- Main Center Viewport: Split Terminal Logs / VT100 & Drawers -->
    <div class="flex-1 flex overflow-hidden min-h-0">
      <!-- Left: Terminal Log Viewport or VT100 Terminal View -->
      <div
        v-show="sessionMode === 'vt100'"
        class="flex-1 h-full overflow-hidden"
        @contextmenu="handleContextMenu"
      >
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
        @contextmenu="handleContextMenu"
        class="flex-1 overflow-auto p-3 space-y-0.5 select-text bg-zinc-950 font-mono text-[11.5px] leading-relaxed"
      >
        <div v-if="logs.length === 0" class="h-full flex flex-col items-center justify-center text-zinc-600 select-none">
          <Terminal class="w-10 h-10 mb-2 stroke-1 opacity-40" />
          <p>[{{ portName }}] {{ t('term_ready_waiting') }}</p>
          <p class="text-[10px] text-zinc-700 mt-1">{{ t('term_independent_desc') }}</p>
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
        {{ activeGroup ? activeGroup.name : t('term_quick_cmds') }}:
      </span>

      <!-- Commands in active group -->
      <template v-if="activeGroup && activeGroup.commands.length > 0">
        <button
          v-for="cmd in activeGroup.commands"
          :key="cmd.id"
          @click="handleSendSingleGroupCommand(cmd)"
          :disabled="!isConnected"
          :title="`[${t('cmd_single_send')}] ${cmd.label} | ${cmd.payload} (${cmd.format}, ${cmd.lineEnding})`"
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
        <Layers class="w-3.5 h-3.5" />
        <span>{{ isCommandPanelOpen ? t('term_collapse_drawer') : t('term_manage_groups') }}</span>
      </button>
    </div>

    <!-- Bottom Input & Send Bar -->
    <div class="bg-zinc-900 border-t border-zinc-800 p-2.5 flex items-center gap-2 select-none">
      <select
        v-model="inputMode"
        class="bg-zinc-950 border border-zinc-800 text-zinc-200 text-xs py-1.5 px-2 rounded outline-none"
      >
        <option value="string">{{ t('term_ascii') }}</option>
        <option value="hex">{{ t('term_hex') }}</option>
      </select>

      <select
        v-if="inputMode === 'string'"
        v-model="lineEnding"
        class="bg-zinc-950 border border-zinc-800 text-zinc-200 text-xs py-1.5 px-2 rounded outline-none"
      >
        <option value="crlf">+CRLF (\r\n)</option>
        <option value="lf">+LF (\n)</option>
        <option value="cr">+CR (\r)</option>
        <option value="none">{{ t('term_line_ending_none') }}</option>
      </select>

      <!-- Automatic Checksum Append Selector -->
      <select
        v-model="checksumAlgo"
        class="bg-zinc-950 border border-zinc-800 text-[11px] py-1.5 px-2 rounded outline-none font-mono transition-colors"
        :class="checksumAlgo !== 'none' ? 'text-amber-400 border-amber-700/80 font-bold bg-amber-950/30' : 'text-zinc-400'"
        :title="t('term_checksum_selector_tip')"
      >
        <option value="none">{{ t('term_chk_none') }}</option>
        <option value="modbus_crc16">{{ t('term_chk_modbus') }}</option>
        <option value="crc16_ccitt">{{ t('term_chk_crc16') }}</option>
        <option value="checksum8">{{ t('term_chk_sum8') }}</option>
        <option value="xor8">{{ t('term_chk_xor8') }}</option>
      </select>

      <div class="flex-1 relative">
        <input
          v-model="inputMessage"
          @keydown.enter="handleSendMessage()"
          type="text"
          :placeholder="inputMode === 'hex' ? t('term_input_placeholder_hex') : t('term_input_placeholder_str')"
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
        <span>{{ t('term_send') }}</span>
      </button>
    </div>

    <!-- INGChips Serial Flasher Modal -->
    <IngSerialFlasher
      :tab-id="tabId"
      :port-name="portName"
      :is-open="isIngFlasherOpen"
      @close="isIngFlasherOpen = false"
    />

    <!-- Right-click Context Menu for Clearing & Copying Logs -->
    <div
      v-if="contextMenuVisible"
      class="fixed inset-0 z-50 select-none"
      @click="closeContextMenu"
      @contextmenu.prevent="closeContextMenu"
    >
      <div
        class="absolute bg-zinc-900 border border-zinc-700/80 rounded-lg shadow-2xl py-1 w-44 text-xs text-zinc-200 divide-y divide-zinc-800"
        :style="{ left: `${contextMenuX}px`, top: `${contextMenuY}px` }"
        @click.stop
      >
        <div class="py-0.5">
          <button
            @click="clearLogs(); closeContextMenu()"
            class="w-full text-left px-3 py-1.5 hover:bg-zinc-800 hover:text-rose-400 flex items-center gap-2 cursor-pointer transition-colors"
          >
            <Trash2 class="w-3.5 h-3.5 text-rose-400" />
            <span>{{ t('term_menu_clear_all') }}</span>
          </button>
        </div>
        <div class="py-0.5">
          <button
            @click="copyAllLogs(); closeContextMenu()"
            class="w-full text-left px-3 py-1.5 hover:bg-zinc-800 hover:text-zinc-100 flex items-center gap-2 cursor-pointer transition-colors"
          >
            <Copy class="w-3.5 h-3.5 text-emerald-400" />
            <span>{{ t('term_menu_copy_all') }}</span>
          </button>
          <button
            @click="exportLogs(); closeContextMenu()"
            class="w-full text-left px-3 py-1.5 hover:bg-zinc-800 hover:text-zinc-100 flex items-center gap-2 cursor-pointer transition-colors"
          >
            <Download class="w-3.5 h-3.5 text-sky-400" />
            <span>{{ t('term_menu_export_file') }}</span>
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
