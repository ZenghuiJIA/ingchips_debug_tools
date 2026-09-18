<script setup lang="ts">
import { ref, shallowRef, onMounted, onUnmounted, nextTick } from 'vue';
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
  Zap,
  Activity
} from '@lucide/vue';
import CommandGroupPanel from './CommandGroupPanel.vue';
import TriggerPanel from './TriggerPanel.vue';
import { encodeCommand } from '../utils/commandEncoder';
import type { CommandGroup, CommandItem, TriggerRule } from '../types';

const props = defineProps<{
  isConnected: boolean;
}>();

const emit = defineEmits<{
  (e: 'switch-tab', tab: string): void;
}>();

const isCommandPanelOpen = ref<boolean>(true);
const isTriggerPanelOpen = ref<boolean>(false);
const cmdPanelRef = ref<any>(null);
const triggerPanelRef = ref<any>(null);
const activeGroup = ref<CommandGroup | null>(null);

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
      const sentCount: number = await safeInvoke('send_serial_data', { data: encoded.bytes });
      txBytesCount.value += sentCount;
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
const MAX_LOG_LINES = 2500;

const viewMode = ref<'string' | 'hex'>('string');
const showTimestamps = ref<boolean>(true);
const autoScroll = ref<boolean>(true);

const inputMessage = ref<string>('');
const inputMode = ref<'string' | 'hex'>('string');
const lineEnding = ref<string>('crlf');

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
}

function exportLogs() {
  const content = logs.value.map(l => `[${l.timestamp}] [${l.type.toUpperCase()}] ${l.text}`).join('\n');
  const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `serial_log_${new Date().toISOString().replace(/[:.]/g, '-')}.txt`;
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

  try {
    const sentCount: number = await safeInvoke('send_serial_data', { data: bytes });
    txBytesCount.value += sentCount;
    appendLog(textToSend, 'tx');
    if (customText === undefined) {
      inputMessage.value = '';
    }
  } catch (err: any) {
    appendLog(`发送失败: ${err}`, 'error');
  }
}

onMounted(async () => {
  // Initialize Web Worker
  try {
    worker = new Worker(new URL('../workers/serialParser.worker.ts', import.meta.url), { type: 'module' });
    worker.onmessage = (e) => {
      if (e.data.type === 'formatted_chunk') {
        rxBytesCount.value += e.data.rawLength;
        appendLog(e.data.text, 'rx', e.data.timestamp);
        handleIncomingRxText(e.data.text);
      }
    };
  } catch (err) {
    console.error('Failed to instantiate Web Worker:', err);
  }

  // Listen to Tauri serial-rx event if running in Tauri
  if (isTauri()) {
    try {
      unlistenRx = await listen<SerialRxPayload>('serial-rx', (event) => {
        const raw = new Uint8Array(event.payload.data);
        const ts = formatTimestamp();

        if (worker) {
          worker.postMessage({
            rawBytes: raw,
            mode: viewMode.value,
            timestamp: ts
          });
        } else {
          // Fallback
          const text = new TextDecoder('utf-8', { fatal: false }).decode(raw);
          rxBytesCount.value += raw.length;
          appendLog(text, 'rx', ts);
          handleIncomingRxText(text);
        }
      });
    } catch (err) {
      console.warn('Failed to attach serial-rx listener:', err);
    }
  }
});

onUnmounted(() => {
  if (unlistenRx) unlistenRx();
  if (worker) worker.terminate();
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-mono text-xs">
    <!-- Terminal Header Toolbar -->
    <div class="bg-zinc-900 border-b border-zinc-800 px-3 py-1.5 flex items-center justify-between gap-3 select-none">
      <!-- Left: Title & Mode Selector -->
      <div class="flex items-center gap-2">
        <div class="flex items-center gap-1 text-zinc-300 font-semibold">
          <Terminal class="w-4 h-4 text-emerald-400" />
          <span>串口控制台</span>
        </div>

        <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded p-0.5 ml-2">
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

        <!-- Toggles -->
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

        <!-- Command Group Toggle Button -->
        <button
          @click="isCommandPanelOpen = !isCommandPanelOpen"
          class="px-2 py-0.5 rounded text-[11px] transition-colors border flex items-center gap-1 ml-1"
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

    <!-- Main Center Viewport: Split Terminal Logs & Command Group Drawer -->
    <div class="flex-1 flex overflow-hidden min-h-0">
      <!-- Left: Terminal Log Viewport -->
      <div
        ref="logContainer"
        class="flex-1 overflow-y-auto p-3 space-y-1 select-text bg-zinc-950 font-mono text-[11.5px] leading-relaxed"
      >
        <div v-if="logs.length === 0" class="h-full flex flex-col items-center justify-center text-zinc-600 select-none">
          <Terminal class="w-10 h-10 mb-2 stroke-1 opacity-40" />
          <p>串口就绪，等待数据输入或发送测试命令...</p>
          <p class="text-[10px] text-zinc-700 mt-1">支持 921600 高波特率无损捕获与 Web Worker 异步渲染</p>
        </div>

        <div
          v-for="item in logs"
          :key="item.id"
          class="flex items-start gap-2 hover:bg-zinc-900/50 rounded px-1 -mx-1"
        >
          <!-- Timestamp -->
          <span v-if="showTimestamps" class="text-zinc-600 text-[10px] shrink-0 select-none">
            [{{ item.timestamp }}]
          </span>

          <!-- Direction Badge -->
          <span
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

          <!-- Content -->
          <span
            class="flex-1 break-all whitespace-pre-wrap"
            :class="{
              'text-emerald-300': item.type === 'rx',
              'text-sky-300 font-medium': item.type === 'tx',
              'text-amber-300': item.type === 'info',
              'text-rose-400 font-semibold': item.type === 'error',
            }"
          >{{ item.text }}</span>
        </div>
      </div>

      <!-- Right: Collapsible Command Group Panel -->
      <div
        v-show="isCommandPanelOpen"
        class="w-88 border-l border-zinc-800 flex flex-col shrink-0 overflow-hidden"
      >
        <CommandGroupPanel
          ref="cmdPanelRef"
          :is-connected="isConnected"
          @log="appendLog"
          @bytes-sent="(c) => txBytesCount += c"
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

      <!-- Commands in active group (每个都支持直接单击单独发送!) -->
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
      <!-- Input Format Mode -->
      <select
        v-model="inputMode"
        class="bg-zinc-950 border border-zinc-800 text-zinc-200 text-xs py-1.5 px-2 rounded outline-none"
      >
        <option value="string">文本 (String)</option>
        <option value="hex">HEX 格式</option>
      </select>

      <!-- Line Ending Mode -->
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

      <!-- Input Textbox -->
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

      <!-- Send Button -->
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
