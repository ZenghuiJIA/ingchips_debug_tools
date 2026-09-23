<script setup lang="ts">
import { ref, computed } from 'vue';
import {
  Layers,
  Send,
  Play,
  Square,
  AlertTriangle,
  Binary,
  X
} from '@lucide/vue';
import { safeInvoke } from '../utils/ipc';
import { buildModbusRequest, parseModbusResponse, type ModbusResponseResult } from '../utils/modbus';

const props = defineProps<{
  portName: string;
  isConnected: boolean;
}>();

const emit = defineEmits<{
  (e: 'close'): void;
  (e: 'log', text: string, type: 'rx' | 'tx' | 'info' | 'error'): void;
  (e: 'bytes-sent', count: number): void;
}>();

const modbusMode = ref<'rtu' | 'ascii'>('rtu');
const slaveId = ref<number>(1);
const funcCode = ref<number>(3); // 03 = Read Holding Registers
const startAddrInput = ref<string>('0');
const countOrValInput = ref<string>('10');
const extraValuesInput = ref<string>(''); // For 0x10 multiple registers

const isPolling = ref<boolean>(false);
const pollIntervalMs = ref<number>(500);
let pollTimer: any = null;

const parsedResult = ref<ModbusResponseResult | null>(null);
const displayFormat = ref<'uint16' | 'int16' | 'hex' | 'float32'>('uint16');

const funcCodeOptions = [
  { value: 1, label: '01: 读线圈 (Read Coils)' },
  { value: 2, label: '02: 读离散输入 (Read Discrete Inputs)' },
  { value: 3, label: '03: 读保持寄存器 (Read Holding Regs)' },
  { value: 4, label: '04: 读输入寄存器 (Read Input Regs)' },
  { value: 5, label: '05: 写单个线圈 (Write Single Coil)' },
  { value: 6, label: '06: 写单个寄存器 (Write Single Reg)' },
  { value: 16, label: '10: 写多个寄存器 (Write Multiple Regs)' },
];

function parseNumericInput(val: string): number {
  const trimmed = val.trim();
  if (trimmed.toLowerCase().startsWith('0x')) {
    return parseInt(trimmed, 16) || 0;
  }
  return parseInt(trimmed, 10) || 0;
}

const computedStartAddr = computed(() => parseNumericInput(startAddrInput.value));
const computedCountOrVal = computed(() => parseNumericInput(countOrValInput.value));

async function sendModbusCommand() {
  if (!props.isConnected) {
    emit('log', '串口未连接，无法发送 Modbus 请求', 'error');
    return;
  }

  let extraValues: number[] | undefined = undefined;
  if (funcCode.value === 16) {
    extraValues = extraValuesInput.value
      .split(/[\s,]+/)
      .map(s => parseNumericInput(s))
      .filter(n => !isNaN(n));
  }

  try {
    const frame = await buildModbusRequest(
      slaveId.value,
      funcCode.value,
      computedStartAddr.value,
      computedCountOrVal.value,
      extraValues,
      modbusMode.value
    );

    const sentCount: number = await safeInvoke('send_serial_data', {
      data: frame,
      portName: props.portName
    });
    emit('bytes-sent', sentCount);

    if (modbusMode.value === 'ascii') {
      const asciiStr = new TextDecoder().decode(new Uint8Array(frame)).trim();
      emit('log', `[Modbus ASCII TX] -> ${asciiStr}`, 'tx');
    } else {
      const hexStr = frame.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');
      emit('log', `[Modbus RTU TX] -> ${hexStr}`, 'tx');
    }
  } catch (err: any) {
    emit('log', `Modbus 发送失败: ${err}`, 'error');
  }
}

/**
 * Feeds received raw bytes from serial to Modbus response parser
 */
async function feedIncomingBytes(bytes: Uint8Array) {
  if (bytes.length < 3) return;
  try {
    const res = await parseModbusResponse(props.portName, computedStartAddr.value, Array.from(bytes));
    if (res && res.slave_id === slaveId.value) {
      parsedResult.value = res;
      if (res.is_exception) {
        emit('log', `[Modbus 异常响应] 从机 ${res.slave_id} 报错: ${res.exception_desc}`, 'error');
      } else {
        emit('log', `[Modbus ${res.mode.toUpperCase()} RX] 从机 ${res.slave_id} 响应成功 (${res.registers.length} 个寄存器)`, 'rx');
      }
    }
  } catch (err) {
    // Not a valid Modbus frame or CRC/LRC mismatch, ignore
  }
}

function togglePolling() {
  if (isPolling.value) {
    stopPolling();
  } else {
    startPolling();
  }
}

function startPolling() {
  if (!props.isConnected) return;
  isPolling.value = true;
  sendModbusCommand();
  pollTimer = setInterval(() => {
    if (!props.isConnected) {
      stopPolling();
      return;
    }
    sendModbusCommand();
  }, Math.max(100, pollIntervalMs.value));
}

function stopPolling() {
  isPolling.value = false;
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

/**
 * Combines 2 contiguous 16-bit registers into IEEE-754 32-bit float (Big Endian)
 */
function getFloat32(u0: number, u1: number): string {
  const buf = new ArrayBuffer(4);
  const view = new DataView(buf);
  view.setUint16(0, u0);
  view.setUint16(2, u1);
  const f = view.getFloat32(0);
  return f.toFixed(4);
}

defineExpose({
  feedIncomingBytes,
  stopPolling
});
</script>

<template>
  <div class="w-88 h-full bg-zinc-900 border-l border-zinc-800 flex flex-col font-mono text-xs select-none">
    <!-- Header -->
    <div class="px-3 py-2 border-b border-zinc-800 flex items-center justify-between bg-zinc-900/90">
      <div class="flex items-center gap-1.5 font-semibold text-amber-300">
        <Layers class="w-4 h-4 text-amber-400" />
        <span>Modbus 主站控制台</span>
      </div>
      <div class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded p-0.5 text-[10px]">
        <button
          @click="modbusMode = 'rtu'"
          class="px-1.5 py-0.5 rounded transition-colors"
          :class="modbusMode === 'rtu' ? 'bg-amber-500/20 text-amber-300 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
        >
          RTU
        </button>
        <button
          @click="modbusMode = 'ascii'"
          class="px-1.5 py-0.5 rounded transition-colors"
          :class="modbusMode === 'ascii' ? 'bg-amber-500/20 text-amber-300 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
        >
          ASCII
        </button>
      </div>
      <button
        @click="emit('close')"
        class="p-1 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 rounded transition-colors"
      >
        <X class="w-4 h-4" />
      </button>
    </div>

    <!-- Parameter Config Form -->
    <div class="p-3 border-b border-zinc-800 space-y-2.5 bg-zinc-950/40">
      <!-- Row 1: Slave ID & Function Code -->
      <div class="grid grid-cols-2 gap-2">
        <div>
          <label class="block text-[10px] text-zinc-400 mb-0.5">从机地址 (Slave ID):</label>
          <input
            v-model.number="slaveId"
            type="number"
            min="1"
            max="247"
            class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-2 py-1 text-zinc-100 focus:border-amber-500 outline-none"
          />
        </div>
        <div>
          <label class="block text-[10px] text-zinc-400 mb-0.5">功能码 (Function):</label>
          <select
            v-model="funcCode"
            class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-1.5 py-1 text-zinc-200 focus:border-amber-500 outline-none text-[11px]"
          >
            <option v-for="opt in funcCodeOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>
      </div>

      <!-- Row 2: Start Address & Count/Value -->
      <div class="grid grid-cols-2 gap-2">
        <div>
          <label class="block text-[10px] text-zinc-400 mb-0.5">起始地址 (Hex/Dec):</label>
          <input
            v-model="startAddrInput"
            type="text"
            placeholder="如 0x0000 或 0"
            class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-2 py-1 text-zinc-100 focus:border-amber-500 outline-none"
          />
        </div>
        <div>
          <label class="block text-[10px] text-zinc-400 mb-0.5">
            {{ funcCode === 5 || funcCode === 6 ? '写入数值 (Dec/Hex):' : '读取数量 (Count):' }}
          </label>
          <input
            v-model="countOrValInput"
            type="text"
            placeholder="如 10 或 0x1234"
            class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-2 py-1 text-zinc-100 focus:border-amber-500 outline-none"
          />
        </div>
      </div>

      <!-- Row 3: Extra values for 0x10 multiple registers -->
      <div v-if="funcCode === 16">
        <label class="block text-[10px] text-zinc-400 mb-0.5">写入数据列表 (以空格或逗号分隔):</label>
        <input
          v-model="extraValuesInput"
          type="text"
          placeholder="如: 0x1122 0x3344 1234"
          class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-2 py-1 text-zinc-100 focus:border-amber-500 outline-none"
        />
      </div>

      <!-- Action Buttons: Send & Polling -->
      <div class="flex items-center gap-2 pt-1">
        <button
          @click="sendModbusCommand"
          :disabled="!isConnected"
          class="flex-1 flex items-center justify-center gap-1.5 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded font-medium transition-colors disabled:opacity-40"
        >
          <Send class="w-3.5 h-3.5" />
          <span>单次发送 (带CRC)</span>
        </button>

        <button
          @click="togglePolling"
          :disabled="!isConnected"
          class="flex items-center gap-1 px-3 py-1.5 rounded font-medium border transition-colors disabled:opacity-40"
          :class="isPolling ? 'bg-rose-950 text-rose-300 border-rose-800' : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
        >
          <component :is="isPolling ? Square : Play" class="w-3.5 h-3.5" :class="{ 'fill-rose-400 text-rose-400': isPolling }" />
          <span>{{ isPolling ? '停止轮询' : '自动轮询' }}</span>
        </button>
      </div>

      <!-- Polling interval setting -->
      <div v-if="isPolling" class="flex items-center justify-between text-[11px] text-zinc-400 px-1">
        <span>轮询周期:</span>
        <div class="flex items-center gap-1">
          <input
            v-model.number="pollIntervalMs"
            type="number"
            step="100"
            min="50"
            class="w-16 bg-zinc-900 border border-zinc-800 rounded px-1 text-center text-zinc-200"
          />
          <span>ms</span>
        </div>
      </div>
    </div>

    <!-- Response Display Section -->
    <div class="flex-1 flex flex-col overflow-hidden p-3 min-h-0">
      <div class="flex items-center justify-between mb-2">
        <span class="text-[11px] font-semibold text-zinc-300">响应寄存器解析:</span>
        
        <!-- Format selector -->
        <select
          v-model="displayFormat"
          class="bg-zinc-950 border border-zinc-800 text-[10px] text-zinc-300 rounded px-1.5 py-0.5 outline-none"
        >
          <option value="uint16">UInt16 (无符号)</option>
          <option value="int16">Int16 (有符号)</option>
          <option value="hex">HEX 原生</option>
          <option value="float32">Float32 (两字组合)</option>
        </select>
      </div>

      <!-- Exception Alert -->
      <div
        v-if="parsedResult?.is_exception"
        class="bg-rose-950/70 border border-rose-800 rounded p-2.5 mb-2 flex items-start gap-2 text-rose-300 text-[11px]"
      >
        <AlertTriangle class="w-4 h-4 shrink-0 text-rose-400 mt-0.5" />
        <div>
          <div class="font-bold">从机返回异常应答</div>
          <div class="text-[10px] text-rose-200 mt-0.5">{{ parsedResult.exception_desc }}</div>
        </div>
      </div>

      <!-- Registers Table -->
      <div
        v-if="parsedResult && parsedResult.registers.length > 0"
        class="flex-1 border border-zinc-800 rounded overflow-auto bg-zinc-950 select-text"
      >
        <table class="w-full text-[11px] text-left">
          <thead class="bg-zinc-900 text-zinc-400 sticky top-0 border-b border-zinc-800">
            <tr>
              <th class="p-1.5 pl-2 font-normal">地址</th>
              <th class="p-1.5 font-normal">HEX</th>
              <th class="p-1.5 font-normal">数值</th>
            </tr>
          </thead>
          <tbody class="divide-y divide-zinc-900">
            <template v-if="displayFormat !== 'float32'">
              <tr
                v-for="reg in parsedResult.registers"
                :key="reg.address"
                class="hover:bg-zinc-900/60"
              >
                <td class="p-1.5 pl-2 text-zinc-400 font-mono">{{ reg.address }} (0x{{ reg.address.toString(16).padStart(4, '0').toUpperCase() }})</td>
                <td class="p-1.5 text-amber-300/90 font-mono">{{ reg.raw_hex }}</td>
                <td class="p-1.5 text-emerald-400 font-mono font-medium">
                  {{ displayFormat === 'uint16' ? reg.u16_val : displayFormat === 'int16' ? reg.i16_val : reg.raw_hex }}
                </td>
              </tr>
            </template>

            <!-- Float32 Pair representation -->
            <template v-else>
              <tr
                v-for="idx in Math.ceil(parsedResult.registers.length / 2)"
                :key="idx"
                class="hover:bg-zinc-900/60"
              >
                <td class="p-1.5 pl-2 text-zinc-400 font-mono">
                  {{ parsedResult.registers[(idx - 1) * 2]?.address }} ~ {{ (parsedResult.registers[(idx - 1) * 2]?.address ?? 0) + 1 }}
                </td>
                <td class="p-1.5 text-amber-300/90 font-mono">
                  {{ parsedResult.registers[(idx - 1) * 2]?.raw_hex }} {{ parsedResult.registers[(idx - 1) * 2 + 1]?.raw_hex || '' }}
                </td>
                <td class="p-1.5 text-emerald-400 font-mono font-medium">
                  {{ getFloat32(parsedResult.registers[(idx - 1) * 2]?.u16_val ?? 0, parsedResult.registers[(idx - 1) * 2 + 1]?.u16_val ?? 0) }}
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>

      <!-- Empty State -->
      <div
        v-else-if="!parsedResult?.is_exception"
        class="flex-1 flex flex-col items-center justify-center text-zinc-600 border border-dashed border-zinc-800 rounded p-4 text-center"
      >
        <Binary class="w-8 h-8 mb-2 opacity-30" />
        <p>暂无 Modbus 响应数据</p>
        <p class="text-[10px] text-zinc-700 mt-1">点击“单次发送”或启动轮询以获取数据</p>
      </div>
    </div>
  </div>
</template>
