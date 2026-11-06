<script setup lang="ts">
import { ref, shallowRef, computed, watch, onMounted, onUnmounted, nextTick } from 'vue';
import { appendBoundedLog, filterLogs, highlightParts } from '../utils/serialLog';
import { DEFAULT_SERIAL_APPEARANCE, loadSerialAppearance, saveSerialAppearance, normalizeSerialAppearance, serialLogStyle, serialLogColor, type SerialAppearance } from '../utils/serialAppearance';
import { serialIdentity, guardedSend, type CaptureStatus, type CapturePage, type RawEvent } from '../utils/serialSession';
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
import CaptureAnalysis from './CaptureAnalysis.vue';
import TriggerPanel from './TriggerPanel.vue';
import SerialXtermView from './SerialXtermView.vue';
import ModbusDrawer from './ModbusDrawer.vue';
import ProtocolDashboard from './ProtocolDashboard.vue';
import IngSerialFlasher from './IngSerialFlasher.vue';
import BaudrateSelect from './common/BaudrateSelect.vue';
import ResizableDrawer from './common/ResizableDrawer.vue';
import { encodeCommand } from '../utils/commandEncoder';
import { appendChecksum, type ChecksumAlgorithm } from '../utils/crc';
import { t } from '../utils/i18n';
import type { CommandGroup, CommandItem, TriggerRule, PortInfo } from '../types';

const props = defineProps<{
  tabId?: string;
  portName: string;
  baudRate: number;
  isConnected: boolean;
  isListening?: boolean;
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

const loadedAppearance = loadSerialAppearance(() => localStorage);
const appearance = ref<SerialAppearance>(loadedAppearance.appearance);
const appearanceError = ref(loadedAppearance.error);
const appearanceOpen = ref(false);
const logAppearanceStyle = computed(() => serialLogStyle(appearance.value));
function appearanceLabel(key: string, fallback: string): string {
  const text = t(key);
  return text === key ? fallback : text;
}
function updateAppearance(key: keyof SerialAppearance, event: Event) {
  const input = event.target as HTMLInputElement;
  if (!input.reportValidity()) return;
  appearance.value = normalizeSerialAppearance({ ...appearance.value, [key]: key === 'fontSize' ? Number(input.value) : input.value });
}
function resetAppearance() { appearance.value = { ...DEFAULT_SERIAL_APPEARANCE }; }
watch(appearance, value => { appearanceError.value = saveSerialAppearance(() => localStorage, value); }, { deep: true });

const checksumAlgo = ref<ChecksumAlgorithm>('none');

function handleSendSingleGroupCommand(cmd: CommandItem) {
  if (cmdPanelRef.value) {
    cmdPanelRef.value.sendSingleCommand(cmd);
  }
}

async function executeTriggerResponse(rule: TriggerRule, sourceSession?: string | null) {
  if (!isTauri()) return;
  const targetPort = props.portName;
  const identity = await serialIdentity(targetPort);
  if (sourceSession && identity !== sourceSession) throw new Error('旧连接触发事件已拒绝');
  if (triggerTimers.size >= 100) throw new Error('自动应答待发送队列已满，请降低触发频率');
  const encoded = encodeCommand({
    id: rule.id,
    label: rule.name,
    payload: rule.responsePayload,
    format: rule.responseFormat,
    lineEnding: rule.responseEnding,
    delayAfterMs: 0,
    enabled: true
  });

  const timer = setTimeout(async () => {
    triggerTimers.delete(timer);
    if (!props.isConnected || props.portName !== targetPort) return;
    try {
      const sentCount = await guardedSend(targetPort, identity, encoded.bytes);
      txBytesCount.value += sentCount;
      emit('update-stats', { rx: rxBytesCount.value, tx: txBytesCount.value });
      appendLog(t('term_log_trigger_hit', { name: rule.name, text: encoded.textDisplay }), 'tx');
    } catch (err) {
      appendLog(t('term_log_trigger_fail', { name: rule.name, err: String(err) }), 'error');
    }
  }, rule.delayMs);
  triggerTimers.add(timer);
}

const triggerTimers = new Set<ReturnType<typeof setTimeout>>();
const rxDecoder = new TextDecoder('utf-8', { fatal: false });
function handleIncomingRxText(text: string, sourceSession?: string | null) {
  if (triggerPanelRef.value) {
    try {
      for (const rule of triggerPanelRef.value.checkAndMatchTriggers(text))
        executeTriggerResponse(rule, sourceSession).catch(error => appendLog(String(error), 'error'));
    } catch (error) { appendLog(String(error), 'error'); }
  }
}

const logContainer = ref<HTMLElement | null>(null);
const logs = shallowRef<SerialLogItem[]>([]);
let nextLogId = 1;
let pendingLogQueue: SerialLogItem[] = [];
let logFlushRafId: number | null = null;
// Optimized: Limit to 1200 lines per tab to keep DOM node count < 2000 and prevent Renderer memory bloat
const includeText = ref('');
const excludeText = ref('');
const regexFilter = ref(false);
const bookmarkOnly = ref(false);
const bookmarks = ref<SerialLogItem[]>([]);
const filterError = ref('');
const visibleLogs = computed(() => {
  try { filterError.value = ''; return filterLogs(bookmarkOnly.value ? bookmarks.value : logs.value, includeText.value, excludeText.value, regexFilter.value); }
  catch (error) { filterError.value = String(error); return []; }
});
function bookmark(item: SerialLogItem) {
  bookmarks.value = bookmarks.value.some(x => x.id === item.id) ? bookmarks.value.filter(x => x.id !== item.id) : [...bookmarks.value, { ...item }].slice(-200);
}
const captureStatus = ref<CaptureStatus | null>(null);
const analysisOpen = ref(false);
const backendJournal = computed(() => isTauri() && !/^(TCP|UDP)/.test(props.portName));
let captureCursor = 0;
let captureSession = '';
let capturePolling = false;
const retainedRaw = shallowRef<RawEvent[]>([]);
let captureDecoder = new TextDecoder();
function renderCaptured(event: RawEvent) {
  const data = Uint8Array.from(event.data.match(/.{2}/g) || [], b => parseInt(b, 16));
  const text = event.message || (viewMode.value === 'hex' ? (event.data.match(/.{2}/g)?.join(' ').toUpperCase() || '') + ' ' : event.direction === 'RX' ? captureDecoder.decode(data, { stream: true }) : new TextDecoder().decode(data));
  pendingLogQueue.push({ id: nextLogId++, timestamp: new Date(event.wall_time_ms).toLocaleTimeString(), text,
    type: event.direction === 'RX' ? 'rx' : event.direction === 'TX' ? 'tx' : event.direction === 'ERROR' ? 'error' : 'info' });
}
function redrawCaptured() {
  if (!backendJournal.value) return;
  pendingLogQueue = [];
  logs.value = []; captureDecoder = new TextDecoder();
  for (const event of retainedRaw.value) renderCaptured(event);
  flushLogQueue(false);
}
let captureTimer: ReturnType<typeof setInterval> | undefined;
async function refreshCapture() {
  if (!backendJournal.value || capturePolling) return;
  capturePolling = true; const port = props.portName;
  try {
    let page = await safeInvoke<CapturePage>('serial_capture_read', { portName: port, after: captureCursor, limit: 500 });
    if (props.portName !== port) return;
    if (captureSession !== page.status.session_id) {
      captureSession = page.status.session_id; captureCursor = 0; retainedRaw.value = []; logs.value = []; captureDecoder = new TextDecoder();
      page = await safeInvoke<CapturePage>('serial_capture_read', { portName: port, after: 0, limit: 500 });
      if (props.portName !== port) return;
    }
    captureStatus.value = page.status;
    if (page.gap) appendLog('后台环形窗口已覆盖部分历史；完整内容请读取录制文件', 'error');
    captureCursor = page.cursor;
    const retained = [...retainedRaw.value, ...page.events];
    let size = retained.reduce((n,e) => n + e.data.length + 256, 0); let cut = 0;
    while (size > 2*1024*1024 && cut < retained.length) { size -= retained[cut]!.data.length + 256; cut++; }
    retainedRaw.value = retained.slice(cut);
    if (sessionMode.value === 'log') {
      for (const event of page.events) renderCaptured(event);
      flushLogQueue();
    }
    // Empty journal polls must not pull the user away from scrollback.
  } catch { captureStatus.value = null; }
  finally { capturePolling = false; }
}
async function toggleRecording() {
  try { captureStatus.value = await safeInvoke<CaptureStatus>('serial_capture_record', { portName: props.portName, start: !captureStatus.value?.recording }); }
  catch (error) { appendLog(String(error), 'error'); }
}
const sendHistory = ref<{ text: string; format: 'string' | 'hex'; ending: string }[]>([]);
try { sendHistory.value = JSON.parse(localStorage.getItem('hil.send_history.v1') || '[]').slice(0, 100); } catch { /* damaged preferences */ }
function recallHistory(index: string) {
  const item = sendHistory.value[Number(index)]; if (!item) return;
  inputMessage.value = item.text; inputMode.value = item.format; lineEnding.value = item.ending;
}

// Preferences persistence keys
const PREF_KEY_TIMESTAMPS = 'ai_hil_pref_timestamps';
const PREF_KEY_AUTOSCROLL = 'ai_hil_pref_autoscroll';
const PREF_KEY_AUTOWRAP = 'ai_hil_pref_autowrap';
const PREF_KEY_VIEWMODE = 'ai_hil_pref_viewmode';
const PREF_KEY_LINE_ENDING = 'ai_hil_pref_line_ending';

const viewMode = ref<'string' | 'hex'>(
  (localStorage.getItem(PREF_KEY_VIEWMODE) as 'string' | 'hex') || 'string'
);
watch(viewMode, redrawCaptured);
watch(sessionMode, redrawCaptured);
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
    if (autoScroll.value && sessionMode.value === 'log' && logContainer.value) {
      logContainer.value.scrollTop = logContainer.value.scrollHeight;
    }
  });
}

function appendLog(text: string, type: 'rx' | 'tx' | 'info' | 'error', customTime?: string) {
  if (type === 'tx' && backendJournal.value) return;
  pendingLogQueue.push({ id: nextLogId++, timestamp: customTime || formatTimestamp(), text, type });
  if (pendingLogQueue.length >= 40) {
    flushLogQueue();
  } else {
    scheduleLogFlush();
  }
}

function flushLogQueue(followNewMessages = true) {
  if (logFlushRafId !== null) {
    cancelAnimationFrame(logFlushRafId);
    logFlushRafId = null;
  }
  if (pendingLogQueue.length === 0) return;
  let cur = logs.value;
  for (const item of pendingLogQueue) {
    cur = appendBoundedLog(cur, item);
  }
  pendingLogQueue = [];
  logs.value = cur;
  if (followNewMessages) scrollToBottom();
}

function scheduleLogFlush() {
  if (logFlushRafId === null) {
    logFlushRafId = requestAnimationFrame(() => {
      logFlushRafId = null;
      flushLogQueue();
    });
  }
}

function clearLogs() {
  pendingLogQueue = [];
  if (logFlushRafId !== null) {
    cancelAnimationFrame(logFlushRafId);
    logFlushRafId = null;
  }
  retainedRaw.value = [];
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
  safeInvoke('trim_system_memory').catch(() => {});
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
  const targetPort = props.portName;
  let identity: string | null;
  try { identity = await serialIdentity(targetPort); } catch (error) { appendLog(String(error), 'error'); return; }
  const textToSend = customText !== undefined ? customText : inputMessage.value;
  if (!textToSend || !props.isConnected) return;

  let bytes: number[] = [];

  if (inputMode.value === 'hex' && customText === undefined) {
    const cleanHex = textToSend.replace(/\s+/g, '');
    if (!/^[0-9a-fA-F]*$/.test(cleanHex) || cleanHex.length % 2) {
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
    const sentCount = await guardedSend(targetPort, identity, bytes);
    sendHistory.value = [{ text: textToSend, format: inputMode.value, ending: lineEnding.value }, ...sendHistory.value.filter(x => x.text !== textToSend)].slice(0, 100);
    localStorage.setItem('hil.send_history.v1', JSON.stringify(sendHistory.value));
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
  await refreshCapture();
  captureTimer = setInterval(refreshCapture, 150);
  // Initialize Web Worker
  try {
    worker = new Worker(new URL('../workers/serialParser.worker.ts', import.meta.url), { type: 'module' });
    worker.onmessage = (e) => {
      if (e.data.type === 'formatted_chunk') {
        rxBytesCount.value += e.data.rawLength;
        emit('update-stats', { rx: rxBytesCount.value, tx: txBytesCount.value });
        appendLog(e.data.text, 'rx', e.data.timestamp);
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
        const decodedRx = rxDecoder.decode(raw, { stream: true });
        handleIncomingRxText(decodedRx, event.payload.session_id);

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
        if (backendJournal.value) {
          rxBytesCount.value += raw.length;
          emit('update-stats', { rx: rxBytesCount.value, tx: txBytesCount.value });
          return;
        }
        if (worker) {
          worker.postMessage({
            rawBytes: raw,
            mode: viewMode.value,
            timestamp: ts
          });
        } else {
          const text = viewMode.value === 'hex'
            ? Array.from(raw, byte => byte.toString(16).padStart(2, '0').toUpperCase()).join(' ') + ' '
            : decodedRx;
          rxBytesCount.value += raw.length;
          emit('update-stats', { rx: rxBytesCount.value, tx: txBytesCount.value });
          appendLog(text, 'rx', ts);
        }
      });

      unlistenDisconnect = await listen<{ port: string; reason: string }>('serial-disconnected', (event) => {
        if (event.payload.port && event.payload.port === props.portName) {
          appendLog(t('term_log_disconnected', { port: props.portName }), 'error');
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
    for (const timer of triggerTimers) clearTimeout(timer);
    triggerTimers.clear();
    triggerPanelRef.value?.suspendMatcher();
    rxDecoder.decode();
    dtrState.value = false;
    rtsState.value = false;
  }
});
watch(() => props.portName, () => {
  for (const timer of triggerTimers) clearTimeout(timer);
  triggerTimers.clear(); triggerPanelRef.value?.suspendMatcher(); rxDecoder.decode();
  refreshCapture();
});

onUnmounted(() => {
  if (captureTimer) clearInterval(captureTimer);
  for (const timer of triggerTimers) clearTimeout(timer);
  triggerTimers.clear();
  if (unlistenRx) unlistenRx();
  if (unlistenDisconnect) unlistenDisconnect();
  if (unlistenFlashActive) unlistenFlashActive();
  if (unlistenFlashDone) unlistenFlashDone();
  if (worker) {
    worker.terminate();
    worker = null;
  }
  if (logFlushRafId !== null) {
    cancelAnimationFrame(logFlushRafId);
    logFlushRafId = null;
  }
  pendingLogQueue = [];
  // Thorough GC release: clear retained log arrays to free DOM and string heap
  logs.value = [];
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-mono text-xs">
    <CaptureAnalysis v-if="analysisOpen" :initial-path="captureStatus?.directory || ''" @close="analysisOpen = false" />
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

          <!-- Switch Baud Rate Dropdown & Custom Input (Enabled even if connected, supports runtime adjustment) -->
          <BaudrateSelect
            v-if="!portName.startsWith('RTT')"
            :model-value="baudRate"
            @update:model-value="(b) => emit('change-baud', b)"
          />

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
            <span>{{ isFlashingActive ? t('term_flashing') : (isListening ? '停止监听' : (isConnected ? t('term_close') : t('term_open'))) }}</span>
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
            <input type="checkbox" v-model="autoWrap" class="rounded bg-zinc-800 border-zinc-700 text-emerald-500 focus:ring-0">
            <WrapText class="w-3 h-3" />
            <span>{{ t('term_autowrap') }}</span>
          </label>
        </template>

        <label class="flex items-center gap-1 text-[11px] text-zinc-400 hover:text-zinc-200 cursor-pointer" :title="appearanceLabel('term_autoscroll_new_message_tip', '仅新消息到达时滚动到底部；空闲时可向上阅读历史')">
          <input type="checkbox" v-model="autoScroll" class="rounded bg-zinc-800 border-zinc-700 text-emerald-500 focus:ring-0">
          <ArrowDown class="w-3 h-3" />
          <span>{{ t('term_autoscroll') }}</span>
        </label>
        <button @click="appearanceOpen = !appearanceOpen" :aria-expanded="appearanceOpen" class="px-2 py-0.5 rounded text-[11px] bg-zinc-800 text-zinc-300 border border-zinc-700 hover:bg-zinc-700">
          {{ appearanceLabel('term_appearance', '外观') }}
        </button>

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

    <div v-if="appearanceOpen" class="px-3 py-2 flex flex-wrap items-center gap-3 border-b border-zinc-800 bg-zinc-900 text-[11px]">
      <label class="flex items-center gap-1">{{ appearanceLabel('term_font_family', '字体') }}
        <input :value="appearance.fontFamily" @change="updateAppearance('fontFamily', $event)" required maxlength="200" class="w-56 bg-zinc-950 border border-zinc-700 rounded px-2 py-1" />
      </label>
      <label class="flex items-center gap-1">{{ appearanceLabel('term_font_size', '字号') }}
        <input type="number" :value="appearance.fontSize" @change="updateAppearance('fontSize', $event)" min="8" max="32" step="0.5" required class="w-16 bg-zinc-950 border border-zinc-700 rounded px-2 py-1" /> px
      </label>
      <label class="flex items-center gap-1">{{ appearanceLabel('term_text_color', '文字 / RX') }}<input type="color" :value="appearance.foreground" @input="updateAppearance('foreground', $event)" class="w-7 h-6" /></label>
      <label class="flex items-center gap-1">{{ appearanceLabel('term_background_color', '背景') }}<input type="color" :value="appearance.background" @input="updateAppearance('background', $event)" class="w-7 h-6" /></label>
      <label class="flex items-center gap-1">TX<input type="color" :value="appearance.txColor" @input="updateAppearance('txColor', $event)" class="w-7 h-6" /></label>
      <label class="flex items-center gap-1">{{ appearanceLabel('term_info_color', '提示') }}<input type="color" :value="appearance.infoColor" @input="updateAppearance('infoColor', $event)" class="w-7 h-6" /></label>
      <label class="flex items-center gap-1">{{ appearanceLabel('term_error_color', '错误') }}<input type="color" :value="appearance.errorColor" @input="updateAppearance('errorColor', $event)" class="w-7 h-6" /></label>
      <button @click="resetAppearance" class="px-2 py-1 bg-zinc-800 rounded">{{ appearanceLabel('term_reset_appearance', '恢复默认外观') }}</button>
      <span class="text-zinc-400">{{ appearanceLabel('term_appearance_scope', '文本 / HEX / VT100 共用；VT100 保留设备 ANSI 颜色') }}</span>
    </div>
    <p v-if="appearanceError" role="alert" class="px-3 py-1 text-amber-300">{{ appearanceLabel('term_appearance_storage_error', '外观偏好无法读取或保存，本次设置仍可使用：') }} {{ appearanceError }}</p>

    <!-- Main Center Viewport: Split Terminal Logs / VT100 & Drawers -->
    <div class="px-3 py-1.5 flex flex-wrap items-center gap-2 border-b border-zinc-800 bg-zinc-900 text-[11px]">
      <input v-model="includeText" placeholder="搜索 / 高亮" class="bg-zinc-950 border border-zinc-700 px-2 py-1 rounded w-36" />
      <input v-model="excludeText" placeholder="排除内容" class="bg-zinc-950 border border-zinc-700 px-2 py-1 rounded w-28" />
      <label><input type="checkbox" v-model="regexFilter" /> 正则</label>
      <label><input type="checkbox" v-model="bookmarkOnly" /> 书签 {{ bookmarks.length }}</label>
      <button @click="toggleRecording" :disabled="!captureStatus" class="px-2 py-1 rounded bg-zinc-800 disabled:opacity-40">{{ captureStatus?.recording ? '停止后台录制' : '后台录制 RX/TX' }}</button>
      <button @click="analysisOpen = true" class="px-2 py-1 rounded bg-sky-900">查看记录 / 回放</button>
      <select @change="recallHistory(($event.target as HTMLSelectElement).value)" class="bg-zinc-950 border border-zinc-700 rounded max-w-44"><option value="">发送历史（选择仅填入）</option><option v-for="(entry, index) in sendHistory" :key="index" :value="index">{{ entry.text.slice(0, 60) }}</option></select>
      <span v-if="filterError || captureStatus?.error" class="text-rose-400">{{ filterError || captureStatus?.error }}</span>
      <span v-if="captureStatus?.directory" class="select-text text-zinc-400 break-all">{{ captureStatus.directory }}</span>
    </div>
    <div class="flex-1 flex overflow-hidden min-h-0">
      <!-- Left: Terminal Log Viewport or VT100 Terminal View -->
      <div
        v-show="sessionMode === 'vt100'"
        class="flex-1 h-full overflow-hidden"
        @contextmenu="handleContextMenu"
      >
        <SerialXtermView
          ref="xtermRef"
          :appearance="appearance"
          :auto-scroll="autoScroll"
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
        class="flex-1 overflow-auto p-3 space-y-0.5 select-text leading-relaxed"
        :style="logAppearanceStyle"
      >
        <div v-if="logs.length === 0" class="h-full flex flex-col items-center justify-center text-zinc-600 select-none">
          <Terminal class="w-10 h-10 mb-2 stroke-1 opacity-40" />
          <p>[{{ portName }}] {{ t('term_ready_waiting') }}</p>
          <p class="text-[10px] text-zinc-700 mt-1">{{ t('term_independent_desc') }}</p>
        </div>

        <div
          v-for="item in visibleLogs"
          :key="item.id"
          class="flex items-start gap-1.5 hover:bg-zinc-900/50 rounded px-1 -mx-1"
        >
          <!-- Timestamp -->
          <button @click="bookmark(item)" title="保存 / 移除书签" class="text-amber-400 shrink-0">{{ bookmarks.some(b => b.id === item.id) ? '★' : '☆' }}</button>
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
            :style="{ color: serialLogColor(appearance, item.type) }"
            :class="[autoWrap ? 'whitespace-pre-wrap break-all' : 'whitespace-pre overflow-x-visible', { 'font-medium': item.type === 'tx', 'font-semibold': item.type === 'error' }]"
          ><span v-for="(part, index) in highlightParts(item.text, regexFilter ? '' : includeText)" :key="index" :class="part.mark ? 'bg-amber-500/30 text-amber-100' : ''">{{ part.text }}</span></span>
        </div>
      </div>

      <!-- Right: Collapsible Custom Protocol Dashboard (Resizable) -->
      <ResizableDrawer
        v-if="isDashboardOpen"
        storage-key="hil_drawer_width_protocol"
        :min="300"
        :max="900"
        :default-size="420"
        side="left"
      >
        <ProtocolDashboard
          :port-name="portName"
          :baud-rate="baudRate"
          :is-connected="isConnected"
          @close="isDashboardOpen = false"
          @log="appendLog"
          @bytes-sent="handleBytesSent"
        />
      </ResizableDrawer>

      <!-- Right: Collapsible Modbus RTU Drawer (Resizable) -->
      <ResizableDrawer
        v-if="isModbusDrawerOpen"
        storage-key="hil_drawer_width_modbus"
        :min="300"
        :max="850"
        :default-size="380"
        side="left"
      >
        <ModbusDrawer
          ref="modbusDrawerRef"
          :port-name="portName"
          :is-connected="isConnected"
          @close="isModbusDrawerOpen = false"
          @log="appendLog"
          @bytes-sent="handleBytesSent"
        />
      </ResizableDrawer>

      <!-- Right: Collapsible Command Group Panel (Resizable) -->
      <ResizableDrawer
        v-if="isCommandPanelOpen"
        storage-key="hil_drawer_width_commands"
        :min="280"
        :max="750"
        :default-size="350"
        side="left"
      >
        <CommandGroupPanel
          ref="cmdPanelRef"
          :is-connected="isConnected"
          :port-name="portName"
          @log="appendLog"
          @bytes-sent="handleBytesSent"
          @group-changed="(g) => activeGroup = g"
        />
      </ResizableDrawer>

      <!-- Right: Collapsible Smart Trigger Panel (Resizable) -->
      <ResizableDrawer
        v-if="isTriggerPanelOpen"
        storage-key="hil_drawer_width_trigger"
        :min="300"
        :max="850"
        :default-size="384"
        side="left"
      >
        <TriggerPanel
          ref="triggerPanelRef"
          @close="isTriggerPanelOpen = false"
        />
      </ResizableDrawer>
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
