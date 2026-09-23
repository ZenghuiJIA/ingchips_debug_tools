<script setup lang="ts">
import { ref, watch } from 'vue';
import {
  Sliders,
  Plus,
  Trash2,
  X,
  Send,
  Zap,
  ToggleLeft,
  ToggleRight
} from '@lucide/vue';
import { safeInvoke } from '../utils/ipc';
import { appendChecksum, type ChecksumAlgorithm } from '../utils/crc';

export interface ProtocolField {
  id: string;
  name: string;
  type: 'uint8' | 'uint16' | 'int16' | 'bool';
  widget: 'slider' | 'switch' | 'number' | 'fixed';
  min: number;
  max: number;
  step: number;
  value: number; // Current value
}

const props = defineProps<{
  portName: string;
  isConnected: boolean;
}>();

const emit = defineEmits<{
  (e: 'close'): void;
  (e: 'log', text: string, type: 'rx' | 'tx' | 'info' | 'error'): void;
  (e: 'bytes-sent', count: number): void;
}>();

const STORAGE_KEY = 'ai_hil_protocol_dashboard_v1';

// Frame header and checksum settings
const headerHex = ref<string>('AA 55');
const autoSendOnChange = ref<boolean>(true);
const checksumType = ref<ChecksumAlgorithm>('modbus_crc16');

// Fields list
const fields = ref<ProtocolField[]>([
  { id: 'f_cmd', name: '命令字 (Cmd)', type: 'uint8', widget: 'fixed', min: 0, max: 255, step: 1, value: 0x01 },
  { id: 'f_pwm', name: '电机 PWM 占空比', type: 'uint16', widget: 'slider', min: 0, max: 1000, step: 10, value: 350 },
  { id: 'f_led', name: '板载 LED 开关', type: 'bool', widget: 'switch', min: 0, max: 1, step: 1, value: 1 },
  { id: 'f_target', name: '设定目标转速', type: 'int16', widget: 'number', min: -5000, max: 5000, step: 50, value: 1200 },
]);

// Load from local storage
try {
  const cached = localStorage.getItem(STORAGE_KEY);
  if (cached) {
    const data = JSON.parse(cached);
    if (data.fields && Array.isArray(data.fields)) fields.value = data.fields;
    if (data.headerHex) headerHex.value = data.headerHex;
    if (data.checksumType) checksumType.value = data.checksumType;
  }
} catch (e) {
  // Ignore corrupted cache
}

// Watch and save
watch([fields, headerHex, checksumType], () => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    fields: fields.value,
    headerHex: headerHex.value,
    checksumType: checksumType.value
  }));
}, { deep: true });

/**
 * Builds the raw byte stream from current field values
 */
function buildRawPayload(): number[] {
  const bytes: number[] = [];

  // 1. Parse header
  const cleanHeader = headerHex.value.replace(/[^0-9a-fA-F]/g, '');
  for (let i = 0; i < cleanHeader.length; i += 2) {
    bytes.push(parseInt(cleanHeader.substring(i, i + 2), 16));
  }

  // 2. Encode each field
  for (const f of fields.value) {
    const v = Math.round(f.value);
    if (f.type === 'uint8' || f.type === 'bool') {
      bytes.push(v & 0xFF);
    } else if (f.type === 'uint16' || f.type === 'int16') {
      // Big Endian standard
      bytes.push((v >> 8) & 0xFF);
      bytes.push(v & 0xFF);
    }
  }

  return bytes;
}

const currentPreviewHex = ref<string>('');

async function updatePreview() {
  const raw = buildRawPayload();
  const full = await appendChecksum(raw, checksumType.value);
  currentPreviewHex.value = full.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');
}

watch([fields, headerHex, checksumType], () => {
  updatePreview();
}, { deep: true, immediate: true });

async function sendFrame() {
  if (!props.isConnected) {
    emit('log', '串口未连接，无法发送操控指令', 'error');
    return;
  }

  try {
    const raw = buildRawPayload();
    const finalBytes = await appendChecksum(raw, checksumType.value);
    const count: number = await safeInvoke('send_serial_data', {
      data: finalBytes,
      portName: props.portName
    });
    emit('bytes-sent', count);

    const hexStr = finalBytes.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');
    emit('log', `[操控下发] -> ${hexStr}`, 'tx');
  } catch (err: any) {
    emit('log', `操控发送失败: ${err}`, 'error');
  }
}

function onWidgetChanged() {
  updatePreview();
  if (autoSendOnChange.value && props.isConnected) {
    sendFrame();
  }
}

function addField() {
  fields.value.push({
    id: 'f_' + Date.now(),
    name: '新建控制量',
    type: 'uint16',
    widget: 'slider',
    min: 0,
    max: 100,
    step: 1,
    value: 50
  });
}

function removeField(idx: number) {
  fields.value.splice(idx, 1);
}
</script>

<template>
  <div class="w-96 h-full bg-zinc-900 border-l border-zinc-800 flex flex-col font-mono text-xs select-none">
    <!-- Header -->
    <div class="px-3 py-2 border-b border-zinc-800 flex items-center justify-between bg-zinc-900/90">
      <div class="flex items-center gap-1.5 font-semibold text-emerald-400">
        <Sliders class="w-4 h-4 text-emerald-400" />
        <span>自定义交互操控台 (Dashboard)</span>
      </div>
      <button
        @click="emit('close')"
        class="p-1 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 rounded transition-colors"
      >
        <X class="w-4 h-4" />
      </button>
    </div>

    <!-- Top Protocol Settings -->
    <div class="p-3 border-b border-zinc-800 bg-zinc-950/40 space-y-2">
      <div class="grid grid-cols-2 gap-2">
        <div>
          <label class="block text-[10px] text-zinc-400 mb-0.5">帧头 (Hex):</label>
          <input
            v-model="headerHex"
            type="text"
            placeholder="如 AA 55"
            class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-2 py-1 text-zinc-100 focus:border-emerald-500 outline-none uppercase font-mono"
          />
        </div>
        <div>
          <label class="block text-[10px] text-zinc-400 mb-0.5">校验算法:</label>
          <select
            v-model="checksumType"
            class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-1.5 py-1 text-zinc-200 focus:border-emerald-500 outline-none text-[11px]"
          >
            <option value="none">无校验</option>
            <option value="modbus_crc16">Modbus CRC16</option>
            <option value="crc16_ccitt">CRC16-CCITT</option>
            <option value="checksum8">Checksum-8</option>
            <option value="xor8">XOR-8</option>
          </select>
        </div>
      </div>

      <!-- Realtime Auto-Send Checkbox -->
      <div class="flex items-center justify-between pt-1">
        <label class="flex items-center gap-1.5 text-[11px] text-zinc-300 cursor-pointer">
          <input
            type="checkbox"
            v-model="autoSendOnChange"
            class="rounded bg-zinc-800 border-zinc-700 text-emerald-500 focus:ring-0"
          />
          <Zap class="w-3.5 h-3.5 text-amber-400" />
          <span>滑动/操作时即时发包</span>
        </label>

        <button
          @click="sendFrame"
          :disabled="!isConnected"
          class="flex items-center gap-1 px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded font-medium transition-colors disabled:opacity-40"
        >
          <Send class="w-3 h-3" />
          <span>手动发送</span>
        </button>
      </div>

      <!-- Hex Preview -->
      <div class="bg-zinc-950 border border-zinc-800 rounded p-1.5 text-[10px] flex items-center justify-between">
        <span class="text-zinc-500 shrink-0">实时组帧:</span>
        <span class="text-emerald-400 font-bold truncate ml-2 font-mono">{{ currentPreviewHex || '--' }}</span>
      </div>
    </div>

    <!-- Fields Interactive Controls Viewport -->
    <div class="flex-1 overflow-auto p-3 space-y-3 min-h-0">
      <div class="flex items-center justify-between">
        <span class="text-[11px] font-semibold text-zinc-300">数据字段与控制元件:</span>
        <button
          @click="addField"
          class="flex items-center gap-1 text-[10.5px] text-emerald-400 hover:text-emerald-300 transition-colors"
        >
          <Plus class="w-3.5 h-3.5" />
          <span>添加字段</span>
        </button>
      </div>

      <div
        v-for="(f, idx) in fields"
        :key="f.id"
        class="bg-zinc-950 border border-zinc-800 hover:border-zinc-700/80 rounded p-2.5 transition-colors space-y-2"
      >
        <!-- Field Header: Name & Type & Delete -->
        <div class="flex items-center justify-between gap-2">
          <input
            v-model="f.name"
            class="bg-transparent text-zinc-200 font-medium border-b border-transparent hover:border-zinc-700 focus:border-emerald-500 outline-none px-0.5 text-xs flex-1"
          />
          <select
            v-model="f.widget"
            class="bg-zinc-900 border border-zinc-800 text-[10px] text-zinc-300 rounded px-1 py-0.5"
          >
            <option value="slider">滑动条 (Slider)</option>
            <option value="switch">开关 (Switch)</option>
            <option value="number">步进数值 (Input)</option>
            <option value="fixed">固定值 (Fixed)</option>
          </select>
          <button
            @click="removeField(idx)"
            class="text-zinc-600 hover:text-rose-400 transition-colors"
          >
            <Trash2 class="w-3.5 h-3.5" />
          </button>
        </div>

        <!-- Widget Render: Slider -->
        <div v-if="f.widget === 'slider'" class="space-y-1">
          <div class="flex items-center justify-between text-[11px]">
            <span class="text-zinc-500 font-mono">{{ f.min }}</span>
            <span class="text-emerald-400 font-bold font-mono text-sm">{{ f.value }}</span>
            <span class="text-zinc-500 font-mono">{{ f.max }}</span>
          </div>
          <input
            v-model.number="f.value"
            type="range"
            :min="f.min"
            :max="f.max"
            :step="f.step"
            @input="onWidgetChanged"
            class="w-full accent-emerald-500 cursor-pointer"
          />
        </div>

        <!-- Widget Render: Switch -->
        <div v-else-if="f.widget === 'switch'" class="flex items-center justify-between pt-1">
          <span class="text-[11px] text-zinc-400">状态: {{ f.value ? '已使能 (ON)' : '已关闭 (OFF)' }}</span>
          <button
            @click="f.value = f.value ? 0 : 1; onWidgetChanged()"
            class="flex items-center gap-1.5 px-3 py-1 rounded text-[11px] font-bold transition-colors border"
            :class="f.value ? 'bg-emerald-950 text-emerald-300 border-emerald-700' : 'bg-zinc-900 text-zinc-400 border-zinc-800'"
          >
            <component :is="f.value ? ToggleRight : ToggleLeft" class="w-4 h-4" />
            <span>{{ f.value ? 'ON' : 'OFF' }}</span>
          </button>
        </div>

        <!-- Widget Render: Number Input -->
        <div v-else class="flex items-center gap-2">
          <span class="text-zinc-400 text-[10px]">值:</span>
          <input
            v-model.number="f.value"
            type="number"
            :step="f.step"
            @change="onWidgetChanged"
            class="flex-1 bg-zinc-900 border border-zinc-800 rounded px-2 py-1 text-zinc-200 font-mono outline-none focus:border-emerald-500"
          />
        </div>
      </div>
    </div>
  </div>
</template>
