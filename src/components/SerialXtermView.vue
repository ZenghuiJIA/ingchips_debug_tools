<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue';
import { Terminal } from '@xterm/xterm';
import { FitAddon } from '@xterm/addon-fit';
import '@xterm/xterm/css/xterm.css';
import { Trash2, Copy, Check } from '@lucide/vue';
import { safeInvoke } from '../utils/ipc';

const props = defineProps<{
  portName: string;
  isConnected: boolean;
}>();

const emit = defineEmits<{
  (e: 'bytes-sent', count: number): void;
  (e: 'log', text: string, type: 'rx' | 'tx' | 'info' | 'error'): void;
}>();

const terminalRef = ref<HTMLDivElement | null>(null);
let term: Terminal | null = null;
let fitAddon: FitAddon | null = null;
let resizeObserver: ResizeObserver | null = null;

const isCopied = ref<boolean>(false);

function initTerminal() {
  if (!terminalRef.value) return;

  term = new Terminal({
    cursorBlink: true,
    cursorStyle: 'block',
    fontSize: 12,
    fontFamily: 'Consolas, "Fira Code", monospace, "Courier New"',
    theme: {
      background: '#09090b', // zinc-950
      foreground: '#f4f4f5', // zinc-100
      cursor: '#10b981',     // emerald-500
      cursorAccent: '#000000',
      selectionBackground: '#047857',
      black: '#18181b',
      red: '#f43f5e',
      green: '#10b981',
      yellow: '#f59e0b',
      blue: '#0284c7',
      magenta: '#a855f7',
      cyan: '#06b6d4',
      white: '#fafafa',
      brightBlack: '#52525b',
      brightRed: '#fb7185',
      brightGreen: '#34d399',
      brightYellow: '#fbbf24',
      brightBlue: '#38bdf8',
      brightMagenta: '#c084fc',
      brightCyan: '#22d3ee',
      brightWhite: '#ffffff',
    },
    convertEol: true,
    scrollback: 5000,
  });

  fitAddon = new FitAddon();
  term.loadAddon(fitAddon);
  term.open(terminalRef.value);

  // Hook terminal keyboard data sending to serial
  term.onData(async (data: string) => {
    if (!props.isConnected) {
      term?.write('\r\n\x1b[33m[AI-HIL] 串口未连接，无法发送输入\x1b[0m\r\n');
      return;
    }
    try {
      const bytes = Array.from(new TextEncoder().encode(data));
      const sentCount: number = await safeInvoke('send_serial_data', {
        data: bytes,
        portName: props.portName
      });
      emit('bytes-sent', sentCount);
    } catch (err) {
      term?.write(`\r\n\x1b[31m[错误] 发送失败: ${err}\x1b[0m\r\n`);
    }
  });

  // Fit terminal on layout changes
  resizeObserver = new ResizeObserver(() => {
    try {
      fitAddon?.fit();
    } catch (e) {
      // Ignore initial layout zero-size
    }
  });
  resizeObserver.observe(terminalRef.value);

  setTimeout(() => {
    fitAddon?.fit();
    term?.focus();
    printWelcomeBanner();
  }, 100);
}

function printWelcomeBanner() {
  if (!term) return;
  term.writeln('\x1b[1;36m┌────────────────────────────────────────────────────────────┐\x1b[0m');
  term.writeln(`\x1b[1;36m│\x1b[0m  \x1b[1;32mAI-HIL Debugger - VT100 / ANSI 交互终端模式\x1b[0m               \x1b[1;36m│\x1b[0m`);
  term.writeln(`\x1b[1;36m│\x1b[0m  端口: \x1b[33m${props.portName}\x1b[0m | 支持 Linux 控制台、Shell、Tab 补全 & 颜色 \x1b[1;36m│\x1b[0m`);
  term.writeln('\x1b[1;36m└────────────────────────────────────────────────────────────┘\x1b[0m');
}

/**
 * Feeds raw bytes received from serial into xterm
 */
function writeRawBytes(bytes: Uint8Array) {
  if (term) {
    term.write(bytes);
  }
}

function clearTerminal() {
  term?.clear();
}

function copySelection() {
  if (!term) return;
  const selection = term.getSelection();
  if (selection) {
    navigator.clipboard.writeText(selection);
    isCopied.value = true;
    setTimeout(() => isCopied.value = false, 1500);
  }
}

defineExpose({
  writeRawBytes,
  clearTerminal,
  fit: () => fitAddon?.fit(),
  focus: () => term?.focus()
});

onMounted(() => {
  initTerminal();
});

onUnmounted(() => {
  resizeObserver?.disconnect();
  term?.dispose();
});

watch(() => props.isConnected, (connected) => {
  if (term) {
    if (connected) {
      term.writeln(`\r\n\x1b[32m>>> 端口 [${props.portName}] 已连接，进入交互终端 <<<\x1b[0m\r\n`);
    } else {
      term.writeln(`\r\n\x1b[31m>>> 端口 [${props.portName}] 已断开 <<<\x1b[0m\r\n`);
    }
  }
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 relative overflow-hidden select-text">
    <!-- Mini floating toolbar for terminal -->
    <div class="absolute top-2 right-4 z-10 flex items-center gap-1.5 bg-zinc-900/80 backdrop-blur-xs border border-zinc-800 rounded px-2 py-1 select-none">
      <span class="text-[10px] text-zinc-400 font-mono">VT100 Console</span>
      <div class="h-3 w-px bg-zinc-800 mx-1"></div>
      <button
        @click="copySelection"
        title="复制终端选中文字"
        class="p-1 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 rounded transition-colors"
      >
        <component :is="isCopied ? Check : Copy" class="w-3.5 h-3.5" :class="{ 'text-emerald-400': isCopied }" />
      </button>
      <button
        @click="clearTerminal"
        title="清空终端画布"
        class="p-1 text-zinc-400 hover:text-rose-400 hover:bg-zinc-800 rounded transition-colors"
      >
        <Trash2 class="w-3.5 h-3.5" />
      </button>
    </div>

    <!-- Terminal Mounting Point -->
    <div ref="terminalRef" class="flex-1 w-full h-full p-2 overflow-hidden"></div>
  </div>
</template>

<style scoped>
:deep(.xterm) {
  padding: 4px;
  height: 100%;
}
:deep(.xterm-viewport) {
  background-color: #09090b !important;
}
</style>
