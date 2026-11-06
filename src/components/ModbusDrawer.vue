<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue';
import {
  Layers,
  Send,
  Play,
  Square,
  AlertTriangle,
  Binary,
  X,
  RefreshCw,
  Edit2,
  Check,
  ChevronDown,
  ChevronUp,
  Cpu,
  Radio,
  ToggleLeft,
  ToggleRight,
  Trash2,
  Plus
} from '@lucide/vue';
import { safeInvoke } from '../utils/ipc';
import {
  buildModbusRequest,
  parseModbusResponse,
  handleModbusSlaveFrame,
  parseModbus32Bit,
  formatSingleRegister,
  type ModbusResponseResult,
  type ModbusByteOrder,
  type ModbusDisplayFormat
} from '../utils/modbus';
import { t } from '../utils/i18n';

const props = defineProps<{
  portName: string;
  isConnected: boolean;
}>();

const emit = defineEmits<{
  (e: 'close'): void;
  (e: 'log', text: string, type: 'rx' | 'tx' | 'info' | 'error'): void;
  (e: 'bytes-sent', count: number): void;
}>();

// --- Main Mode: Master vs Slave ---
const currentRole = ref<'master' | 'slave'>('master');
const modbusMode = ref<'rtu' | 'ascii'>('rtu');

// --- Master Mode Parameters ---
const slaveId = ref<number>(1);
const funcCode = ref<number>(3); // 03 = Read Holding Registers
const startAddrInput = ref<string>('0');
const countOrValInput = ref<string>('10');
const extraValuesInput = ref<string>(''); // For 0x0F / 0x10 multiple coils/registers

const isPolling = ref<boolean>(false);
const pollIntervalMs = ref<number>(500);
let pollTimer: any = null;

// --- Data Format & Endianness ---
const displayFormat = ref<ModbusDisplayFormat>('uint16');
const byteOrder = ref<ModbusByteOrder>('AB_CD');

// --- Results & Stats ---
const parsedResult = ref<ModbusResponseResult | null>(null);
const stats = ref({
  txCount: 0,
  rxCount: 0,
  errCount: 0
});

// --- Traffic Trace Log ---
interface ModbusLogItem {
  id: number;
  time: string;
  dir: 'tx' | 'rx';
  rawHex: string;
  desc: string;
  isError?: boolean;
}
const trafficLogs = ref<ModbusLogItem[]>([]);
const isLogPanelOpen = ref<boolean>(false);
let logIdCounter = 1;

// --- Quick Inline Edit State ---
const editingAddr = ref<number | null>(null);
const editValInput = ref<string>('');

// --- Slave Emulator State ---
const slaveSimId = ref<number>(1);
const slaveHoldingRegs = ref<Record<number, number>>({
  0: 100,
  1: 200,
  2: 1234,
  3: 5678,
  4: 0x1122
});
const slaveCoils = ref<Record<number, boolean>>({
  0: true,
  1: false,
  2: true,
  3: true
});
const slaveNewAddrInput = ref<string>('');
const slaveNewValInput = ref<string>('');
const slaveAreaType = ref<'holding' | 'coils'>('holding');

// --- Frame Reassembly Buffer (for RTU & ASCII) ---
let rxBuffer: number[] = [];
let rxFrameTimer: any = null;

const funcCodeOptions = [
  { value: 1, label: t('mb_fn_01') },
  { value: 2, label: t('mb_fn_02') },
  { value: 3, label: t('mb_fn_03') },
  { value: 4, label: t('mb_fn_04') },
  { value: 5, label: t('mb_fn_05') },
  { value: 6, label: t('mb_fn_06') },
  { value: 15, label: t('mb_fn_0f') },
  { value: 16, label: t('mb_fn_10') }
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

const is32BitFormat = computed(() => {
  return ['uint32', 'int32', 'float32'].includes(displayFormat.value);
});

function addTrafficLog(dir: 'tx' | 'rx', rawHex: string, desc: string, isError = false) {
  const now = new Date();
  const time = `${now.toTimeString().split(' ')[0]}.${now.getMilliseconds().toString().padStart(3, '0')}`;
  trafficLogs.value.unshift({
    id: logIdCounter++,
    time,
    dir,
    rawHex,
    desc,
    isError
  });
  if (trafficLogs.value.length > 100) {
    trafficLogs.value.pop();
  }
}

// --- Send Command (Master) ---
async function sendModbusCommand() {
  if (!props.isConnected) {
    emit('log', t('mb_err_no_conn'), 'error');
    return;
  }

  let extraValues: number[] | undefined = undefined;
  if (funcCode.value === 15 || funcCode.value === 16) {
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
    stats.value.txCount++;

    const hexStr = frame.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');
    if (modbusMode.value === 'ascii') {
      const asciiStr = new TextDecoder().decode(new Uint8Array(frame)).trim();
      emit('log', `[Modbus ASCII TX] -> ${asciiStr}`, 'tx');
      addTrafficLog('tx', asciiStr, `Master Send [Fn ${funcCode.value}]`);
    } else {
      emit('log', `[Modbus RTU TX] -> ${hexStr}`, 'tx');
      addTrafficLog('tx', hexStr, `Master Send [Fn ${funcCode.value}]`);
    }
  } catch (err: any) {
    stats.value.errCount++;
    emit('log', t('mb_err_send_failed', { err: String(err) }), 'error');
  }
}

// --- Quick Write (Click on row to modify) ---
function startInlineEdit(addr: number, curVal: number) {
  editingAddr.value = addr;
  editValInput.value = curVal.toString();
}

async function confirmInlineEdit(addr: number) {
  if (!props.isConnected) return;
  const val = parseNumericInput(editValInput.value);
  editingAddr.value = null;

  try {
    const frame = await buildModbusRequest(
      slaveId.value,
      6, // Write single register
      addr,
      val,
      undefined,
      modbusMode.value
    );

    const sentCount: number = await safeInvoke('send_serial_data', {
      data: frame,
      portName: props.portName
    });
    emit('bytes-sent', sentCount);
    stats.value.txCount++;
    const hexStr = frame.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');
    emit('log', `[Modbus Write 06] Addr 0x${addr.toString(16).toUpperCase()} = ${val}`, 'tx');
    addTrafficLog('tx', hexStr, `Write Reg [0x${addr.toString(16).toUpperCase()}] = ${val}`);
  } catch (err: any) {
    stats.value.errCount++;
    emit('log', t('mb_err_send_failed', { err: String(err) }), 'error');
  }
}

async function quickToggleCoil(addr: number, currentState: boolean) {
  if (!props.isConnected) return;
  const newState = !currentState;
  try {
    const frame = await buildModbusRequest(
      slaveId.value,
      5, // Write single coil
      addr,
      newState ? 1 : 0,
      undefined,
      modbusMode.value
    );

    const sentCount: number = await safeInvoke('send_serial_data', {
      data: frame,
      portName: props.portName
    });
    emit('bytes-sent', sentCount);
    stats.value.txCount++;
    const hexStr = frame.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');
    emit('log', `[Modbus Coil 05] Addr 0x${addr.toString(16).toUpperCase()} = ${newState ? 'ON' : 'OFF'}`, 'tx');
    addTrafficLog('tx', hexStr, `Toggle Coil [0x${addr.toString(16).toUpperCase()}] = ${newState ? 'ON' : 'OFF'}`);
  } catch (err: any) {
    stats.value.errCount++;
    emit('log', t('mb_err_send_failed', { err: String(err) }), 'error');
  }
}

// --- Frame Processing & Debounced Reassembly ---
function feedIncomingBytes(bytes: Uint8Array) {
  if (bytes.length === 0) return;

  // Append to reassembly buffer
  for (let i = 0; i < bytes.length; i++) {
    rxBuffer.push(bytes[i]);
  }

  // Clear existing frame debounce timer
  if (rxFrameTimer) {
    clearTimeout(rxFrameTimer);
    rxFrameTimer = null;
  }

  // For ASCII mode: check if buffer contains ':' and '\r\n'
  if (modbusMode.value === 'ascii') {
    const startIdx = rxBuffer.indexOf(58); // ':'
    if (startIdx >= 0) {
      const endIdx = rxBuffer.indexOf(10, startIdx); // '\n'
      if (endIdx > startIdx) {
        const frame = rxBuffer.slice(startIdx, endIdx + 1);
        rxBuffer = rxBuffer.slice(endIdx + 1);
        processCompleteFrame(frame);
        return;
      }
    }
  }

  // For RTU mode: 25ms silence timer constitutes full frame
  rxFrameTimer = setTimeout(() => {
    if (rxBuffer.length >= 3) {
      const frame = [...rxBuffer];
      rxBuffer = [];
      processCompleteFrame(frame);
    }
  }, 25);
}

async function processCompleteFrame(frameBytes: number[]) {
  const hexStr = frameBytes.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');

  // 1. If currently in Slave Simulator Mode, respond to incoming Master request
  if (currentRole.value === 'slave') {
    try {
      const res = await handleModbusSlaveFrame(
        slaveSimId.value,
        frameBytes,
        slaveHoldingRegs.value,
        slaveHoldingRegs.value,
        slaveCoils.value,
        slaveCoils.value
      );

      if (res && res.handled_func) {
        stats.value.rxCount++;
        addTrafficLog('rx', hexStr, res.log_desc || `Slave Handled [Fn ${res.handled_func}]`);
        emit('log', `[Modbus Slave RX] ${res.log_desc || ''}`, 'rx');

        // Update local holding registers & coils if modified
        if (res.updated_holding_registers) {
          slaveHoldingRegs.value = { ...slaveHoldingRegs.value, ...res.updated_holding_registers };
        }
        if (res.updated_coils) {
          slaveCoils.value = { ...slaveCoils.value, ...res.updated_coils };
        }

        // Send back response frame if generated
        if (res.response_bytes && res.response_bytes.length > 0) {
          const sentCount: number = await safeInvoke('send_serial_data', {
            data: res.response_bytes,
            portName: props.portName
          });
          emit('bytes-sent', sentCount);
          stats.value.txCount++;
          const respHex = res.response_bytes.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');
          addTrafficLog('tx', respHex, `Slave Auto-Reply [Fn ${res.handled_func}]`);
        }
      }
    } catch (err) {
      // Not for this slave or invalid CRC, ignore
    }
    return;
  }

  // 2. Otherwise Master Mode: parse incoming response
  try {
    const res = await parseModbusResponse(props.portName, computedStartAddr.value, frameBytes);
    if (res && res.slave_id === slaveId.value) {
      parsedResult.value = res;
      stats.value.rxCount++;

      if (res.is_exception) {
        stats.value.errCount++;
        emit('log', t('mb_err_exception_resp', { slave: res.slave_id, desc: res.exception_desc || '' }), 'error');
        addTrafficLog('rx', hexStr, `Exception: ${res.exception_desc || ''}`, true);
      } else {
        const desc = res.description || t('mb_rx_success', { mode: res.mode.toUpperCase(), slave: res.slave_id, count: res.registers.length });
        emit('log', desc, 'rx');
        addTrafficLog('rx', hexStr, desc);
      }
    }
  } catch (err) {
    // CRC mismatch or fragmented noise, ignore
  }
}

// --- Polling Control ---
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
  }, Math.max(80, pollIntervalMs.value));
}

function stopPolling() {
  isPolling.value = false;
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

function resetStats() {
  stats.value = { txCount: 0, rxCount: 0, errCount: 0 };
}

function clearLogs() {
  trafficLogs.value = [];
}

// --- Slave Edit Helpers ---
function addSlavePoint() {
  const addr = parseNumericInput(slaveNewAddrInput.value);
  if (slaveAreaType.value === 'holding') {
    const val = parseNumericInput(slaveNewValInput.value);
    slaveHoldingRegs.value[addr] = val;
  } else {
    const b = slaveNewValInput.value.trim() === '1' || slaveNewValInput.value.toLowerCase() === 'true';
    slaveCoils.value[addr] = b;
  }
  slaveNewAddrInput.value = '';
  slaveNewValInput.value = '';
}

function removeSlavePoint(type: 'holding' | 'coils', addr: number) {
  if (type === 'holding') {
    delete slaveHoldingRegs.value[addr];
  } else {
    delete slaveCoils.value[addr];
  }
}

onUnmounted(() => {
  stopPolling();
  if (rxFrameTimer) clearTimeout(rxFrameTimer);
});

defineExpose({
  feedIncomingBytes,
  stopPolling
});
</script>

<template>
  <div class="w-full h-full bg-zinc-900 border-l border-zinc-800 flex flex-col font-mono text-xs select-none">
    <!-- Top Header -->
    <div class="px-3 py-2 border-b border-zinc-800 flex items-center justify-between bg-zinc-900/90 shrink-0">
      <div class="flex items-center gap-2">
        <Layers class="w-4 h-4 text-amber-400" />
        <span class="font-bold text-amber-300">{{ t("mb_console_title") }}</span>
      </div>

      <!-- Center: Master / Slave Role Switcher -->
      <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded p-0.5 text-[10px]">
        <button
          @click="currentRole = 'master'"
          class="px-2 py-0.5 rounded transition-colors flex items-center gap-1"
          :class="currentRole === 'master' ? 'bg-amber-500/20 text-amber-300 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
        >
          <Radio class="w-3 h-3" />
          <span>{{ t("mb_mode_master") }}</span>
        </button>
        <button
          @click="currentRole = 'slave'"
          class="px-2 py-0.5 rounded transition-colors flex items-center gap-1"
          :class="currentRole === 'slave' ? 'bg-cyan-500/20 text-cyan-300 font-bold' : 'text-zinc-400 hover:text-zinc-200'"
        >
          <Cpu class="w-3 h-3" />
          <span>{{ t("mb_mode_slave") }}</span>
        </button>
      </div>

      <!-- Right controls: RTU/ASCII + Close -->
      <div class="flex items-center gap-2">
        <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded p-0.5 text-[10px]">
          <button
            @click="modbusMode = 'rtu'"
            class="px-1.5 py-0.5 rounded transition-colors"
            :class="modbusMode === 'rtu' ? 'bg-zinc-800 text-zinc-100 font-bold' : 'text-zinc-500 hover:text-zinc-300'"
          >
            RTU
          </button>
          <button
            @click="modbusMode = 'ascii'"
            class="px-1.5 py-0.5 rounded transition-colors"
            :class="modbusMode === 'ascii' ? 'bg-zinc-800 text-zinc-100 font-bold' : 'text-zinc-500 hover:text-zinc-300'"
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
    </div>

    <!-- Communication Stats Bar -->
    <div class="px-3 py-1 bg-zinc-950/80 border-b border-zinc-800 flex items-center justify-between text-[10px] text-zinc-400 shrink-0">
      <div class="flex items-center gap-3">
        <span>{{ t("mb_stats_tx") }}: <strong class="text-zinc-200">{{ stats.txCount }}</strong></span>
        <span>{{ t("mb_stats_rx") }}: <strong class="text-emerald-400">{{ stats.rxCount }}</strong></span>
        <span>{{ t("mb_stats_err") }}: <strong :class="stats.errCount > 0 ? 'text-rose-400 font-bold' : 'text-zinc-500'">{{ stats.errCount }}</strong></span>
      </div>
      <button
        @click="resetStats"
        class="text-zinc-500 hover:text-zinc-300 flex items-center gap-0.5 hover:underline"
        :title="t('mb_stats_reset')"
      >
        <RefreshCw class="w-2.5 h-2.5" />
        <span>{{ t("mb_stats_reset") }}</span>
      </button>
    </div>

    <!-- ==================== MASTER MODE VIEW ==================== -->
    <template v-if="currentRole === 'master'">
      <!-- Request Config Form -->
      <div class="p-3 border-b border-zinc-800 space-y-2.5 bg-zinc-950/40 shrink-0">
        <!-- Row 1: Slave ID & Function Code -->
        <div class="grid grid-cols-2 gap-2">
          <div>
            <label class="block text-[10px] text-zinc-400 mb-0.5">{{ t("mb_slave_id_label") }}</label>
            <input
              v-model.number="slaveId"
              type="number"
              min="1"
              max="247"
              class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-2 py-1 text-zinc-100 focus:border-amber-500 outline-none"
            />
          </div>
          <div>
            <label class="block text-[10px] text-zinc-400 mb-0.5">{{ t("mb_func_code_label") }}</label>
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
            <label class="block text-[10px] text-zinc-400 mb-0.5">{{ t("mb_start_addr_label") }}</label>
            <input
              v-model="startAddrInput"
              type="text"
              :placeholder="t('mb_start_addr_placeholder')"
              class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-2 py-1 text-zinc-100 focus:border-amber-500 outline-none"
            />
          </div>
          <div>
            <label class="block text-[10px] text-zinc-400 mb-0.5">
              {{ funcCode === 5 || funcCode === 6 ? t('mb_val_or_count_write') : t('mb_val_or_count_read') }}
            </label>
            <input
              v-model="countOrValInput"
              type="text"
              :placeholder="t('mb_val_or_count_placeholder')"
              class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-2 py-1 text-zinc-100 focus:border-amber-500 outline-none"
            />
          </div>
        </div>

        <!-- Row 3: Multiple values for 0x0F / 0x10 -->
        <div v-if="funcCode === 15 || funcCode === 16">
          <label class="block text-[10px] text-zinc-400 mb-0.5">{{ t("mb_write_list_label") }}</label>
          <input
            v-model="extraValuesInput"
            type="text"
            :placeholder="t('mb_write_list_placeholder')"
            class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-2 py-1 text-zinc-100 focus:border-amber-500 outline-none"
          />
        </div>

        <!-- Actions: Send & Auto Polling -->
        <div class="flex items-center gap-2 pt-1">
          <button
            @click="sendModbusCommand"
            :disabled="!isConnected"
            class="flex-1 flex items-center justify-center gap-1.5 py-1.5 bg-amber-600 hover:bg-amber-500 text-white rounded font-medium transition-colors disabled:opacity-40"
          >
            <Send class="w-3.5 h-3.5" />
            <span>{{ t('modbus_send') }}</span>
          </button>

          <button
            @click="togglePolling"
            :disabled="!isConnected"
            class="flex items-center gap-1 px-3 py-1.5 rounded font-medium border transition-colors disabled:opacity-40"
            :class="isPolling ? 'bg-rose-950 text-rose-300 border-rose-800' : 'bg-zinc-800 text-zinc-300 border-zinc-700 hover:bg-zinc-700'"
          >
            <component :is="isPolling ? Square : Play" class="w-3.5 h-3.5" :class="{ 'fill-rose-400 text-rose-400': isPolling }" />
            <span>{{ isPolling ? 'Stop' : t('modbus_auto_poll') }}</span>
          </button>
        </div>

        <!-- Polling interval adjuster -->
        <div v-if="isPolling" class="flex items-center justify-between text-[11px] text-zinc-400 px-1">
          <span>{{ t("mb_poll_cycle") }}</span>
          <div class="flex items-center gap-1">
            <input
              v-model.number="pollIntervalMs"
              type="number"
              step="50"
              min="50"
              class="w-16 bg-zinc-900 border border-zinc-800 rounded px-1 text-center text-zinc-200"
            />
            <span>ms</span>
          </div>
        </div>
      </div>

      <!-- Format & Endianness Toolbar -->
      <div class="px-3 py-1.5 bg-zinc-950/90 border-b border-zinc-800 flex items-center justify-between shrink-0 gap-2">
        <!-- Display Format Selector -->
        <div class="flex items-center gap-1.5">
          <span class="text-[10px] text-zinc-400">{{ t("mb_resp_parse_label") }}</span>
          <select
            v-model="displayFormat"
            class="bg-zinc-900 border border-zinc-700 text-[10px] text-zinc-200 rounded px-1.5 py-0.5 outline-none"
          >
            <option value="uint16">{{ t("mb_fmt_uint16") }}</option>
            <option value="int16">{{ t("mb_fmt_int16") }}</option>
            <option value="uint32">{{ t("mb_fmt_uint32") }}</option>
            <option value="int32">{{ t("mb_fmt_int32") }}</option>
            <option value="float32">{{ t("mb_fmt_float32") }}</option>
            <option value="hex">{{ t("mb_fmt_hex") }}</option>
            <option value="binary">{{ t("mb_fmt_binary") }}</option>
            <option value="ascii">{{ t("mb_fmt_ascii") }}</option>
          </select>
        </div>

        <!-- 32-bit Byte Order Selector -->
        <div v-if="is32BitFormat" class="flex items-center gap-1">
          <span class="text-[10px] text-amber-400">{{ t("mb_order_label") }}</span>
          <select
            v-model="byteOrder"
            class="bg-zinc-900 border border-amber-800 text-[10px] text-amber-200 rounded px-1 py-0.5 outline-none"
          >
            <option value="AB_CD">{{ t("mb_order_abcd") }}</option>
            <option value="CD_AB">{{ t("mb_order_cdab") }}</option>
            <option value="BA_DC">{{ t("mb_order_badc") }}</option>
            <option value="DC_BA">{{ t("mb_order_dcba") }}</option>
          </select>
        </div>
      </div>

      <!-- Response Display Table -->
      <div class="flex-1 flex flex-col overflow-hidden p-3 min-h-0">
        <!-- Exception Banner -->
        <div
          v-if="parsedResult?.is_exception"
          class="bg-rose-950/70 border border-rose-800 rounded p-2.5 mb-2 flex items-start gap-2 text-rose-300 text-[11px] shrink-0"
        >
          <AlertTriangle class="w-4 h-4 shrink-0 text-rose-400 mt-0.5" />
          <div>
            <div class="font-bold">{{ t("mb_exception_banner") }}</div>
            <div class="text-[10px] text-rose-200 mt-0.5">{{ parsedResult.exception_desc }}</div>
          </div>
        </div>

        <!-- Coils View (Bit states) -->
        <div
          v-if="parsedResult && parsedResult.registers.length > 0 && parsedResult.registers[0].bool_val !== undefined"
          class="flex-1 border border-zinc-800 rounded overflow-auto bg-zinc-950 select-text p-2"
        >
          <div class="grid grid-cols-2 gap-2">
            <div
              v-for="reg in parsedResult.registers"
              :key="reg.address"
              @click="quickToggleCoil(reg.address, reg.bool_val ?? false)"
              class="border border-zinc-800 rounded p-2 flex items-center justify-between hover:bg-zinc-900/80 cursor-pointer transition-colors"
              :class="reg.bool_val ? 'bg-emerald-950/20 border-emerald-900/60' : 'bg-zinc-900/40'"
              :title="t('mb_quick_toggle_coil')"
            >
              <div>
                <div class="text-[10px] text-zinc-400 font-mono">0x{{ reg.address.toString(16).padStart(4, '0').toUpperCase() }} ({{ reg.address }})</div>
                <div class="font-bold text-xs" :class="reg.bool_val ? 'text-emerald-400' : 'text-zinc-500'">
                  {{ reg.bool_val ? 'ON (1)' : 'OFF (0)' }}
                </div>
              </div>
              <component
                :is="reg.bool_val ? ToggleRight : ToggleLeft"
                class="w-5 h-5 transition-transform"
                :class="reg.bool_val ? 'text-emerald-400' : 'text-zinc-600'"
              />
            </div>
          </div>
        </div>

        <!-- 32-bit Combined View -->
        <div
          v-else-if="parsedResult && parsedResult.registers.length > 0 && is32BitFormat"
          class="flex-1 border border-zinc-800 rounded overflow-auto bg-zinc-950 select-text"
        >
          <table class="w-full text-[11px] text-left">
            <thead class="bg-zinc-900 text-zinc-400 sticky top-0 border-b border-zinc-800">
              <tr>
                <th class="p-1.5 pl-2 font-normal">{{ t("mb_th_addr") }}</th>
                <th class="p-1.5 font-normal">HEX (4B)</th>
                <th class="p-1.5 font-normal">{{ t("mb_th_val") }} ({{ displayFormat.toUpperCase() }})</th>
              </tr>
            </thead>
            <tbody class="divide-y divide-zinc-900">
              <tr
                v-for="idx in Math.ceil(parsedResult.registers.length / 2)"
                :key="idx"
                class="hover:bg-zinc-900/60"
              >
                <td class="p-1.5 pl-2 text-zinc-400 font-mono">
                  {{ parsedResult.registers[(idx - 1) * 2]?.address }} ~ {{ (parsedResult.registers[(idx - 1) * 2]?.address ?? 0) + 1 }}
                </td>
                <td class="p-1.5 text-amber-300/90 font-mono text-[10px]">
                  {{ parsedResult.registers[(idx - 1) * 2]?.raw_hex }} {{ parsedResult.registers[(idx - 1) * 2 + 1]?.raw_hex || '00 00' }}
                </td>
                <td class="p-1.5 text-emerald-400 font-mono font-bold">
                  {{
                    parseModbus32Bit(
                      parsedResult.registers[(idx - 1) * 2]?.u16_val ?? 0,
                      parsedResult.registers[(idx - 1) * 2 + 1]?.u16_val ?? 0,
                      displayFormat as any,
                      byteOrder
                    )
                  }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 16-bit Regular Registers View (Inline Edit Supported) -->
        <div
          v-else-if="parsedResult && parsedResult.registers.length > 0"
          class="flex-1 border border-zinc-800 rounded overflow-auto bg-zinc-950 select-text"
        >
          <table class="w-full text-[11px] text-left">
            <thead class="bg-zinc-900 text-zinc-400 sticky top-0 border-b border-zinc-800">
              <tr>
                <th class="p-1.5 pl-2 font-normal">{{ t("mb_th_addr") }}</th>
                <th class="p-1.5 font-normal">HEX</th>
                <th class="p-1.5 font-normal">{{ t("mb_th_val") }} ({{ displayFormat.toUpperCase() }})</th>
                <th class="p-1.5 pr-2 w-8"></th>
              </tr>
            </thead>
            <tbody class="divide-y divide-zinc-900">
              <tr
                v-for="reg in parsedResult.registers"
                :key="reg.address"
                class="hover:bg-zinc-900/60 group"
              >
                <td class="p-1.5 pl-2 text-zinc-400 font-mono">
                  {{ reg.address }} <span class="text-zinc-600">(0x{{ reg.address.toString(16).padStart(4, '0').toUpperCase() }})</span>
                </td>
                <td class="p-1.5 text-amber-300/90 font-mono">{{ reg.raw_hex }}</td>

                <!-- Value Display / Inline Edit -->
                <td class="p-1.5 font-mono font-medium">
                  <div v-if="editingAddr === reg.address" class="flex items-center gap-1">
                    <input
                      v-model="editValInput"
                      @keydown.enter="confirmInlineEdit(reg.address)"
                      @keydown.esc="editingAddr = null"
                      type="text"
                      class="w-20 bg-zinc-900 border border-amber-500 rounded px-1 py-0.5 text-zinc-100 text-[10px] outline-none"
                      autofocus
                    />
                    <button
                      @click="confirmInlineEdit(reg.address)"
                      class="p-0.5 text-emerald-400 hover:bg-zinc-800 rounded"
                    >
                      <Check class="w-3 h-3" />
                    </button>
                  </div>
                  <div
                    v-else
                    @dblclick="startInlineEdit(reg.address, reg.u16_val)"
                    class="text-emerald-400 cursor-pointer hover:underline"
                    :title="t('mb_quick_write')"
                  >
                    {{ formatSingleRegister(reg.u16_val, displayFormat as any) }}
                  </div>
                </td>

                <td class="p-1.5 pr-2 text-right">
                  <button
                    @click="startInlineEdit(reg.address, reg.u16_val)"
                    class="opacity-0 group-hover:opacity-100 p-0.5 text-zinc-500 hover:text-amber-300 transition-opacity"
                    :title="t('mb_quick_write')"
                  >
                    <Edit2 class="w-3 h-3" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- Empty State -->
        <div
          v-else-if="!parsedResult?.is_exception"
          class="flex-1 flex flex-col items-center justify-center text-zinc-600 border border-dashed border-zinc-800 rounded p-4 text-center"
        >
          <Binary class="w-8 h-8 mb-2 opacity-30" />
          <p>{{ t("mb_empty_tip") }}</p>
          <p class="text-[10px] text-zinc-700 mt-1">{{ t("mb_empty_subtip") }}</p>
        </div>
      </div>
    </template>

    <!-- ==================== SLAVE SIMULATOR VIEW ==================== -->
    <template v-else>
      <div class="p-3 border-b border-zinc-800 space-y-2 bg-zinc-950/60 shrink-0">
        <div class="flex items-center justify-between">
          <div class="flex items-center gap-1.5 text-cyan-400 font-bold">
            <Cpu class="w-4 h-4" />
            <span>{{ t("mb_slave_title") }}</span>
          </div>
          <div class="flex items-center gap-1.5">
            <span class="text-[10px] text-zinc-400">{{ t("mb_slave_id_label") }}</span>
            <input
              v-model.number="slaveSimId"
              type="number"
              min="1"
              max="247"
              class="w-14 bg-zinc-900 border border-zinc-700 rounded px-1.5 py-0.5 text-center text-cyan-300 font-bold outline-none"
            />
          </div>
        </div>
        <p class="text-[10px] text-zinc-500">{{ t("mb_slave_tip") }}</p>

        <!-- Add Point Bar -->
        <div class="pt-1 flex items-center gap-1.5">
          <select
            v-model="slaveAreaType"
            class="bg-zinc-900 border border-zinc-700 text-[10px] text-zinc-200 rounded px-1 py-1 outline-none"
          >
            <option value="holding">{{ t("mb_slave_type_holding") }}</option>
            <option value="coils">{{ t("mb_slave_type_coils") }}</option>
          </select>
          <input
            v-model="slaveNewAddrInput"
            placeholder="Addr (e.g. 0)"
            class="w-20 bg-zinc-900 border border-zinc-700 rounded px-1.5 py-1 text-zinc-100 text-[10px] outline-none"
          />
          <input
            v-model="slaveNewValInput"
            placeholder="Val (e.g. 123)"
            class="flex-1 bg-zinc-900 border border-zinc-700 rounded px-1.5 py-1 text-zinc-100 text-[10px] outline-none"
          />
          <button
            @click="addSlavePoint"
            class="px-2 py-1 bg-cyan-700 hover:bg-cyan-600 text-white rounded font-medium text-[10px] flex items-center gap-0.5"
          >
            <Plus class="w-3 h-3" />
            <span>{{ t("mb_slave_add_reg") }}</span>
          </button>
        </div>
      </div>

      <!-- Slave Memory Tables -->
      <div class="flex-1 overflow-auto p-3 space-y-4">
        <!-- Holding Registers Area -->
        <div>
          <div class="text-[11px] font-bold text-amber-300 mb-1 flex items-center justify-between">
            <span>{{ t("mb_slave_type_holding") }}</span>
            <span class="text-[10px] text-zinc-500 font-normal">{{ Object.keys(slaveHoldingRegs).length }} points</span>
          </div>
          <div class="border border-zinc-800 rounded bg-zinc-950 overflow-hidden">
            <table class="w-full text-[11px] text-left">
              <thead class="bg-zinc-900 text-zinc-400 border-b border-zinc-800 text-[10px]">
                <tr>
                  <th class="p-1 pl-2 font-normal">Addr</th>
                  <th class="p-1 font-normal">HEX</th>
                  <th class="p-1 font-normal">Value (Dec)</th>
                  <th class="p-1 pr-2 w-6"></th>
                </tr>
              </thead>
              <tbody class="divide-y divide-zinc-900">
                <tr
                  v-for="(val, addrStr) in slaveHoldingRegs"
                  :key="addrStr"
                  class="hover:bg-zinc-900/40"
                >
                  <td class="p-1 pl-2 font-mono text-zinc-400">0x{{ Number(addrStr).toString(16).padStart(4, '0').toUpperCase() }} ({{ addrStr }})</td>
                  <td class="p-1 font-mono text-amber-300/80">0x{{ (val & 0xFFFF).toString(16).padStart(4, '0').toUpperCase() }}</td>
                  <td class="p-1 font-mono">
                    <input
                      v-model.number="slaveHoldingRegs[Number(addrStr)]"
                      type="number"
                      class="w-20 bg-zinc-900 border border-zinc-800 rounded px-1 py-0.5 text-emerald-400 text-[10px] outline-none"
                    />
                  </td>
                  <td class="p-1 pr-2 text-right">
                    <button
                      @click="removeSlavePoint('holding', Number(addrStr))"
                      class="text-zinc-600 hover:text-rose-400"
                    >
                      <Trash2 class="w-3 h-3" />
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- Coils Area -->
        <div>
          <div class="text-[11px] font-bold text-emerald-400 mb-1 flex items-center justify-between">
            <span>{{ t("mb_slave_type_coils") }}</span>
            <span class="text-[10px] text-zinc-500 font-normal">{{ Object.keys(slaveCoils).length }} points</span>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <div
              v-for="(val, addrStr) in slaveCoils"
              :key="addrStr"
              @click="slaveCoils[Number(addrStr)] = !slaveCoils[Number(addrStr)]"
              class="border border-zinc-800 rounded p-1.5 flex items-center justify-between bg-zinc-950 hover:bg-zinc-900/60 cursor-pointer"
            >
              <div>
                <span class="text-[10px] text-zinc-500 font-mono">0x{{ Number(addrStr).toString(16).padStart(4, '0').toUpperCase() }}</span>
                <span class="ml-1 font-bold text-[11px]" :class="val ? 'text-emerald-400' : 'text-zinc-600'">
                  {{ val ? 'ON' : 'OFF' }}
                </span>
              </div>
              <component :is="val ? ToggleRight : ToggleLeft" class="w-4 h-4" :class="val ? 'text-emerald-400' : 'text-zinc-600'" />
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- Bottom Traffic Log Panel (Collapsible) -->
    <div class="border-t border-zinc-800 bg-zinc-950 shrink-0">
      <div
        @click="isLogPanelOpen = !isLogPanelOpen"
        class="px-3 py-1.5 flex items-center justify-between text-[10px] text-zinc-400 hover:bg-zinc-900/80 cursor-pointer"
      >
        <div class="flex items-center gap-1.5">
          <span class="font-bold text-zinc-300">{{ t("mb_log_title") }}</span>
          <span class="bg-zinc-900 border border-zinc-800 px-1 rounded text-zinc-500">{{ trafficLogs.length }}</span>
        </div>
        <div class="flex items-center gap-2">
          <button
            v-if="trafficLogs.length > 0"
            @click.stop="clearLogs"
            class="text-zinc-500 hover:text-zinc-300 flex items-center gap-0.5"
            :title="t('mb_clear_log')"
          >
            <Trash2 class="w-2.5 h-2.5" />
            <span>{{ t("mb_clear_log") }}</span>
          </button>
          <component :is="isLogPanelOpen ? ChevronDown : ChevronUp" class="w-3.5 h-3.5 text-zinc-500" />
        </div>
      </div>

      <!-- Traffic Log Content -->
      <div
        v-if="isLogPanelOpen"
        class="h-32 overflow-auto p-2 border-t border-zinc-800 text-[10px] space-y-1 select-text"
      >
        <div
          v-for="log in trafficLogs"
          :key="log.id"
          class="flex items-start gap-1.5 leading-tight font-mono"
        >
          <span class="text-zinc-600 shrink-0">{{ log.time }}</span>
          <span
            class="px-1 rounded shrink-0 font-bold"
            :class="log.dir === 'tx' ? 'bg-amber-950 text-amber-300' : log.isError ? 'bg-rose-950 text-rose-300' : 'bg-emerald-950 text-emerald-300'"
          >
            {{ log.dir.toUpperCase() }}
          </span>
          <span class="text-zinc-300 shrink-0">{{ log.desc }}</span>
          <span class="text-zinc-500 break-all">[{{ log.rawHex }}]</span>
        </div>
        <div v-if="trafficLogs.length === 0" class="text-center text-zinc-700 py-3">
          暂无报文交互
        </div>
      </div>
    </div>
  </div>
</template>
