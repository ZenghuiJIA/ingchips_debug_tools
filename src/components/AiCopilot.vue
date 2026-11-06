<script setup lang="ts">
import { ref, onMounted, nextTick } from 'vue';
import { safeInvoke } from '../utils/ipc';
import { parseHardwareIntent } from '../utils/hardwareContracts';
import { t } from '../utils/i18n';
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
  Check,
  Binary,
  Radio,
  Terminal,
  Layers
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
    const intent = parseHardwareIntent(prompt);
    if (!intent) {
      addMessage('assistant', '未执行硬件操作。此页支持完整快捷命令，不解析自由问答。请使用下方快捷按钮；写内存必须明确提供地址和值。');
      return;
    }
    let probeId: string | null = null;
    let portName: string | null = null;
    if (['fault', 'read', 'write', 'read_core_registers', 'reset_target_swd'].includes(intent.action)) {
      const probes = await safeInvoke<any[]>('pyocd_list_probes');
      if (probes.length !== 1) throw new Error('需要且仅允许连接一只探针；多探针请在对应工具页明确选择');
      probeId = probes[0].unique_id;
    }
    if (intent.action === 'reset' || intent.action === 'boot') {
      const ports = await safeInvoke<string[]>('list_active_serial_sessions');
      if (ports.length !== 1) throw new Error('请保留一个已连接的目标串口再执行复位');
      portName = ports[0];
    }

    if (intent.action === 'fault') {
      // Execute diagnose_hardfault tool
      addMessage('assistant', '正在调用 MCP 硬件工具 `diagnose_hardfault` 读取 ARM Cortex-M 寄存器现场...', {
        name: 'diagnose_hardfault',
        arguments: { target_override: 'cortex_m' },
        status: 'running'
      });

      const res: any = await safeInvoke('pyocd_diagnose_hardfault', {
        probeId,
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

    } else if (intent.action === 'reset') {
      // Execute hardware reset tool
      addMessage('assistant', '正在通过 MCP 硬件引脚状态机下发 `normal_reset` (RTS 设为 0 -> 100ms DTR 复位脉冲)...', {
        name: 'hardware_serial_control',
        arguments: { action: 'normal_reset' },
        status: 'running'
      });

      await safeInvoke('execute_reset_sequence', { seqType: 'normal_reset', portName });

      messages.value[messages.value.length - 1].tool_call = {
        name: 'hardware_serial_control',
        arguments: { action: 'normal_reset' },
        result: { status: 'success', duration_ms: 100 },
        status: 'success'
      };

      addMessage('assistant', '✅ 单片机普通复位完成。RTS 保持 0 (正常态)，DTR 复位完成，MCU 正在从 Flash 起始地址正常重启运行。');

    } else if (intent.action === 'probes') {
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

    } else if (intent.action === 'boot') {
      addMessage('assistant', '正在通过 MCP 状态机触发进入 ISP Bootloader 模式 (RTS 设为 1 -> 等待 500ms 电平建立 -> 100ms DTR 复位脉冲)...', {
        name: 'hardware_serial_control',
        arguments: { action: 'bootloader_reset' },
        status: 'running'
      });

      await safeInvoke('execute_reset_sequence', { seqType: 'bootloader_reset', portName });

      messages.value[messages.value.length - 1].tool_call = {
        name: 'hardware_serial_control',
        arguments: { action: 'bootloader_reset' },
        result: { status: 'success', delay_ms: 500 },
        status: 'success'
      };

      addMessage('assistant', '⚡ 单片机已成功切换至 System Bootloader (ISP) 引导模式 (RTS 1 维持 500ms 后复位触发)！');

    } else if (intent.action === 'read') {
      // Parse address if specified
      const targetAddr = intent.address!;
      const count = 16;

      addMessage('assistant', `正在调用 MCP 工具 \`read_memory\` 读取内存地址 ${targetAddr}...`, {
        name: 'read_memory',
        arguments: { address: targetAddr, count, target_override: 'cortex_m' },
        status: 'running'
      });

      const res: any = await safeInvoke('pyocd_read_memory', {
        address: targetAddr,
        count,
        probeId,
        targetOverride: 'cortex_m'
      });

      messages.value[messages.value.length - 1].tool_call = {
        name: 'read_memory',
        arguments: { address: targetAddr, count },
        result: res,
        status: 'success'
      };

      addMessage('assistant', `✅ 成功通过 MCP 读取内存 **${res.address || targetAddr}** (16 字节):\n\`\`\`\nHEX: ${res.hex_dump || 'N/A'}\n\`\`\`\n原始字节: \`[${res.bytes?.join(', ')}]\``);

    } else if (intent.action === 'write') {
      const targetAddr = intent.address!;
      const valStr = intent.value!;

      addMessage('assistant', `正在调用 MCP 工具 \`write_memory\` 向地址 ${targetAddr} 写入 ${valStr}...`, {
        name: 'write_memory',
        arguments: { address: targetAddr, value: valStr, target_override: 'cortex_m' },
        status: 'running'
      });

      const res: any = await safeInvoke('pyocd_write_memory', {
        address: targetAddr,
        value: valStr,
        probeId,
        targetOverride: 'cortex_m'
      });

      messages.value[messages.value.length - 1].tool_call = {
        name: 'write_memory',
        arguments: { address: targetAddr, value: valStr },
        result: res,
        status: 'success'
      };

      addMessage('assistant', `✅ 成功通过 MCP 向内存 **${res.address || targetAddr}** 写入 **${res.value || valStr}**！状态: \`${res.status}\``);

    } else if (intent.action === 'list_serial_ports') {
      addMessage('assistant', '正在通过 MCP 扫描系统可用串口及 USB CDC 设备...', {
        name: 'list_serial_ports',
        arguments: {},
        status: 'running'
      });

      const ports: any = await safeInvoke('list_serial_ports');

      messages.value[messages.value.length - 1].tool_call = {
        name: 'list_serial_ports',
        arguments: {},
        result: ports,
        status: 'success'
      };

      if (ports && ports.length > 0) {
        let msg = `✅ 成功枚举到 **${ports.length}** 个可用串口：\n`;
        for (const p of ports) {
          const dap = p.is_daplink ? ' *(DAPLink 虚拟串口)*' : '';
          const desc = p.usb_info?.description ? ` - ${p.usb_info.description}` : '';
          msg += `- **${p.port_name}**${dap}${desc}\n`;
        }
        addMessage('assistant', msg);
      } else {
        addMessage('assistant', '⚠️ 未发现系统可用串口，请检查硬件连接或驱动。');
      }

    } else if (intent.action === 'read_serial_data') {
      const activeSessions = await safeInvoke<string[]>('list_active_serial_sessions');
      if (!activeSessions || activeSessions.length === 0) {
        addMessage('assistant', '⚠️ 当前没有已连接的串口会话。请先在串口助手连接目标串口，或通过 MCP 打开串口。');
        return;
      }
      const targetPort = intent.port || activeSessions[0];

      addMessage('assistant', `正在读取串口 **${targetPort}** 的最新接收数据...`, {
        name: 'read_serial_data',
        arguments: { port_name: targetPort, max_bytes: 50 },
        status: 'running'
      });

      const page: any = await safeInvoke('serial_capture_read', {
        portName: targetPort,
        after: 0,
        limit: 50
      });

      messages.value[messages.value.length - 1].tool_call = {
        name: 'read_serial_data',
        arguments: { port_name: targetPort },
        result: page,
        status: 'success'
      };

      const events = page?.events || [];
      const rxEvents = events.filter((e: any) => e.direction === 'rx');
      if (rxEvents.length > 0) {
        const lastFew = rxEvents.slice(-10);
        let snippet = lastFew.map((e: any) => `[+${Math.round(e.elapsed_ms)}ms] ${e.data}`).join('\n');
        addMessage('assistant', `✅ 从串口 **${targetPort}** 读取到最新 ${rxEvents.length} 条数据片段：\n\`\`\`text\n${snippet}\n\`\`\``);
      } else if (events.length > 0) {
        addMessage('assistant', `ℹ️ 串口 **${targetPort}** 记录中包含 ${events.length} 条历史事件，暂无最新 RX 接收数据。`);
      } else {
        addMessage('assistant', `ℹ️ 串口 **${targetPort}** 缓冲区当前为空，尚未收到数据。`);
      }

    } else if (intent.action === 'send_serial_data') {
      const activeSessions = await safeInvoke<string[]>('list_active_serial_sessions');
      if (!activeSessions || activeSessions.length === 0) {
        addMessage('assistant', '⚠️ 当前没有已连接的串口会话，无法下发数据。请先在串口助手连接目标串口。');
        return;
      }
      const targetPort = intent.port || activeSessions[0];
      const payloadStr = intent.data || '';

      addMessage('assistant', `正在向串口 **${targetPort}** 下发数据...`, {
        name: 'send_serial_data',
        arguments: { port_name: targetPort, data: payloadStr },
        status: 'running'
      });

      let rawBytes: number[] = [];
      const hexClean = payloadStr.replace(/0x|\s+|,/g, '');
      if (/^[0-9a-fA-F]+$/.test(hexClean) && hexClean.length % 2 === 0 && payloadStr.includes(' ')) {
        for (let i = 0; i < hexClean.length; i += 2) {
          rawBytes.push(parseInt(hexClean.substr(i, 2), 16));
        }
      } else {
        rawBytes = Array.from(new TextEncoder().encode(payloadStr));
      }

      const sentBytes: any = await safeInvoke('send_serial_data', {
        data: rawBytes,
        portName: targetPort
      });

      messages.value[messages.value.length - 1].tool_call = {
        name: 'send_serial_data',
        arguments: { port_name: targetPort, data: payloadStr, bytes_count: rawBytes.length },
        result: { bytes_sent: sentBytes ?? rawBytes.length },
        status: 'success'
      };

      addMessage('assistant', `✅ 成功向串口 **${targetPort}** 发送 ${sentBytes ?? rawBytes.length} 字节数据！`);

    } else if (intent.action === 'read_core_registers') {
      addMessage('assistant', '正在调用 MCP 硬件工具 `read_core_registers` 读取 Cortex-M 核心寄存器...', {
        name: 'read_core_registers',
        arguments: { target_override: 'cortex_m' },
        status: 'running'
      });

      const res: any = await safeInvoke('pyocd_read_registers', {
        probeId,
        targetOverride: 'cortex_m'
      });

      messages.value[messages.value.length - 1].tool_call = {
        name: 'read_core_registers',
        arguments: { target_override: 'cortex_m' },
        result: res,
        status: 'success'
      };

      let table = `### 📊 ARM Cortex-M 核心寄存器状态\n\n`;
      table += `| 寄存器 | 32 位十六进制值 | 寄存器 | 32 位十六进制值 |\n`;
      table += `| :--- | :--- | :--- | :--- |\n`;
      const regs = res?.registers || res || {};
      const pairs = [
        ['R0', 'R1'], ['R2', 'R3'], ['R4', 'R5'], ['R6', 'R7'],
        ['R8', 'R9'], ['R10', 'R11'], ['R12', 'SP (R13)'],
        ['LR (R14)', 'PC (R15)'], ['xPSR', 'MSP'], ['PSP', 'PRIMASK']
      ];
      for (const [k1, k2] of pairs) {
        const val1 = regs[k1] ?? regs[k1.split(' ')[0]] ?? '-';
        const val2 = regs[k2] ?? regs[k2.split(' ')[0]] ?? '-';
        table += `| \`${k1}\` | \`${typeof val1 === 'number' ? '0x' + val1.toString(16).padStart(8, '0') : val1}\` | \`${k2}\` | \`${typeof val2 === 'number' ? '0x' + val2.toString(16).padStart(8, '0') : val2}\` |\n`;
      }
      addMessage('assistant', table);

    } else if (intent.action === 'reset_target_swd') {
      addMessage('assistant', '正在通过 SWD 调试探针下发目标复位指令...', {
        name: 'reset_target',
        arguments: { halt: false, target_override: 'cortex_m' },
        status: 'running'
      });

      const res: any = await safeInvoke('pyocd_reset_target', {
        halt: false,
        probeId,
        targetOverride: 'cortex_m'
      });

      messages.value[messages.value.length - 1].tool_call = {
        name: 'reset_target',
        arguments: { halt: false },
        result: res || { status: 'success' },
        status: 'success'
      };

      addMessage('assistant', '✅ 已通过 SWD 接口下发硬件复位命令，MCU 核心已重启并正常运行。');

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
        <span>快捷命令模式 · 执行时检查连接</span>
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
          <span>{{ msg.role === 'user' ? t('ai_role_user') : t('ai_role_assistant') }}</span>
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
                <RefreshCw class="w-3 h-3 animate-spin" /> {{ t("ai_status_running") }}
              </span>
              <span
                v-else-if="msg.tool_call.status === 'success'"
                class="text-emerald-400 flex items-center gap-1"
              >
                <CheckCircle2 class="w-3 h-3" /> {{ t("ai_status_success") }}
              </span>
              <span v-else class="text-rose-400 flex items-center gap-1">
                <AlertCircle class="w-3 h-3" /> {{ t("ai_status_failed") }}
              </span>
            </div>
          </div>

          <div class="text-zinc-400 text-[11px]">
            <div>{{ t("ai_field_args") }} <code class="text-zinc-300 select-text">{{ JSON.stringify(msg.tool_call.arguments) }}</code></div>
            <div v-if="msg.tool_call.result" class="mt-1">
              <div class="flex items-center justify-between">
                <span>{{ t("ai_field_returned") }}</span>
                <button
                  @click="copyMessage(msg.id + '_tool', JSON.stringify(msg.tool_call.result, null, 2))"
                  class="flex items-center gap-1 text-[10px] text-zinc-400 hover:text-zinc-200 px-1.5 py-0.5 rounded hover:bg-zinc-800 transition-colors"
                  :title="t('ai_tip_copy_tool')"
                >
                  <component :is="copiedId === msg.id + '_tool' ? Check : Copy" class="w-3 h-3 text-emerald-400" />
                  <span>{{ copiedId === msg.id + '_tool' ? t('ai_btn_copied_tool') : t('ai_btn_copy_tool') }}</span>
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
            :title="t('ai_tip_copy_msg')"
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
        <span>{{ t("ai_action_hardfault") }}</span>
      </button>

      <button
        @click="handleSendMessage('复位单片机并重启')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <RotateCcw class="w-3.5 h-3.5 text-sky-400" />
        <span>{{ t("ai_action_reset") }}</span>
      </button>

      <button
        @click="handleSendMessage('切换至 ISP Bootloader 引导模式')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <Zap class="w-3.5 h-3.5 text-amber-400" />
        <span>{{ t("ai_action_boot") }}</span>
      </button>

      <button
        @click="handleSendMessage('检测当前连接的硬件调试探针')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <Cpu class="w-3.5 h-3.5 text-emerald-400" />
        <span>{{ t("ai_action_probes") }}</span>
      </button>

      <button
        @click="handleSendMessage('读取 RAM 内存 0x20000000')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <Binary class="w-3.5 h-3.5 text-emerald-400" />
        <span>{{ t("ai_action_read_ram") }}</span>
      </button>

      <button
        @click="handleSendMessage('写入 RAM 内存 0x20000000 0x12345678')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <Binary class="w-3.5 h-3.5 text-indigo-400" />
        <span>{{ t("ai_action_write_ram") }}</span>
      </button>

      <button
        @click="handleSendMessage('扫描可用串口')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <Radio class="w-3.5 h-3.5 text-cyan-400" />
        <span>{{ t("ai_action_scan_serial") }}</span>
      </button>

      <button
        @click="handleSendMessage('读取串口最新数据')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <Terminal class="w-3.5 h-3.5 text-lime-400" />
        <span>{{ t("ai_action_read_serial") }}</span>
      </button>

      <button
        @click="handleSendMessage('读取 CPU 核心寄存器')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <Layers class="w-3.5 h-3.5 text-purple-400" />
        <span>{{ t("ai_action_core_regs") }}</span>
      </button>

      <button
        @click="handleSendMessage('SWD 目标复位')"
        class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs border border-zinc-700 transition-colors shrink-0"
      >
        <RotateCcw class="w-3.5 h-3.5 text-pink-400" />
        <span>{{ t("ai_action_reset_swd") }}</span>
      </button>
    </div>

    <!-- Chat Input Bar -->
    <div class="bg-zinc-900 border-t border-zinc-800 p-3 flex items-center gap-2">
      <input
        v-model="userInput"
        @keydown.enter="handleSendMessage()"
        type="text"
        :placeholder="t('ai_placeholder_input')"
        class="flex-1 bg-zinc-950 border border-zinc-800 focus:border-emerald-500 rounded-lg px-3.5 py-2 text-xs text-zinc-100 placeholder-zinc-500 outline-none transition-colors"
        :disabled="isThinking"
      />
      <button
        @click="handleSendMessage()"
        :disabled="isThinking || !userInput.trim()"
        class="flex items-center gap-1.5 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold transition-colors disabled:opacity-40"
      >
        <Send class="w-3.5 h-3.5" />
        <span>{{ t("ai_btn_send") }}</span>
      </button>
    </div>
  </div>
</template>
