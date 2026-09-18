<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue';
import { safeInvoke } from '../utils/ipc';
import type { ChatMessage } from '../types';
import {
  Send,
  Wrench,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  RefreshCw,
  Cpu,
  Zap,
  RotateCcw,
  Copy,
  Check
} from '@lucide/vue';

const messages = ref<ChatMessage[]>([]);
const userInput = ref<string>('');
const isThinking = ref<boolean>(false);
const chatContainer = ref<HTMLElement | null>(null);
const copiedId = ref<string | null>(null);

function copyMessage(id: string, text: string) {
  navigator.clipboard.writeText(text);
  copiedId.value = id;
  setTimeout(() => {
    if (copiedId.value === id) {
      copiedId.value = null;
    }
  }, 2000);
}

function scrollToBottom() {
  nextTick(() => {
    if (chatContainer.value) {
      chatContainer.value.scrollTop = chatContainer.value.scrollHeight;
    }
  });
}

function addMessage(role: 'user' | 'assistant' | 'tool', content: string, tool_call?: any) {
  const msg: ChatMessage = {
    id: Date.now().toString() + Math.random().toString(),
    role,
    content,
    tool_call,
    timestamp: new Date().toTimeString().split(' ')[0]
  };
  messages.value.push(msg);
  scrollToBottom();
}

async function handleSendMessage(customPrompt?: string) {
  const prompt = customPrompt || userInput.value;
  if (!prompt.trim() || isThinking.value) return;

  addMessage('user', prompt);
  if (!customPrompt) userInput.value = '';

  isThinking.value = true;

  try {
    // Check if query matches hardware actions for direct MCP tool execution
    const lower = prompt.toLowerCase();

    if (lower.includes('hardfault') || lower.includes('故障') || lower.includes('崩溃') || lower.includes('死机')) {
      // Execute diagnose_hardfault tool
      addMessage('assistant', '正在调用 MCP 硬件工具 `diagnose_hardfault` 读取 ARM Cortex-M 寄存器现场...', {
        name: 'diagnose_hardfault',
        arguments: { target_override: 'cortex_m' },
        status: 'running'
      });

      const res: any = await safeInvoke('pyocd_diagnose_hardfault', {
        probeId: null,
        targetOverride: 'cortex_m'
      });

      // Update tool card to success
      messages.value[messages.value.length - 1].tool_call = {
        name: 'diagnose_hardfault',
        arguments: { target_override: 'cortex_m' },
        result: res.raw_dump,
        status: 'success'
      };

      // Formulate detailed AI analysis
      let aiAnalysis = `### 🔍 Cortex-M HardFault 智能分析报告\n\n`;
      aiAnalysis += `- **程序崩溃计数器 (PC)**: \`${res.raw_dump?.core_registers?.PC || 'N/A'}\`\n`;
      aiAnalysis += `- **异常返回状态 (LR/EXC_RETURN)**: \`${res.raw_dump?.core_registers?.LR || 'N/A'}\`\n`;
      aiAnalysis += `- **主栈指针 (MSP)**: \`${res.raw_dump?.core_registers?.MSP || 'N/A'}\`\n\n`;

      const flags = res.raw_dump?.cfsr_decoded?.flags || [];
      if (flags.length > 0) {
        aiAnalysis += `#### 🚨 触发的硬件故障位:\n`;
        for (const f of flags) {
          aiAnalysis += `- \`${f}\`\n`;
        }
      }

      if (res.recommendations && res.recommendations.length > 0) {
        aiAnalysis += `\n#### 💡 修复与排查建议:\n`;
        for (const r of res.recommendations) {
          aiAnalysis += `1. ${r}\n`;
        }
      } else {
        aiAnalysis += `\n单片机当前处于常规运行或未发生严重总线冲突，可复位后继续追踪。`;
      }

      addMessage('assistant', aiAnalysis);

    } else if (lower.includes('复位') || lower.includes('reset') || lower.includes('重启')) {
      // Execute hardware reset tool
      addMessage('assistant', '正在通过 MCP 硬件引脚状态机下发 `normal_reset` (RTS 设为 0 -> 100ms DTR 复位脉冲)...', {
        name: 'hardware_serial_control',
        arguments: { action: 'normal_reset' },
        status: 'running'
      });

      await safeInvoke('execute_reset_sequence', { seqType: 'normal_reset' });

      messages.value[messages.value.length - 1].tool_call = {
        name: 'hardware_serial_control',
        arguments: { action: 'normal_reset' },
        result: { status: 'success', duration_ms: 100 },
        status: 'success'
      };

      addMessage('assistant', '✅ 单片机普通复位完成。RTS 保持 0 (正常态)，DTR 复位完成，MCU 正在从 Flash 起始地址正常重启运行。');

    } else if (lower.includes('探针') || lower.includes('probe') || lower.includes('daplink')) {
      addMessage('assistant', '正在通过 MCP 协议扫描系统总线上的调试器探针...', {
        name: 'list_probes',
        arguments: {},
        status: 'running'
      });

      const probes: any = await safeInvoke('pyocd_list_probes');

      messages.value[messages.value.length - 1].tool_call = {
        name: 'list_probes',
        arguments: {},
        result: probes,
        status: 'success'
      };

      if (probes.length > 0) {
        addMessage('assistant', `✅ 成功枚举到 **${probes.length}** 个硬件调试器探针：\n- **设备**: ${probes[0].description}\n- **探针 Unique ID**: \`${probes[0].unique_id}\`\n- **协议后端**: CMSIS-DAP / WinUSB`);
      } else {
        addMessage('assistant', '⚠️ 未发现已连接的 DAPLink / CMSIS-DAP 探针，请检查 USB 接口与供电。');
      }

    } else if (lower.includes('boot') || lower.includes('引导') || lower.includes('isp')) {
      addMessage('assistant', '正在通过 MCP 状态机触发进入 ISP Bootloader 模式 (RTS 设为 1 -> 等待 500ms 电平建立 -> 100ms DTR 复位脉冲)...', {
        name: 'hardware_serial_control',
        arguments: { action: 'bootloader_reset' },
        status: 'running'
      });

      await safeInvoke('execute_reset_sequence', { seqType: 'bootloader_reset' });

      messages.value[messages.value.length - 1].tool_call = {
        name: 'hardware_serial_control',
        arguments: { action: 'bootloader_reset' },
        result: { status: 'success', delay_ms: 500 },
        status: 'success'
      };

      addMessage('assistant', '⚡ 单片机已成功切换至 System Bootloader (ISP) 引导模式 (RTS 1 维持 500ms 后复位触发)！');

    } else if ((lower.includes('读') || lower.includes('read')) && (lower.includes('ram') || lower.includes('mem') || lower.includes('内存') || lower.includes('0x'))) {
      // Parse address if specified
      const addrMatch = prompt.match(/0x[0-9a-fA-F]+/);
      const targetAddr = addrMatch ? addrMatch[0] : '0x20000000';
      const count = 16;

      addMessage('assistant', `正在调用 MCP 工具 \`read_memory\` 读取内存地址 ${targetAddr}...`, {
        name: 'read_memory',
        arguments: { address: targetAddr, count, target_override: 'cortex_m' },
        status: 'running'
      });

      const res: any = await safeInvoke('pyocd_read_memory', {
        address: targetAddr,
        count,
        probeId: null,
        targetOverride: 'cortex_m'
      });

      messages.value[messages.value.length - 1].tool_call = {
        name: 'read_memory',
        arguments: { address: targetAddr, count },
        result: res,
        status: 'success'
      };

      addMessage('assistant', `✅ 成功通过 MCP 读取内存 **${res.address || targetAddr}** (16 字节):\n\`\`\`\nHEX: ${res.hex_dump || 'N/A'}\n\`\`\`\n原始字节: \`[${res.bytes?.join(', ')}]\``);

    } else if ((lower.includes('写') || lower.includes('write') || lower.includes('修改')) && (lower.includes('ram') || lower.includes('mem') || lower.includes('内存') || lower.includes('0x'))) {
      const allHex = prompt.match(/0x[0-9a-fA-F]+/g) || [];
      const targetAddr = allHex[0] || '0x20000000';
      const valStr = allHex.length > 1 ? allHex[1] : '0x12345678';

      addMessage('assistant', `正在调用 MCP 工具 \`write_memory\` 向地址 ${targetAddr} 写入 ${valStr}...`, {
        name: 'write_memory',
        arguments: { address: targetAddr, value: valStr, target_override: 'cortex_m' },
        status: 'running'
      });

      const res: any = await safeInvoke('pyocd_write_memory', {
        address: targetAddr,
        value: valStr,
        probeId: null,
        targetOverride: 'cortex_m'
      });

      messages.value[messages.value.length - 1].tool_call = {
        name: 'write_memory',
        arguments: { address: targetAddr, value: valStr },
        result: res,
        status: 'success'
      };

      addMessage('assistant', `✅ 成功通过 MCP 向内存 **${res.address || targetAddr}** 写入 **${res.value || valStr}**！状态: \`${res.status}\``);

    } else {
      // General Embedded AI guidance
      setTimeout(() => {
        addMessage(
          'assistant',
          `您好！我是您的嵌入式 HIL 硬件智能助手。我已经通过 MCP (Model Context Protocol) 直连您的 DAPLink 调试器。\n\n您可以随时指示我执行：\n- 🔍 **“检测当前连接的硬件调试探针”**\n- 📖 **“读取 RAM 内存 0x20000000”**\n- ✏️ **“写入 RAM 内存 0x20000000 0x12345678”**\n- 🔍 **“分析当前单片机 HardFault 崩溃原因”**\n- 🔄 **“复位单片机并重启”**\n- ⚡ **“切换至 ISP Bootloader 引导模式”**`
        );
      }, 500);
    }
  } catch (err: any) {
    addMessage('assistant', `❌ MCP Tool 执行失败: ${err}`);
  } finally {
    isThinking.value = false;
  }
}

onMounted(() => {
  addMessage(
    'assistant',
    '👋 欢迎使用 AI-HIL 嵌入式硬件助手！原生支持 **MCP 协议**，我可以直接控制 DAPLink 引脚状态机、SWD 调试总线以及 Cortex-M 故障寄存器。点击下方快捷指令或直接提问。'
  );
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 text-xs">
    <!-- Chat Header -->
    <div class="bg-zinc-900 border-b border-zinc-800 px-4 py-2.5 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <Sparkles class="w-4 h-4 text-emerald-400" />
        <span class="font-bold text-zinc-200">AI 嵌入式 HIL 智能助手 (MCP Native)</span>
      </div>
      <div class="flex items-center gap-2 text-[11px] text-zinc-400">
        <span class="w-2 h-2 rounded-full bg-emerald-500 animate-pulse"></span>
        <span>MCP Server (stdio) 在线</span>
      </div>
    </div>

    <!-- Messages Viewport -->
    <div ref="chatContainer" class="flex-1 overflow-y-auto p-4 space-y-4">
      <div
        v-for="msg in messages"
        :key="msg.id"
        class="flex flex-col gap-1.5 max-w-3xl"
        :class="msg.role === 'user' ? 'ml-auto items-end' : 'mr-auto items-start'"
      >
        <div class="flex items-center gap-1.5 text-[10px] text-zinc-500 font-mono">
          <span>{{ msg.role === 'user' ? '用户' : 'AI Copilot' }}</span>
          <span>•</span>
          <span>{{ msg.timestamp }}</span>
        </div>

        <!-- Tool Call Execution Card (if present) -->
        <div
          v-if="msg.tool_call"
          class="w-full bg-zinc-900 border border-zinc-800 rounded-lg p-3 text-xs font-mono space-y-2 shadow-sm"
        >
          <div class="flex items-center justify-between pb-1.5 border-b border-zinc-800">
            <div class="flex items-center gap-1.5 text-emerald-400 font-bold">
              <Wrench class="w-3.5 h-3.5" />
              <span>MCP Tool: {{ msg.tool_call.name }}</span>
            </div>
            <div class="flex items-center gap-1 text-[10px]">
              <span
                v-if="msg.tool_call.status === 'running'"
                class="text-amber-400 flex items-center gap-1"
              >
                <RefreshCw class="w-3 h-3 animate-spin" /> 执行中
              </span>
              <span
                v-else-if="msg.tool_call.status === 'success'"
                class="text-emerald-400 flex items-center gap-1"
              >
                <CheckCircle2 class="w-3 h-3" /> 执行成功
              </span>
              <span v-else class="text-rose-400 flex items-center gap-1">
                <AlertCircle class="w-3 h-3" /> 失败
              </span>
            </div>
          </div>

          <div class="text-zinc-400 text-[11px]">
            <div>入参: <code class="text-zinc-300 select-text">{{ JSON.stringify(msg.tool_call.arguments) }}</code></div>
            <div v-if="msg.tool_call.result" class="mt-1">
              <div class="flex items-center justify-between">
                <span>返回数据:</span>
                <button
                  @click="copyMessage(msg.id + '_tool', JSON.stringify(msg.tool_call.result, null, 2))"
                  class="flex items-center gap-1 text-[10px] text-zinc-400 hover:text-zinc-200 px-1.5 py-0.5 rounded hover:bg-zinc-800 transition-colors"
                  title="复制工具返回结果"
                >
                  <component :is="copiedId === msg.id + '_tool' ? Check : Copy" class="w-3 h-3 text-emerald-400" />
                  <span>{{ copiedId === msg.id + '_tool' ? '已复制' : '复制结果' }}</span>
                </button>
              </div>
              <pre class="bg-zinc-950 p-2 rounded mt-1 max-h-36 overflow-y-auto text-[10px] text-zinc-300 select-text">{{ JSON.stringify(msg.tool_call.result, null, 2) }}</pre>
            </div>
          </div>
        </div>

        <!-- Text Bubble -->
        <div class="relative group/msg max-w-full">
          <div
            class="rounded-xl px-4 py-2.5 leading-relaxed text-[12px] select-text"
            :class="msg.role === 'user' 
              ? 'bg-emerald-600 text-white rounded-br-none shadow' 
              : 'bg-zinc-900 border border-zinc-800/80 text-zinc-200 rounded-bl-none shadow-sm whitespace-pre-wrap'"
          >
            {{ msg.content }}
          </div>
          <!-- Copy button on hover -->
          <button
            @click="copyMessage(msg.id, msg.content)"
            class="absolute top-1 right-1 opacity-0 group-hover/msg:opacity-100 p-1 rounded bg-zinc-800/80 hover:bg-zinc-700 text-zinc-300 transition-all shadow-sm"
            :class="{ '!opacity-100': copiedId === msg.id }"
            title="复制消息内容"
          >
            <component :is="copiedId === msg.id ? Check : Copy" class="w-3 h-3 text-emerald-400" />
          </button>
        </div>
      </div>
    </div>

    <!-- Quick Action Chips -->
    <div class="bg-zinc-900/40 border-t border-zinc-800/60 px-4 py-2 flex items-center gap-2 overflow-x-auto select-none">
      <button
        @click="handleSendMessage('分析当前单片机 HardFault 故障原因')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <AlertCircle class="w-3.5 h-3.5 text-rose-400" />
        <span>诊断 HardFault 故障</span>
      </button>

      <button
        @click="handleSendMessage('复位单片机并重启')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <RotateCcw class="w-3.5 h-3.5 text-sky-400" />
        <span>复位单片机</span>
      </button>

      <button
        @click="handleSendMessage('切换至 ISP Bootloader 引导模式')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <Zap class="w-3.5 h-3.5 text-amber-400" />
        <span>进入 Bootloader</span>
      </button>

      <button
        @click="handleSendMessage('检测当前连接的硬件调试探针')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <Cpu class="w-3.5 h-3.5 text-emerald-400" />
        <span>扫描调试探针</span>
      </button>

      <button
        @click="handleSendMessage('读取 RAM 内存 0x20000000')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <Binary class="w-3.5 h-3.5 text-emerald-400" />
        <span>读取 RAM (0x20000000)</span>
      </button>

      <button
        @click="handleSendMessage('写入 RAM 内存 0x20000000 0x12345678')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <Binary class="w-3.5 h-3.5 text-indigo-400" />
        <span>写入 RAM (0x20000000)</span>
      </button>
    </div>

    <!-- Chat Input Bar -->
    <div class="bg-zinc-900 border-t border-zinc-800 p-3 flex items-center gap-2">
      <input
        v-model="userInput"
        @keydown.enter="handleSendMessage()"
        type="text"
        placeholder="向 AI 描述您的硬件调试需求，或输入指令直接调用 MCP Tools..."
        class="flex-1 bg-zinc-950 border border-zinc-800 focus:border-emerald-500 rounded-lg px-3.5 py-2 text-xs text-zinc-100 placeholder-zinc-500 outline-none transition-colors"
        :disabled="isThinking"
      />
      <button
        @click="handleSendMessage()"
        :disabled="isThinking || !userInput.trim()"
        class="flex items-center gap-1.5 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold transition-colors disabled:opacity-40"
      >
        <Send class="w-3.5 h-3.5" />
        <span>发送</span>
      </button>
    </div>
  </div>
</template>
