<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { safeInvoke, isTauri } from '../utils/ipc';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import type { SerialRxPayload, PortInfo } from '../types';
import {
  Radio,
  Play,
  Square,
  Download,
  Filter
} from '@lucide/vue';

// --- H4 / HCI Packet Types ---
export interface HciPacket {
  id: number;
  timestamp: string;
  type: 'CMD' | 'EVT' | 'ACL' | 'ISO' | 'RAW';
  typeByte: number;
  opcodeOrEvent: string;
  length: number;
  summary: string;
  rawHex: string;
  rawBytes: number[];
  fields: Array<{ name: string; value: string }>;
}

// Available Ports
const availablePorts = ref<PortInfo[]>([]);
const selectedPort = ref<string>('');

// Active Tab: 'dtm' (Direct Test Mode) | 'hci_trace' (Packet Inspector)
const activeSubTab = ref<'dtm' | 'hci_trace'>('dtm');

// --- DTM RF Test State ---
const dtmMode = ref<'tx' | 'rx'>('tx');
const dtmChannel = ref<number>(0); // 0 ~ 39 (2402 ~ 2480 MHz)
const dtmPhy = ref<'1M' | '2M' | 'coded_s8' | 'coded_s2'>('1M');
const dtmPayloadType = ref<'prbs9' | '1010' | '1111' | 'single_carrier'>('prbs9');
const dtmPacketLength = ref<number>(37); // 0 ~ 255
const isDtmRunning = ref<boolean>(false);
const dtmLogs = ref<Array<{ time: string; text: string; status: 'info' | 'success' | 'error' }>>([]);

// Rx Statistics
const rxPacketsCount = ref<number>(0);
const rxExpectedPackets = ref<number>(100);
const rxPerRate = computed(() => {
  if (rxExpectedPackets.value <= 0) return 0;
  const lost = Math.max(0, rxExpectedPackets.value - rxPacketsCount.value);
  return Number(((lost / rxExpectedPackets.value) * 100).toFixed(1));
});

// --- HCI Packet Inspector State ---
const hciPackets = ref<HciPacket[]>([]);
const selectedPacketId = ref<number | null>(null);
const filterType = ref<string>('ALL');
const filterKeyword = ref<string>('');
let nextHciId = 1;
let unlistenRx: UnlistenFn | null = null;

// Channels definition with frequency
const channelsList = Array.from({ length: 40 }, (_, i) => ({
  ch: i,
  freq: 2402 + i * 2,
  isAdv: i === 37 || i === 38 || i === 39
}));

// Filtered HCI Packets
const filteredHciPackets = computed(() => {
  return hciPackets.value.filter(p => {
    if (filterType.value !== 'ALL' && p.type !== filterType.value) return false;
    if (filterKeyword.value.trim()) {
      const q = filterKeyword.value.trim().toLowerCase();
      return p.opcodeOrEvent.toLowerCase().includes(q) || p.summary.toLowerCase().includes(q) || p.rawHex.toLowerCase().includes(q);
    }
    return true;
  });
});

const selectedPacket = computed(() => {
  return hciPackets.value.find(p => p.id === selectedPacketId.value) || null;
});

function addDtmLog(text: string, status: 'info' | 'success' | 'error' = 'info') {
  const time = new Date().toTimeString().split(' ')[0];
  dtmLogs.value.unshift({ time, text, status });
  if (dtmLogs.value.length > 100) dtmLogs.value.pop();
}

async function loadPorts() {
  try {
    const list: PortInfo[] = await safeInvoke('list_serial_ports');
    availablePorts.value = list;
    if (list.length > 0 && !selectedPort.value) {
      selectedPort.value = list[0].port_name;
    }
  } catch (e) {
    console.warn('Failed to load ports in BLE console:', e);
  }
}

// Start / Stop DTM Test
async function startDtmTest() {
  if (!selectedPort.value) {
    alert('请先选择目标芯片串口端口');
    return;
  }

  isDtmRunning.value = true;
  rxPacketsCount.value = 0;
  const freqMhz = 2402 + dtmChannel.value * 2;

  if (dtmMode.value === 'tx') {
    addDtmLog(`启动 TX 射频发射测试: 频点 CH${dtmChannel.value} (${freqMhz}MHz), PHY: ${dtmPhy.value}, 载荷: ${dtmPayloadType.value}, 长度: ${dtmPacketLength.value}B`, 'info');
    // Standard Bluetooth DTM 2-byte command: 0x02 (Transmitter Test) | (Frequency << 2) ...
    // Send over selected serial port
    try {
      const cmdByte1 = 0x80 | (dtmChannel.value & 0x3F);
      const cmdByte2 = (dtmPacketLength.value & 0x3F);
      await safeInvoke('send_serial_data', {
        data: [cmdByte1, cmdByte2],
        portName: selectedPort.value
      });
      addDtmLog('DTM TX 指令已下发到芯片控制器', 'success');
    } catch (err: any) {
      addDtmLog(`DTM 指令发送失败: ${err}`, 'error');
    }
  } else {
    addDtmLog(`启动 RX 接收灵敏度测试: 频点 CH${dtmChannel.value} (${freqMhz}MHz), PHY: ${dtmPhy.value}`, 'info');
    try {
      const cmdByte1 = 0x40 | (dtmChannel.value & 0x3F);
      await safeInvoke('send_serial_data', {
        data: [cmdByte1, 0x00],
        portName: selectedPort.value
      });
      addDtmLog('DTM RX 监听已启动', 'success');
    } catch (err: any) {
      addDtmLog(`DTM RX 启动失败: ${err}`, 'error');
    }
  }
}

async function stopDtmTest() {
  if (!selectedPort.value) return;
  addDtmLog('正在结束 DTM 射频测试并读取返回统计...', 'info');
  try {
    // 0x00 0x00: Test End command
    await safeInvoke('send_serial_data', {
      data: [0x00, 0x00],
      portName: selectedPort.value
    });
    isDtmRunning.value = false;
    addDtmLog('DTM 射频测试已停止', 'success');
  } catch (err: any) {
    addDtmLog(`停止测试失败: ${err}`, 'error');
    isDtmRunning.value = false;
  }
}

// HCI Packet Parser (H4 framing)
function parseHciChunk(bytes: Uint8Array) {
  if (bytes.length === 0) return;
  const time = new Date().toTimeString().split(' ')[0] + '.' + new Date().getMilliseconds().toString().padStart(3, '0');
  const typeByte = bytes[0];
  const hexStr = Array.from(bytes).map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');

  let type: HciPacket['type'] = 'RAW';
  let opcodeOrEvent = 'RAW_DATA';
  let summary = `原始数据 (${bytes.length} 字节)`;
  const fields: HciPacket['fields'] = [];

  if (typeByte === 0x01 && bytes.length >= 4) {
    type = 'CMD';
    const ocf = bytes[1];
    const ogf = bytes[2] >> 2;
    opcodeOrEvent = `HCI_CMD (OGF:0x${ogf.toString(16)}, OCF:0x${ocf.toString(16)})`;
    summary = `命令参数长: ${bytes[3]} 字节`;
    fields.push({ name: 'Type Indicator', value: '0x01 (HCI Command)' });
    fields.push({ name: 'Opcode', value: `0x${((bytes[2] << 8) | bytes[1]).toString(16).toUpperCase()}` });
    fields.push({ name: 'Parameter Length', value: `${bytes[3]} Bytes` });
  } else if (typeByte === 0x04 && bytes.length >= 3) {
    type = 'EVT';
    const evtCode = bytes[1];
    const paramLen = bytes[2];
    if (evtCode === 0x3E) {
      const subEvent = bytes[3];
      opcodeOrEvent = `LE_META (Sub:0x${subEvent ? subEvent.toString(16).padStart(2, '0') : '00'})`;
      if (subEvent === 0x02) {
        opcodeOrEvent = 'LE_Advertising_Report';
        summary = `广播数据上报 (Len: ${paramLen})`;
      } else if (subEvent === 0x0D) {
        opcodeOrEvent = 'LE_Extended_Advertising_Report';
        summary = `扩展广播数据包 (Len: ${paramLen})`;
      } else {
        summary = `LE Meta Event (Sub: 0x${subEvent.toString(16)})`;
      }
    } else if (evtCode === 0x0E) {
      opcodeOrEvent = 'Command_Complete';
      summary = `命令完成状态`;
    } else {
      opcodeOrEvent = `HCI_EVT_0x${evtCode.toString(16).toUpperCase()}`;
      summary = `事件载荷: ${paramLen} 字节`;
    }
    fields.push({ name: 'Type Indicator', value: '0x04 (HCI Event)' });
    fields.push({ name: 'Event Code', value: `0x${evtCode.toString(16).toUpperCase()}` });
    fields.push({ name: 'Parameter Length', value: `${paramLen} Bytes` });
  } else if (typeByte === 0x02) {
    type = 'ACL';
    opcodeOrEvent = 'HCI_ACL_Data';
    summary = `BLE 连接数据包 (${bytes.length - 1} 字节)`;
  }

  const packet: HciPacket = {
    id: nextHciId++,
    timestamp: time,
    type,
    typeByte,
    opcodeOrEvent,
    length: bytes.length,
    summary,
    rawHex: hexStr,
    rawBytes: Array.from(bytes),
    fields
  };

  hciPackets.value.unshift(packet);
  if (hciPackets.value.length > 500) hciPackets.value.pop();

  if (type === 'EVT' && isDtmRunning.value && dtmMode.value === 'rx') {
    rxPacketsCount.value++;
  }
}

function clearPackets() {
  hciPackets.value = [];
  selectedPacketId.value = null;
}

// Export PCAP file helper
function exportPcap() {
  if (hciPackets.value.length === 0) {
    alert('暂无捕获的 HCI 报文');
    return;
  }
  const text = hciPackets.value.map(p => `[${p.timestamp}] [${p.type}] ${p.opcodeOrEvent}: ${p.rawHex}`).join('\n');
  const blob = new Blob([text], { type: 'text/plain' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `hci_trace_${Date.now()}.txt`;
  a.click();
  URL.revokeObjectURL(url);
}

onMounted(async () => {
  await loadPorts();

  if (isTauri()) {
    try {
      unlistenRx = await listen<SerialRxPayload>('serial-rx', (event) => {
        if (selectedPort.value && event.payload.port === selectedPort.value) {
          parseHciChunk(new Uint8Array(event.payload.data));
        }
      });
    } catch (e) {
      console.warn('Failed to attach serial rx listener:', e);
    }
  }
});

onUnmounted(() => {
  if (unlistenRx) unlistenRx();
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-sans select-none overflow-hidden">
    <!-- Header Controls Toolbar -->
    <div class="bg-zinc-900 border-b border-zinc-800 p-3 flex items-center justify-between gap-3 shrink-0">
      <div class="flex items-center gap-2.5">
        <div class="p-1.5 rounded bg-blue-950/60 border border-blue-800/40 text-blue-400">
          <Radio class="w-4 h-4" />
        </div>
        <div>
          <span class="font-bold text-xs text-zinc-100 font-sans">BLE 射频调试控制台与 HCI 报文解析 (RF DTM & HCI Analyzer)</span>
          <p class="text-[10.5px] text-zinc-400 font-sans">
            针对 INGChips (ING918x / ING916x) 及无线 MCU 的射频直测模式 (DTM) 与 UART H4 HCI 协议深度解析。
          </p>
        </div>
      </div>

      <!-- Port Selector & Sub-tab Switcher -->
      <div class="flex items-center gap-2">
        <div class="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-xs">
          <span class="text-zinc-500 font-mono">串口:</span>
          <select
            v-model="selectedPort"
            class="bg-transparent text-emerald-400 font-mono outline-none cursor-pointer"
          >
            <option v-for="p in availablePorts" :key="p.port_name" :value="p.port_name">
              {{ p.port_name }}
            </option>
          </select>
        </div>

        <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded p-0.5 text-xs">
          <button
            @click="activeSubTab = 'dtm'"
            class="px-3 py-1 rounded transition-colors font-medium"
            :class="activeSubTab === 'dtm' ? 'bg-zinc-800 text-blue-400 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
          >
            RF DTM 射频测试
          </button>
          <button
            @click="activeSubTab = 'hci_trace'"
            class="px-3 py-1 rounded transition-colors font-medium flex items-center gap-1.5"
            :class="activeSubTab === 'hci_trace' ? 'bg-zinc-800 text-cyan-400 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
          >
            <span>HCI 协议报文追踪</span>
            <span class="text-[10px] px-1 py-0.2 rounded-full bg-cyan-950 text-cyan-300 font-mono">{{ hciPackets.length }}</span>
          </button>
        </div>
      </div>
    </div>

    <!-- Tab 1: RF DTM Console View -->
    <div v-if="activeSubTab === 'dtm'" class="flex-1 flex overflow-hidden">
      <!-- Left: Test Parameters Configuration -->
      <div class="w-80 border-r border-zinc-800 bg-zinc-900/40 p-4 space-y-4 overflow-y-auto shrink-0 text-xs">
        <div>
          <label class="block text-zinc-400 text-[11px] mb-1 font-medium">测试模式 (Mode)</label>
          <div class="grid grid-cols-2 gap-2">
            <button
              @click="dtmMode = 'tx'"
              class="py-1.5 rounded font-bold border transition-colors"
              :class="dtmMode === 'tx' ? 'bg-blue-600 text-zinc-950 border-blue-500' : 'bg-zinc-900 text-zinc-400 border-zinc-800 hover:bg-zinc-800'"
            >
              发射测试 (Tx Test)
            </button>
            <button
              @click="dtmMode = 'rx'"
              class="py-1.5 rounded font-bold border transition-colors"
              :class="dtmMode === 'rx' ? 'bg-emerald-600 text-zinc-950 border-emerald-500' : 'bg-zinc-900 text-zinc-400 border-zinc-800 hover:bg-zinc-800'"
            >
              接收测试 (Rx Test)
            </button>
          </div>
        </div>

        <div>
          <div class="flex items-center justify-between text-zinc-400 text-[11px] mb-1">
            <span class="font-medium">射频信道 (Channel)</span>
            <span class="font-mono text-cyan-400">CH {{ dtmChannel }} ({{ 2402 + dtmChannel * 2 }} MHz)</span>
          </div>
          <select
            v-model.number="dtmChannel"
            class="w-full bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 outline-none font-mono"
          >
            <option v-for="ch in channelsList" :key="ch.ch" :value="ch.ch">
              CH {{ ch.ch }} - {{ ch.freq }} MHz {{ ch.isAdv ? '[广播信道]' : '' }}
            </option>
          </select>
        </div>

        <div>
          <label class="block text-zinc-400 text-[11px] mb-1 font-medium">物理层 PHY</label>
          <select
            v-model="dtmPhy"
            class="w-full bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 outline-none"
          >
            <option value="1M">LE 1M PHY (标准)</option>
            <option value="2M">LE 2M PHY (高速)</option>
            <option value="coded_s8">LE Coded (S=8, 125kbps 远距离)</option>
            <option value="coded_s2">LE Coded (S=2, 500kbps)</option>
          </select>
        </div>

        <template v-if="dtmMode === 'tx'">
          <div>
            <label class="block text-zinc-400 text-[11px] mb-1 font-medium">载荷序列类型 (Payload)</label>
            <select
              v-model="dtmPayloadType"
              class="w-full bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 outline-none"
            >
              <option value="prbs9">PRBS9 (伪随机二进制序列 9)</option>
              <option value="1010">10101010 序列</option>
              <option value="1111">11110000 序列</option>
              <option value="single_carrier">单载波持续发射 (CW Unmodulated)</option>
            </select>
          </div>

          <div>
            <div class="flex items-center justify-between text-zinc-400 text-[11px] mb-1">
              <span class="font-medium">数据包长度 (Bytes)</span>
              <span class="font-mono text-emerald-400">{{ dtmPacketLength }} B</span>
            </div>
            <input
              type="number"
              v-model.number="dtmPacketLength"
              min="0"
              max="255"
              class="w-full bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 outline-none font-mono"
            />
          </div>
        </template>

        <div class="pt-2">
          <button
            v-if="!isDtmRunning"
            @click="startDtmTest"
            class="w-full py-2 bg-blue-600 hover:bg-blue-500 text-zinc-950 font-bold rounded shadow-sm transition-all flex items-center justify-center gap-1.5"
          >
            <Play class="w-4 h-4 fill-current" />
            <span>开始 {{ dtmMode.toUpperCase() }} 射频测试</span>
          </button>
          <button
            v-else
            @click="stopDtmTest"
            class="w-full py-2 bg-rose-600 hover:bg-rose-500 text-zinc-100 font-bold rounded shadow-sm transition-all flex items-center justify-center gap-1.5 animate-pulse"
          >
            <Square class="w-4 h-4 fill-current" />
            <span>停止测试并获取报告</span>
          </button>
        </div>
      </div>

      <!-- Right: Realtime RF Metrics & Execution Log -->
      <div class="flex-1 flex flex-col bg-zinc-950 overflow-hidden">
        <!-- Live Metrics Cards -->
        <div class="p-4 grid grid-cols-3 gap-3 bg-zinc-900/30 border-b border-zinc-800">
          <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
            <div class="text-[11px] text-zinc-400">测试运行状态</div>
            <div class="text-lg font-bold font-mono mt-1" :class="isDtmRunning ? 'text-emerald-400 animate-pulse' : 'text-zinc-500'">
              {{ isDtmRunning ? 'RUNNING' : 'IDLE' }}
            </div>
          </div>
          <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
            <div class="text-[11px] text-zinc-400">已接收数据包数 (Rx Packets)</div>
            <div class="text-lg font-bold font-mono text-cyan-400 mt-1">{{ rxPacketsCount }}</div>
          </div>
          <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
            <div class="text-[11px] text-zinc-400">误包率估算 (PER %)</div>
            <div class="text-lg font-bold font-mono text-amber-400 mt-1">{{ rxPerRate }}%</div>
          </div>
        </div>

        <!-- DTM Operation Log -->
        <div class="flex-1 p-3 flex flex-col overflow-hidden">
          <div class="flex items-center justify-between text-xs text-zinc-400 mb-2">
            <span class="font-semibold">DTM 控制执行日志</span>
            <button @click="dtmLogs = []" class="text-[11px] text-zinc-500 hover:text-zinc-300">清空</button>
          </div>
          <div class="flex-1 bg-zinc-900/60 border border-zinc-800 rounded-lg p-3 font-mono text-[11px] overflow-y-auto space-y-1.5">
            <div
              v-for="(log, idx) in dtmLogs"
              :key="idx"
              class="flex items-start gap-2"
            >
              <span class="text-zinc-600">[{{ log.time }}]</span>
              <span
                :class="[
                  log.status === 'info' ? 'text-zinc-300' : '',
                  log.status === 'success' ? 'text-emerald-400' : '',
                  log.status === 'error' ? 'text-rose-400 font-bold' : ''
                ]"
              >
                {{ log.text }}
              </span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Tab 2: HCI Packet Inspector (Wireshark-like) -->
    <div v-else class="flex-1 flex flex-col overflow-hidden">
      <!-- Filter Bar -->
      <div class="bg-zinc-900/80 border-b border-zinc-800 px-4 py-2 flex items-center justify-between gap-4 text-xs">
        <div class="flex items-center gap-2">
          <Filter class="w-3.5 h-3.5 text-zinc-400" />
          <div class="flex gap-1 bg-zinc-950 border border-zinc-800 rounded p-0.5 text-[11px]">
            <button
              v-for="ft in ['ALL', 'CMD', 'EVT', 'ACL']"
              :key="ft"
              @click="filterType = ft"
              class="px-2 py-0.5 rounded transition-colors"
              :class="filterType === ft ? 'bg-zinc-800 text-cyan-400 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
            >
              {{ ft }}
            </button>
          </div>

          <input
            v-model="filterKeyword"
            class="bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1 text-xs text-zinc-200 outline-none w-64 placeholder:text-zinc-600"
            placeholder="过滤 Opcode / 事件 / MAC 地址..."
          />
        </div>

        <div class="flex items-center gap-2">
          <button
            @click="exportPcap"
            class="px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded text-xs flex items-center gap-1 border border-zinc-700 transition-colors"
          >
            <Download class="w-3.5 h-3.5 text-cyan-400" />
            <span>导出报文记录</span>
          </button>
          <button
            @click="clearPackets"
            class="px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-400 hover:text-zinc-200 rounded text-xs transition-colors"
          >
            清空
          </button>
        </div>
      </div>

      <!-- Main Packet Inspector: Upper Table + Lower Detail -->
      <div class="flex-1 flex flex-col overflow-hidden divide-y divide-zinc-800">
        <!-- Packets List Table -->
        <div class="flex-1 overflow-y-auto">
          <table class="w-full text-left text-xs border-collapse">
            <thead class="bg-zinc-900 text-zinc-400 text-[11px] font-mono sticky top-0 border-b border-zinc-800">
              <tr>
                <th class="p-2 w-16 text-center">序号</th>
                <th class="p-2 w-28">时间</th>
                <th class="p-2 w-20">类型</th>
                <th class="p-2 w-48">事件 / Opcode</th>
                <th class="p-2 w-16">长度</th>
                <th class="p-2">摘要信息</th>
              </tr>
            </thead>
            <tbody class="font-mono text-[11.5px] divide-y divide-zinc-900">
              <tr
                v-for="pkt in filteredHciPackets"
                :key="pkt.id"
                @click="selectedPacketId = pkt.id"
                class="hover:bg-zinc-800/50 cursor-pointer transition-colors"
                :class="selectedPacketId === pkt.id ? 'bg-cyan-950/40 text-cyan-200 font-semibold' : ''"
              >
                <td class="p-2 text-center text-zinc-500">{{ pkt.id }}</td>
                <td class="p-2 text-zinc-400">{{ pkt.timestamp }}</td>
                <td class="p-2">
                  <span
                    class="px-1.5 py-0.5 rounded text-[10px] font-bold"
                    :class="[
                      pkt.type === 'CMD' ? 'bg-blue-950 text-blue-400 border border-blue-800/50' : '',
                      pkt.type === 'EVT' ? 'bg-emerald-950 text-emerald-400 border border-emerald-800/50' : '',
                      pkt.type === 'ACL' ? 'bg-purple-950 text-purple-400 border border-purple-800/50' : '',
                      pkt.type === 'RAW' ? 'bg-zinc-800 text-zinc-400' : ''
                    ]"
                  >
                    {{ pkt.type }}
                  </span>
                </td>
                <td class="p-2 text-zinc-200 font-sans truncate">{{ pkt.opcodeOrEvent }}</td>
                <td class="p-2 text-zinc-400">{{ pkt.length }}B</td>
                <td class="p-2 text-zinc-400 font-sans truncate">{{ pkt.summary }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Packet Detail Inspector (Bottom Pane) -->
        <div class="h-48 bg-zinc-950 p-3 flex gap-4 overflow-hidden shrink-0">
          <div v-if="selectedPacket" class="flex-1 flex gap-4 overflow-hidden">
            <!-- Fields Decoded Tree -->
            <div class="w-1/2 border border-zinc-800 rounded p-2.5 overflow-y-auto font-sans text-xs space-y-1.5">
              <div class="font-bold text-zinc-300 pb-1 border-b border-zinc-800 text-[11px]">字段解码 (Decoded Fields)</div>
              <div
                v-for="(f, fIdx) in selectedPacket.fields"
                :key="fIdx"
                class="flex items-center justify-between text-[11.5px]"
              >
                <span class="text-zinc-400">{{ f.name }}:</span>
                <span class="font-mono text-cyan-300">{{ f.value }}</span>
              </div>
            </div>

            <!-- Raw Hex Dump -->
            <div class="flex-1 border border-zinc-800 rounded p-2.5 overflow-y-auto font-mono text-xs">
              <div class="font-bold text-zinc-300 pb-1 border-b border-zinc-800 text-[11px] font-sans">原始数据 (Hex Stream)</div>
              <p class="text-zinc-400 mt-2 leading-relaxed tracking-wider break-all text-[11px]">
                {{ selectedPacket.rawHex }}
              </p>
            </div>
          </div>

          <div v-else class="flex-1 flex items-center justify-center text-zinc-600 text-xs">
            点击上方报文列表中任意一条记录查看协议详细解码与原始十六进制
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
