<script setup lang="ts">
import { ref, computed, watch } from 'vue';
import {
  type BitWidth,
  maskValue,
  toHexString,
  toBinString,
  toOctString,
  toDecString,
  toSignedDecString,
  parseInputToBigInt,
  toggleBit,
  testBit,
  countSetBits,
  countLeadingZeros,
  countTrailingZeros,
  shiftLeft,
  shiftRightLogical,
  shiftRightArithmetic,
  rotateLeft,
  rotateRight,
  swapEndian,
  getBytes,
  toFloat32,
  toAsciiString,
  calcCrc16Modbus,
  calcCrc16Ccitt,
  calcCrc32,
  calcChecksum8,
  calcXor8
} from '../utils/radixEngine';
import {
  Calculator,
  Copy,
  Check,
  Binary,
  Layers,
  ShieldCheck,
  History,
  Sliders
} from '@lucide/vue';

// --- Core State (ValueReg) ---
const currentWidth = ref<BitWidth>(32);
const rawValue = ref<bigint>(0n);
const isSigned = ref<boolean>(false);
const overflowMessage = ref<string>('');

// Input Text Models (Sync inputs)
const hexInput = ref<string>('0');
const decInput = ref<string>('0');
const octInput = ref<string>('0');
const binInput = ref<string>('0000 0000 0000 0000 0000 0000 0000 0000');

// Shift / Op Inputs
const shiftAmount = ref<number>(1);
const operandB = ref<string>('0xFF');

// History Stack
interface HistoryItem {
  id: number;
  time: string;
  action: string;
  hex: string;
  dec: string;
  val: bigint;
}
const history = ref<HistoryItem[]>([]);
let nextHistoryId = 1;

// Copied feedback
const copySuccessKey = ref<string>('');

// Sync inputs from rawValue
function syncInputsFromValue(val: bigint) {
  const masked = maskValue(val, currentWidth.value);
  rawValue.value = masked;
  hexInput.value = toHexString(masked, currentWidth.value);
  decInput.value = isSigned.value ? toSignedDecString(masked, currentWidth.value) : toDecString(masked, currentWidth.value);
  octInput.value = toOctString(masked, currentWidth.value);
  binInput.value = toBinString(masked, currentWidth.value, true);
}

// User edits Hex
function handleHexInput() {
  const parsed = parseInputToBigInt(hexInput.value, 16);
  if (parsed !== null) {
    recordHistory('编辑 HEX', parsed);
  }
}

// User edits Dec
function handleDecInput() {
  const parsed = parseInputToBigInt(decInput.value, 10);
  if (parsed !== null) {
    recordHistory('编辑 DEC', parsed);
  }
}

// User edits Oct
function handleOctInput() {
  const parsed = parseInputToBigInt(octInput.value, 8);
  if (parsed !== null) {
    recordHistory('编辑 OCT', parsed);
  }
}

// User edits Bin
function handleBinInput() {
  const parsed = parseInputToBigInt(binInput.value, 2);
  if (parsed !== null) {
    recordHistory('编辑 BIN', parsed);
  }
}

function recordHistory(action: string, newVal: bigint) {
  const masked = maskValue(newVal, currentWidth.value);
  if (newVal > maskValue(newVal, currentWidth.value)) {
    overflowMessage.value = `数值超出 ${currentWidth.value} 位范围，已截断高位`;
    setTimeout(() => overflowMessage.value = '', 3500);
  }
  syncInputsFromValue(masked);
  const time = new Date().toLocaleTimeString();
  history.value.unshift({
    id: nextHistoryId++,
    time,
    action,
    hex: '0x' + toHexString(masked, currentWidth.value),
    dec: toDecString(masked, currentWidth.value),
    val: masked
  });
  if (history.value.length > 50) history.value.pop();
}

function restoreHistory(item: HistoryItem) {
  recordHistory(`恢复历史 (${item.hex})`, item.val);
}

function clearHistory() {
  history.value = [];
}

// Width Change
function setWidth(w: BitWidth) {
  currentWidth.value = w;
  recordHistory(`切换宽度为 ${w} 位`, BigInt(rawValue.value));
}

// Bit manipulation
function handleBitClick(bitIndex: number) {
  const next = toggleBit(BigInt(rawValue.value), bitIndex, currentWidth.value);
  recordHistory(`翻转 Bit ${bitIndex}`, next);
}

function setAllBits() {
  recordHistory('全部置 1', maskValue(~0n, currentWidth.value));
}

function clearAllBits() {
  recordHistory('全部清 0', 0n);
}

function invertAllBits() {
  recordHistory('按位取反 (~)', maskValue(~BigInt(rawValue.value), currentWidth.value));
}

// Shifts
function doShiftLeft() {
  const next = shiftLeft(BigInt(rawValue.value), shiftAmount.value, currentWidth.value);
  recordHistory(`左移 << ${shiftAmount.value}`, next);
}

function doShiftRightLogical() {
  const next = shiftRightLogical(BigInt(rawValue.value), shiftAmount.value, currentWidth.value);
  recordHistory(`逻辑右移 >> ${shiftAmount.value}`, next);
}

function doShiftRightArithmetic() {
  const next = shiftRightArithmetic(BigInt(rawValue.value), shiftAmount.value, currentWidth.value);
  recordHistory(`算术右移 >>> ${shiftAmount.value}`, next);
}

function doRotateLeft() {
  const next = rotateLeft(BigInt(rawValue.value), shiftAmount.value, currentWidth.value);
  recordHistory(`循环左移 ROL ${shiftAmount.value}`, next);
}

function doRotateRight() {
  const next = rotateRight(BigInt(rawValue.value), shiftAmount.value, currentWidth.value);
  recordHistory(`循环右移 ROR ${shiftAmount.value}`, next);
}

// Binary operations with Operand B
function parseOperandB(): bigint {
  const parsed = parseInputToBigInt(operandB.value, 16) ?? parseInputToBigInt(operandB.value, 10);
  return parsed ?? 0n;
}

function doBitwiseAnd() {
  const b = parseOperandB();
  recordHistory(`AND (0x${b.toString(16).toUpperCase()})`, maskValue(BigInt(rawValue.value) & b, currentWidth.value));
}

function doBitwiseOr() {
  const b = parseOperandB();
  recordHistory(`OR (0x${b.toString(16).toUpperCase()})`, maskValue(BigInt(rawValue.value) | b, currentWidth.value));
}

function doBitwiseXor() {
  const b = parseOperandB();
  recordHistory(`XOR (0x${b.toString(16).toUpperCase()})`, maskValue(BigInt(rawValue.value) ^ b, currentWidth.value));
}

// Endianness Swap
function doSwapEndian() {
  const next = swapEndian(BigInt(rawValue.value), currentWidth.value);
  recordHistory('大端/小端 字节反转', next);
}

// Copy to clipboard
function copyText(key: string, text: string) {
  navigator.clipboard.writeText(text);
  copySuccessKey.value = key;
  setTimeout(() => {
    if (copySuccessKey.value === key) copySuccessKey.value = '';
  }, 1500);
}

// Interpretations & Statistics
const bitStats = computed(() => {
  const val = BigInt(rawValue.value);
  return {
    popcount: countSetBits(val, currentWidth.value),
    clz: countLeadingZeros(val, currentWidth.value),
    ctz: countTrailingZeros(val, currentWidth.value),
  };
});

const bytesListBig = computed(() => getBytes(BigInt(rawValue.value), currentWidth.value, false));
const bytesListLittle = computed(() => getBytes(BigInt(rawValue.value), currentWidth.value, true));
const floatInterpretation = computed(() => toFloat32(BigInt(rawValue.value)));
const asciiInterpretation = computed(() => toAsciiString(BigInt(rawValue.value), currentWidth.value));

// CRC / Checksum computations
const crcResults = computed(() => {
  const bytes = new Uint8Array(bytesListBig.value);
  return {
    crc16Modbus: '0x' + calcCrc16Modbus(bytes).toString(16).toUpperCase().padStart(4, '0'),
    crc16Ccitt: '0x' + calcCrc16Ccitt(bytes).toString(16).toUpperCase().padStart(4, '0'),
    crc32: '0x' + calcCrc32(bytes).toString(16).toUpperCase().padStart(8, '0'),
    sum8: '0x' + calcChecksum8(bytes).toString(16).toUpperCase().padStart(2, '0'),
    xor8: '0x' + calcXor8(bytes).toString(16).toUpperCase().padStart(2, '0')
  };
});

// Watch sign mode
watch(isSigned, () => {
  decInput.value = isSigned.value
    ? toSignedDecString(BigInt(rawValue.value), currentWidth.value)
    : toDecString(BigInt(rawValue.value), currentWidth.value);
});

// Initialize with default 0
syncInputsFromValue(0n);
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-sans select-none overflow-hidden">
    <!-- Top Toolbar Header -->
    <div class="bg-zinc-900 border-b border-zinc-800 p-3 flex items-center justify-between shrink-0">
      <div class="flex items-center gap-2.5">
        <div class="p-1.5 rounded bg-emerald-950/60 border border-emerald-800/40 text-emerald-400">
          <Calculator class="w-4 h-4" />
        </div>
        <div>
          <span class="font-bold text-xs text-zinc-100">Radix Lab 进制计算器与位运算工作台</span>
          <p class="text-[10.5px] text-zinc-400">
            全息多进制同步编辑、可视比特矩阵(Bit Matrix)、大/小端字节序与嵌入式校验。
          </p>
        </div>
      </div>

      <!-- Width & Signed Selection -->
      <div class="flex items-center gap-3">
        <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded p-0.5 text-xs">
          <button
            v-for="w in [8, 16, 32, 64] as BitWidth[]"
            :key="w"
            @click="setWidth(w)"
            class="px-2.5 py-1 rounded transition-colors font-mono font-bold"
            :class="currentWidth === w ? 'bg-emerald-600 text-zinc-950 shadow-xs' : 'text-zinc-400 hover:text-zinc-200'"
          >
            {{ w }} 位
          </button>
        </div>

        <label class="flex items-center gap-1.5 text-xs cursor-pointer text-zinc-300">
          <input
            type="checkbox"
            v-model="isSigned"
            class="rounded bg-zinc-950 border-zinc-700 text-emerald-500 focus:ring-0 cursor-pointer"
          />
          <span :class="isSigned ? 'text-emerald-400 font-semibold' : 'text-zinc-400'">补码有符号</span>
        </label>
      </div>
    </div>

    <!-- Overflow alert banner if any -->
    <div v-if="overflowMessage" class="bg-amber-950/90 border-b border-amber-800 text-amber-300 px-4 py-1.5 text-xs flex items-center gap-2">
      <span>⚠️ {{ overflowMessage }}</span>
    </div>

    <!-- Main Workspace Content -->
    <div class="flex-1 flex overflow-hidden">
      <!-- Left Column: Synchronized Radix Inputs & Bit Matrix -->
      <div class="flex-1 flex flex-col p-4 space-y-4 overflow-y-auto border-r border-zinc-800/80">
        <!-- 1. Radix Inputs Cards (HEX, DEC, OCT, BIN) -->
        <div class="bg-zinc-900/60 border border-zinc-800/80 rounded-xl p-4 space-y-3">
          <div class="text-[11px] font-bold text-zinc-400 uppercase tracking-wider flex items-center justify-between">
            <span>多进制同步编辑 (就地实时双向联动)</span>
            <span class="text-zinc-500 font-mono">ValueReg ({{ currentWidth }}bit)</span>
          </div>

          <!-- HEX Input -->
          <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded-lg p-2 focus-within:border-emerald-500 transition-colors">
            <span class="w-12 text-zinc-500 font-bold font-mono text-xs pl-1">HEX</span>
            <span class="text-emerald-400 font-mono text-xs mr-2 font-semibold">0x</span>
            <input
              v-model="hexInput"
              @input="handleHexInput"
              class="flex-1 bg-transparent text-emerald-400 font-mono font-bold text-sm outline-none"
              placeholder="0"
            />
            <button
              @click="copyText('hex', '0x' + hexInput)"
              class="p-1 hover:bg-zinc-800 rounded text-zinc-400 hover:text-zinc-200"
              title="复制十六进制"
            >
              <component :is="copySuccessKey === 'hex' ? Check : Copy" class="w-3.5 h-3.5" :class="copySuccessKey === 'hex' ? 'text-emerald-400' : ''" />
            </button>
          </div>

          <!-- DEC Input -->
          <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded-lg p-2 focus-within:border-cyan-500 transition-colors">
            <span class="w-12 text-zinc-500 font-bold font-mono text-xs pl-1">DEC</span>
            <span class="text-cyan-400 font-mono text-xs mr-2 font-semibold">{{ isSigned ? '±' : '+' }}</span>
            <input
              v-model="decInput"
              @input="handleDecInput"
              class="flex-1 bg-transparent text-cyan-300 font-mono font-bold text-sm outline-none"
              placeholder="0"
            />
            <button
              @click="copyText('dec', decInput)"
              class="p-1 hover:bg-zinc-800 rounded text-zinc-400 hover:text-zinc-200"
              title="复制十进制"
            >
              <component :is="copySuccessKey === 'dec' ? Check : Copy" class="w-3.5 h-3.5" :class="copySuccessKey === 'dec' ? 'text-emerald-400' : ''" />
            </button>
          </div>

          <!-- OCT Input -->
          <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded-lg p-2 focus-within:border-indigo-500 transition-colors">
            <span class="w-12 text-zinc-500 font-bold font-mono text-xs pl-1">OCT</span>
            <span class="text-indigo-400 font-mono text-xs mr-2 font-semibold">0o</span>
            <input
              v-model="octInput"
              @input="handleOctInput"
              class="flex-1 bg-transparent text-indigo-300 font-mono font-bold text-sm outline-none"
              placeholder="0"
            />
            <button
              @click="copyText('oct', '0o' + octInput)"
              class="p-1 hover:bg-zinc-800 rounded text-zinc-400 hover:text-zinc-200"
              title="复制八进制"
            >
              <component :is="copySuccessKey === 'oct' ? Check : Copy" class="w-3.5 h-3.5" :class="copySuccessKey === 'oct' ? 'text-emerald-400' : ''" />
            </button>
          </div>

          <!-- BIN Input -->
          <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded-lg p-2 focus-within:border-amber-500 transition-colors">
            <span class="w-12 text-zinc-500 font-bold font-mono text-xs pl-1">BIN</span>
            <span class="text-amber-400 font-mono text-xs mr-2 font-semibold">0b</span>
            <input
              v-model="binInput"
              @input="handleBinInput"
              class="flex-1 bg-transparent text-amber-300 font-mono font-bold text-xs outline-none tracking-widest"
              placeholder="0"
            />
            <button
              @click="copyText('bin', '0b' + binInput.replace(/\s+/g, ''))"
              class="p-1 hover:bg-zinc-800 rounded text-zinc-400 hover:text-zinc-200"
              title="复制二进制"
            >
              <component :is="copySuccessKey === 'bin' ? Check : Copy" class="w-3.5 h-3.5" :class="copySuccessKey === 'bin' ? 'text-emerald-400' : ''" />
            </button>
          </div>
        </div>

        <!-- 2. Interactive Bit Matrix (可交互比特矩阵) -->
        <div class="bg-zinc-900/60 border border-zinc-800/80 rounded-xl p-4 space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <Binary class="w-4 h-4 text-emerald-400" />
              <span class="text-xs font-bold text-zinc-200">交互式比特矩阵 (点击任意 Bit 直接置位/清零)</span>
            </div>
            <!-- Quick Actions -->
            <div class="flex items-center gap-1.5 text-[11px]">
              <button
                @click="setAllBits"
                class="px-2 py-0.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded border border-zinc-700"
              >
                全置 1
              </button>
              <button
                @click="clearAllBits"
                class="px-2 py-0.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded border border-zinc-700"
              >
                全清 0
              </button>
              <button
                @click="invertAllBits"
                class="px-2 py-0.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded border border-zinc-700"
              >
                取反 (NOT)
              </button>
            </div>
          </div>

          <!-- Bit Grid (Rendered from MSB to LSB, grouped in 8-bit rows) -->
          <div class="space-y-2.5 font-mono select-none">
            <div
              v-for="rowStart in Array.from({ length: currentWidth / 8 }, (_, i) => currentWidth - 1 - i * 8)"
              :key="rowStart"
              class="flex items-center justify-between bg-zinc-950/70 p-2 rounded-lg border border-zinc-800/60"
            >
              <div class="text-[10px] text-zinc-500 w-12 font-bold shrink-0">
                [{{ rowStart }}:{{ rowStart - 7 }}]
              </div>

              <!-- 8 Bits in row -->
              <div class="flex-1 flex items-center justify-end gap-1.5">
                <template v-for="bIdx in Array.from({ length: 8 }, (_, k) => rowStart - k)" :key="bIdx">
                  <!-- Nibble separator gap -->
                  <div v-if="bIdx % 4 === 3 && bIdx !== rowStart" class="w-1.5"></div>

                  <div
                    @click="handleBitClick(bIdx)"
                    class="flex flex-col items-center cursor-pointer group"
                    :title="`Bit ${bIdx} (权重: 0x${(1n << BigInt(bIdx)).toString(16).toUpperCase()})`"
                  >
                    <span class="text-[9px] text-zinc-600 group-hover:text-zinc-400 mb-0.5 font-mono leading-none">
                      {{ bIdx }}
                    </span>
                    <button
                      class="w-6 h-7 rounded flex items-center justify-center font-bold text-xs transition-all border"
                      :class="testBit(BigInt(rawValue), bIdx)
                        ? 'bg-emerald-500 text-zinc-950 border-emerald-400 shadow-sm shadow-emerald-500/20'
                        : 'bg-zinc-900 text-zinc-400 border-zinc-800 hover:border-zinc-700 hover:bg-zinc-800'"
                    >
                      {{ testBit(BigInt(rawValue), bIdx) ? '1' : '0' }}
                    </button>
                  </div>
                </template>
              </div>
            </div>
          </div>

          <!-- Bit Statistics Bar -->
          <div class="flex items-center justify-between text-xs pt-1 border-t border-zinc-800/60 text-zinc-400">
            <div class="flex items-center gap-4">
              <span>置位数 (Popcount): <strong class="text-emerald-400 font-mono">{{ bitStats.popcount }}</strong></span>
              <span>前导零 (CLZ): <strong class="text-cyan-400 font-mono">{{ bitStats.clz }}</strong></span>
              <span>末尾零 (CTZ): <strong class="text-amber-400 font-mono">{{ bitStats.ctz }}</strong></span>
            </div>
            <div class="text-[11px] text-zinc-500 font-mono">
              Bit 0 是最低位 (LSB)
            </div>
          </div>
        </div>
      </div>

      <!-- Right Column: Operations, Shifts, Endianness & CRC Tools -->
      <div class="w-96 flex flex-col p-4 space-y-4 overflow-y-auto bg-zinc-900/40 shrink-0 text-xs">
        <!-- 1. Shifts and Bitwise Ops -->
        <div class="bg-zinc-900/90 border border-zinc-800 rounded-xl p-3.5 space-y-3">
          <div class="flex items-center justify-between">
            <span class="font-bold text-zinc-200 flex items-center gap-1.5">
              <Sliders class="w-3.5 h-3.5 text-cyan-400" />
              移位与逻辑运算
            </span>
            <div class="flex items-center gap-1 font-mono">
              <span class="text-zinc-500 text-[11px]">移位量:</span>
              <input
                type="number"
                v-model.number="shiftAmount"
                min="1"
                :max="currentWidth - 1"
                class="w-10 bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5 text-center text-cyan-400 font-bold outline-none"
              />
            </div>
          </div>

          <!-- Shift Buttons Grid -->
          <div class="grid grid-cols-2 gap-2 font-mono">
            <button
              @click="doShiftLeft"
              class="py-1.5 px-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded border border-zinc-700 transition-colors flex items-center justify-center gap-1"
            >
              <span>&lt;&lt; 逻辑左移</span>
            </button>
            <button
              @click="doShiftRightLogical"
              class="py-1.5 px-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded border border-zinc-700 transition-colors flex items-center justify-center gap-1"
            >
              <span>&gt;&gt; 逻辑右移</span>
            </button>
            <button
              @click="doShiftRightArithmetic"
              class="py-1.5 px-2 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded border border-zinc-700 transition-colors flex items-center justify-center gap-1"
            >
              <span>&gt;&gt;&gt; 算术右移</span>
            </button>
            <button
              @click="doSwapEndian"
              class="py-1.5 px-2 bg-emerald-950/70 hover:bg-emerald-900/80 text-emerald-300 rounded border border-emerald-800/80 transition-colors flex items-center justify-center gap-1 font-semibold"
            >
              <span>SWAP 端序反转</span>
            </button>
            <button
              @click="doRotateLeft"
              class="py-1 px-2 bg-zinc-950 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 rounded border border-zinc-800 transition-colors"
            >
              ROL 循环左移
            </button>
            <button
              @click="doRotateRight"
              class="py-1 px-2 bg-zinc-950 hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 rounded border border-zinc-800 transition-colors"
            >
              ROR 循环右移
            </button>
          </div>

          <!-- Binary Logic Operations with Operand B -->
          <div class="pt-2 border-t border-zinc-800/60 space-y-2">
            <div class="flex items-center gap-2">
              <span class="text-zinc-400 text-[11px] shrink-0">操作数 B:</span>
              <input
                v-model="operandB"
                placeholder="0xFF"
                class="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 font-mono outline-none focus:border-cyan-500"
              />
            </div>
            <div class="grid grid-cols-3 gap-2">
              <button
                @click="doBitwiseAnd"
                class="py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded font-bold border border-zinc-700 transition-colors font-mono"
              >
                AND (&amp;)
              </button>
              <button
                @click="doBitwiseOr"
                class="py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded font-bold border border-zinc-700 transition-colors font-mono"
              >
                OR (|)
              </button>
              <button
                @click="doBitwiseXor"
                class="py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 rounded font-bold border border-zinc-700 transition-colors font-mono"
              >
                XOR (^)
              </button>
            </div>
          </div>
        </div>

        <!-- 2. Endianness & Memory Interpretation (端序与内存解释) -->
        <div class="bg-zinc-900/90 border border-zinc-800 rounded-xl p-3.5 space-y-2.5">
          <span class="font-bold text-zinc-200 flex items-center gap-1.5">
            <Layers class="w-3.5 h-3.5 text-indigo-400" />
            端序与多视角数值解释
          </span>

          <div class="space-y-1.5 text-[11px] font-mono">
            <div class="flex items-center justify-between p-1.5 bg-zinc-950 rounded border border-zinc-800">
              <span class="text-zinc-500">大端字节 (Big Endian):</span>
              <span class="text-indigo-300 font-bold">
                {{ bytesListBig.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ') }}
              </span>
            </div>
            <div class="flex items-center justify-between p-1.5 bg-zinc-950 rounded border border-zinc-800">
              <span class="text-zinc-500">小端字节 (Little Endian):</span>
              <span class="text-cyan-300 font-bold">
                {{ bytesListLittle.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ') }}
              </span>
            </div>
            <div class="flex items-center justify-between p-1.5 bg-zinc-950 rounded border border-zinc-800">
              <span class="text-zinc-500">IEEE 754 Float32:</span>
              <span class="text-amber-300">{{ floatInterpretation.toPrecision(6) }}</span>
            </div>
            <div class="flex items-center justify-between p-1.5 bg-zinc-950 rounded border border-zinc-800">
              <span class="text-zinc-500">ASCII 字符:</span>
              <span class="text-emerald-300 font-bold tracking-widest">'{{ asciiInterpretation }}'</span>
            </div>
          </div>
        </div>

        <!-- 3. Embedded Checksums (CRC & 校验和) -->
        <div class="bg-zinc-900/90 border border-zinc-800 rounded-xl p-3.5 space-y-2.5">
          <span class="font-bold text-zinc-200 flex items-center gap-1.5">
            <ShieldCheck class="w-3.5 h-3.5 text-emerald-400" />
            嵌入式快速校验 (针对当前字节流)
          </span>

          <div class="grid grid-cols-2 gap-2 text-[11px] font-mono">
            <div class="p-1.5 bg-zinc-950 rounded border border-zinc-800">
              <div class="text-[10px] text-zinc-500">CRC-16 Modbus</div>
              <div class="text-emerald-400 font-bold mt-0.5">{{ crcResults.crc16Modbus }}</div>
            </div>
            <div class="p-1.5 bg-zinc-950 rounded border border-zinc-800">
              <div class="text-[10px] text-zinc-500">CRC-16 CCITT</div>
              <div class="text-cyan-400 font-bold mt-0.5">{{ crcResults.crc16Ccitt }}</div>
            </div>
            <div class="p-1.5 bg-zinc-950 rounded border border-zinc-800">
              <div class="text-[10px] text-zinc-500">CRC-32</div>
              <div class="text-indigo-400 font-bold mt-0.5">{{ crcResults.crc32 }}</div>
            </div>
            <div class="p-1.5 bg-zinc-950 rounded border border-zinc-800">
              <div class="text-[10px] text-zinc-500">Sum8 / XOR8</div>
              <div class="text-amber-400 font-bold mt-0.5">{{ crcResults.sum8 }} / {{ crcResults.xor8 }}</div>
            </div>
          </div>
        </div>

        <!-- 4. History Log (计算与修改历史) -->
        <div class="bg-zinc-900/90 border border-zinc-800 rounded-xl p-3.5 space-y-2 flex-1 flex flex-col min-h-[160px]">
          <div class="flex items-center justify-between">
            <span class="font-bold text-zinc-200 flex items-center gap-1.5">
              <History class="w-3.5 h-3.5 text-zinc-400" />
              历史记录 (点击快速回填)
            </span>
            <button
              v-if="history.length > 0"
              @click="clearHistory"
              class="text-zinc-500 hover:text-zinc-300 text-[10px]"
            >
              清空
            </button>
          </div>

          <div class="flex-1 overflow-y-auto space-y-1.5 font-mono text-[11px] max-h-48 pr-1">
            <div
              v-for="item in history"
              :key="item.id"
              @click="restoreHistory(item)"
              class="p-1.5 rounded bg-zinc-950 hover:bg-zinc-800 border border-zinc-800/80 cursor-pointer flex items-center justify-between transition-colors"
            >
              <div>
                <span class="text-emerald-400 font-bold mr-1.5">{{ item.hex }}</span>
                <span class="text-zinc-400">({{ item.dec }})</span>
              </div>
              <span class="text-[9.5px] text-zinc-500">{{ item.action }}</span>
            </div>
            <div v-if="history.length === 0" class="text-zinc-600 text-center py-4 text-xs font-sans">
              暂无计算历史
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
