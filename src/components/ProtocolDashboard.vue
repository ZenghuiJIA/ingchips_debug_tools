<script setup lang="ts">
import { ref, watch } from 'vue';
import {
  Sliders,
  Trash2,
  X,
  Send,
  Zap,
  ToggleLeft,
  ToggleRight,
  Sparkles,
  GripVertical,
  ArrowUp,
  ArrowDown
} from '@lucide/vue';
import { safeInvoke } from '../utils/ipc';
import { appendChecksum, type ChecksumAlgorithm } from '../utils/crc';
import { t } from '../utils/i18n';

export interface ProtocolField {
  id: string;
  name: string;
  type: 'uint8' | 'uint16' | 'uint32' | 'int16' | 'bool';
  widget: 'slider' | 'switch' | 'number' | 'button' | 'fixed';
  min: number;
  max: number;
  step: number;
  value: number; // Current value
  unit?: string;
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

const STORAGE_KEY = 'ai_hil_protocol_dashboard_v2';

// 1. 协议流水线规约配置: 帧头、校验、帧尾
const headerHex = ref<string>('AA 55');
const tailOption = ref<string>('crlf'); // 'none' | 'crlf' | 'lf' | '55aa' | 'ffff' | 'custom'
const customTailHex = ref<string>('0D 0A');
const checksumType = ref<ChecksumAlgorithm>('modbus_crc16');
const autoSendOnChange = ref<boolean>(true);

// 2. 字段列表
const fields = ref<ProtocolField[]>([
  { id: 'f_cmd', name: '功能码(CMD)', type: 'uint8', widget: 'fixed', min: 0, max: 255, step: 1, value: 0x01 },
  { id: 'f_pwm', name: 'PWM输出/占空比', type: 'uint16', widget: 'slider', min: 0, max: 1000, step: 10, value: 350, unit: '‰' },
  { id: 'f_led', name: '继电器/LED开关', type: 'bool', widget: 'switch', min: 0, max: 1, step: 1, value: 1 },
  { id: 'f_target', name: '设定目标值', type: 'int16', widget: 'number', min: -5000, max: 5000, step: 50, value: 1200, unit: 'rpm' }
]);

// 载入本地缓存配置
try {
  const cached = localStorage.getItem(STORAGE_KEY);
  if (cached) {
    const data = JSON.parse(cached);
    if (data.fields && Array.isArray(data.fields)) fields.value = data.fields;
    if (data.headerHex !== undefined) headerHex.value = data.headerHex;
    if (data.tailOption !== undefined) tailOption.value = data.tailOption;
    if (data.customTailHex !== undefined) customTailHex.value = data.customTailHex;
    if (data.checksumType !== undefined) checksumType.value = data.checksumType;
    if (data.autoSendOnChange !== undefined) autoSendOnChange.value = data.autoSendOnChange;
  }
} catch (e) {
  // Ignore corrupted cache
}

// 深度监听并持久化
watch([fields, headerHex, tailOption, customTailHex, checksumType, autoSendOnChange], () => {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({
    fields: fields.value,
    headerHex: headerHex.value,
    tailOption: tailOption.value,
    customTailHex: customTailHex.value,
    checksumType: checksumType.value,
    autoSendOnChange: autoSendOnChange.value
  }));
}, { deep: true });

// 解析帧头字节
function parseHexBytes(hexStr: string): number[] {
  const clean = hexStr.replace(/[^0-9a-fA-F]/g, '');
  const res: number[] = [];
  for (let i = 0; i < clean.length; i += 2) {
    res.push(parseInt(clean.substring(i, i + 2), 16));
  }
  return res;
}

// 解析帧尾字节
function getTailBytes(): number[] {
  switch (tailOption.value) {
    case 'none':
      return [];
    case 'crlf':
      return [0x0D, 0x0A]; // \r\n
    case 'lf':
      return [0x0A]; // \n
    case '55aa':
      return [0x55, 0xAA];
    case 'ffff':
      return [0xFF, 0xFF];
    case 'custom':
      return parseHexBytes(customTailHex.value);
    default:
      return [];
  }
}

// 单个字段变量的 HEX 字节渲染
function getFieldHexBytes(f: ProtocolField): number[] {
  const bytes: number[] = [];
  const v = Math.round(f.value);
  if (f.type === 'uint8' || f.type === 'bool') {
    bytes.push(v & 0xFF);
  } else if (f.type === 'uint16' || f.type === 'int16') {
    // Big Endian
    bytes.push((v >> 8) & 0xFF);
    bytes.push(v & 0xFF);
  } else if (f.type === 'uint32') {
    bytes.push((v >>> 24) & 0xFF);
    bytes.push((v >>> 16) & 0xFF);
    bytes.push((v >>> 8) & 0xFF);
    bytes.push(v & 0xFF);
  }
  return bytes;
}

// 结构化预览分段 (用于实时高亮着色展示)
interface FrameSegmentPreview {
  header: string;
  fields: Array<{ name: string; hex: string; isHot?: boolean }>;
  checksum: string;
  tail: string;
  totalLength: number;
}

const framePreview = ref<FrameSegmentPreview>({
  header: '',
  fields: [],
  checksum: '',
  tail: '',
  totalLength: 0
});

async function updateLivePreview() {
  const headerBytes = parseHexBytes(headerHex.value);
  const tailBytes = getTailBytes();

  // 1. 各变量字节拼接
  const fieldsPayload: number[] = [];
  const fieldSegments: Array<{ name: string; hex: string }> = [];

  for (const f of fields.value) {
    const b = getFieldHexBytes(f);
    fieldsPayload.push(...b);
    fieldSegments.push({
      name: f.name,
      hex: b.map(x => x.toString(16).padStart(2, '0').toUpperCase()).join(' ')
    });
  }

  // 2. 带帧头的全报文 (用于计算校验)
  const preCheckBytes = [...headerBytes, ...fieldsPayload];
  const withCheckBytes = await appendChecksum(preCheckBytes, checksumType.value);
  const checkBytes = withCheckBytes.slice(preCheckBytes.length);

  // 3. 最终组合帧
  const total = withCheckBytes.length + tailBytes.length;

  framePreview.value = {
    header: headerBytes.map(x => x.toString(16).padStart(2, '0').toUpperCase()).join(' '),
    fields: fieldSegments,
    checksum: checkBytes.map(x => x.toString(16).padStart(2, '0').toUpperCase()).join(' '),
    tail: tailBytes.map(x => x.toString(16).padStart(2, '0').toUpperCase()).join(' '),
    totalLength: total
  };
}

watch([fields, headerHex, tailOption, customTailHex, checksumType], () => {
  updateLivePreview();
}, { deep: true, immediate: true });

// 构建最终完整发送报文字节
async function buildFullFrame(): Promise<number[]> {
  const headerBytes = parseHexBytes(headerHex.value);
  const tailBytes = getTailBytes();
  const fieldsPayload: number[] = [];
  for (const f of fields.value) {
    fieldsPayload.push(...getFieldHexBytes(f));
  }
  const preCheckBytes = [...headerBytes, ...fieldsPayload];
  const withCheckBytes = await appendChecksum(preCheckBytes, checksumType.value);
  return [...withCheckBytes, ...tailBytes];
}

async function sendFrame() {
  if (!props.isConnected) {
    emit('log', t('proto_err_no_conn'), 'error');
    return;
  }

  try {
    const finalBytes = await buildFullFrame();
    const count: number = await safeInvoke('send_serial_data', {
      data: finalBytes,
      portName: props.portName
    });
    emit('bytes-sent', count);

    const hexStr = finalBytes.map(b => b.toString(16).padStart(2, '0').toUpperCase()).join(' ');
    emit('log', `[TX Dashboard] ${hexStr}`, 'tx');
  } catch (err: any) {
    emit('log', t('proto_err_send', { err }), 'error');
  }
}

function onWidgetChanged() {
  updateLivePreview();
  if (autoSendOnChange.value && props.isConnected) {
    sendFrame();
  }
}

// 便捷添加预设控件模板
function addQuickWidget(type: 'slider' | 'switch' | 'button' | 'number') {
  const now = Date.now();
  if (type === 'slider') {
    fields.value.push({
      id: 'f_' + now,
      name: '调节滑块',
      type: 'uint16',
      widget: 'slider',
      min: 0,
      max: 100,
      step: 1,
      value: 50,
      unit: '%'
    });
  } else if (type === 'switch') {
    fields.value.push({
      id: 'f_' + now,
      name: '开关控制',
      type: 'bool',
      widget: 'switch',
      min: 0,
      max: 1,
      step: 1,
      value: 1
    });
  } else if (type === 'button') {
    fields.value.push({
      id: 'f_' + now,
      name: '触发按键',
      type: 'uint8',
      widget: 'button',
      min: 0,
      max: 255,
      step: 1,
      value: 1
    });
  } else {
    fields.value.push({
      id: 'f_' + now,
      name: '数值参数',
      type: 'int16',
      widget: 'number',
      min: 0,
      max: 65535,
      step: 1,
      value: 100
    });
  }
}

function removeField(idx: number) {
  fields.value.splice(idx, 1);
  updateLivePreview();
}

// 拖拽排序状态与逻辑 (基于 Pointer Event，彻底解决 HTML5 Drag 在部分 WebView 内不响应调换位置的问题)
const draggedIdx = ref<number | null>(null);
const dragOverIdx = ref<number | null>(null);

let isPointerDragging = false;

function onGripPointerDown(idx: number, e: PointerEvent) {
  // 只响应鼠标左键
  if (e.button !== 0) return;
  
  isPointerDragging = true;
  draggedIdx.value = idx;
  dragOverIdx.value = idx;

  document.body.style.userSelect = 'none';

  function onPointerMove(moveEv: PointerEvent) {
    if (!isPointerDragging) return;
    
    // 获取当前鼠标指针下方的元素
    const elemUnder = document.elementFromPoint(moveEv.clientX, moveEv.clientY);
    if (!elemUnder) return;

    // 寻找最近的拥有 data-field-idx 属性的卡片容器
    const cardElem = elemUnder.closest('[data-field-idx]');
    if (cardElem) {
      const targetIdxAttr = cardElem.getAttribute('data-field-idx');
      if (targetIdxAttr !== null) {
        const targetIdx = parseInt(targetIdxAttr, 10);
        if (!isNaN(targetIdx) && targetIdx !== draggedIdx.value && targetIdx >= 0 && targetIdx < fields.value.length) {
          const fromIdx = draggedIdx.value!;
          const newFields = [...fields.value];
          const [movedItem] = newFields.splice(fromIdx, 1);
          newFields.splice(targetIdx, 0, movedItem);
          fields.value = newFields;

          draggedIdx.value = targetIdx;
          dragOverIdx.value = targetIdx;
          updateLivePreview();
        }
      }
    }
  }

  function onPointerUp() {
    isPointerDragging = false;
    draggedIdx.value = null;
    dragOverIdx.value = null;
    document.body.style.userSelect = '';
    window.removeEventListener('pointermove', onPointerMove);
    window.removeEventListener('pointerup', onPointerUp);
    updateLivePreview();
  }

  window.addEventListener('pointermove', onPointerMove);
  window.addEventListener('pointerup', onPointerUp);
}

// 快速上移/下移
function moveFieldUp(idx: number) {
  if (idx <= 0) return;
  const newArr = [...fields.value];
  const temp = newArr[idx];
  newArr[idx] = newArr[idx - 1];
  newArr[idx - 1] = temp;
  fields.value = newArr;
  updateLivePreview();
}

function moveFieldDown(idx: number) {
  if (idx >= fields.value.length - 1) return;
  const newArr = [...fields.value];
  const temp = newArr[idx];
  newArr[idx] = newArr[idx + 1];
  newArr[idx + 1] = temp;
  fields.value = newArr;
  updateLivePreview();
}
</script>

<template>
  <div class="w-full h-full bg-zinc-900 border-l border-zinc-800 flex flex-col font-mono text-xs select-none">
    <!-- Header -->
    <div class="px-3 py-2 border-b border-zinc-800 flex items-center justify-between bg-zinc-900/90 shrink-0">
      <div class="flex items-center gap-1.5 font-semibold text-emerald-400">
        <Sliders class="w-4 h-4 text-emerald-400" />
        <span>自定义交互控制台 (Protocol Dashboard)</span>
      </div>
      <button
        @click="emit('close')"
        class="p-1 text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 rounded transition-colors"
      >
        <X class="w-4 h-4" />
      </button>
    </div>

    <!-- 1. 协议流水线规约设计条 (帧头 -> 变量 -> 校验 -> 帧尾) -->
    <div class="p-2.5 border-b border-zinc-800 bg-zinc-950/60 space-y-2 shrink-0">
      <div class="flex items-center justify-between text-[11px] font-bold text-zinc-300">
        <span class="flex items-center gap-1 text-emerald-400">
          <Sparkles class="w-3.5 h-3.5" />
          <span>通信规约流水线 (Frame Pipeline)</span>
        </span>
        <span class="text-[10px] text-zinc-500">共 {{ framePreview.totalLength }} 字节</span>
      </div>

      <!-- 流水线输入框组 -->
      <div class="grid grid-cols-3 gap-1.5 text-[11px]">
        <!-- 帧头 Header -->
        <div>
          <label class="block text-[10px] text-cyan-400 font-semibold mb-0.5">1. 帧头 (Header)</label>
          <input
            v-model="headerHex"
            type="text"
            placeholder="AA 55"
            class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-1.5 py-1 text-cyan-300 focus:border-cyan-500 outline-none uppercase font-mono text-center font-bold"
            title="输入 16 进制帧头 (如 AA 55)"
          />
        </div>

        <!-- 校验 Checksum -->
        <div>
          <label class="block text-[10px] text-sky-400 font-semibold mb-0.5">2. 校验算法</label>
          <select
            v-model="checksumType"
            class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-1 py-1 text-sky-300 focus:border-sky-500 outline-none text-[10.5px] cursor-pointer"
          >
            <option value="none">无校验</option>
            <option value="modbus_crc16">CRC16-Modbus</option>
            <option value="crc16_ccitt">CRC16-CCITT</option>
            <option value="checksum8">CheckSum8</option>
            <option value="xor8">XOR-8</option>
          </select>
        </div>

        <!-- 帧尾 Tail / Suffix (新增) -->
        <div>
          <label class="block text-[10px] text-purple-400 font-semibold mb-0.5">3. 帧尾 (Tail)</label>
          <select
            v-model="tailOption"
            class="w-full bg-zinc-900 border border-zinc-700/80 rounded px-1 py-1 text-purple-300 focus:border-purple-500 outline-none text-[10.5px] cursor-pointer"
            title="选择报文帧尾格式"
          >
            <option value="none">无帧尾</option>
            <option value="crlf">\r\n (0D 0A)</option>
            <option value="lf">\n (0A)</option>
            <option value="55aa">55 AA</option>
            <option value="ffff">FF FF</option>
            <option value="custom">自定义 HEX</option>
          </select>
        </div>
      </div>

      <!-- 自定义帧尾输入 -->
      <div v-if="tailOption === 'custom'" class="flex items-center gap-1.5 bg-zinc-900/80 p-1 rounded border border-purple-900/60">
        <span class="text-[10px] text-purple-300">自定义帧尾 HEX:</span>
        <input
          v-model="customTailHex"
          placeholder="0D 0A"
          class="flex-1 bg-zinc-950 border border-zinc-800 rounded px-1.5 py-0.5 text-purple-200 outline-none uppercase font-mono text-xs"
        />
      </div>

      <!-- 报文积木实时可视化着色预览 (直观看到控件改变的数据位置) -->
      <div class="bg-zinc-950 border border-zinc-800 rounded p-2 text-[10.5px] space-y-1">
        <div class="flex items-center justify-between text-zinc-400 text-[10px]">
          <span>实时期望报文透视预览:</span>
          <span>按字节着色</span>
        </div>
        <div class="flex items-center flex-wrap gap-1 font-mono text-xs leading-relaxed bg-zinc-900/60 p-1.5 rounded border border-zinc-800/80">
          <!-- 帧头 -->
          <span v-if="framePreview.header" class="px-1 py-0.2 rounded bg-cyan-950/80 border border-cyan-800 text-cyan-300 font-bold" title="[帧头 Header]">
            {{ framePreview.header }}
          </span>
          <span v-if="framePreview.header" class="text-zinc-600 text-[10px]">➔</span>

          <!-- 控件变量载荷 -->
          <template v-for="(f, i) in framePreview.fields" :key="i">
            <span
              class="px-1 py-0.2 rounded bg-amber-950/80 border border-amber-800/80 text-amber-300 font-bold"
              :title="`[变量: ${f.name}]`"
            >
              {{ f.hex || '00' }}
            </span>
            <span v-if="i < framePreview.fields.length - 1" class="text-zinc-700 text-[9px]">|</span>
          </template>

          <!-- 校验 -->
          <template v-if="framePreview.checksum">
            <span class="text-zinc-600 text-[10px]">➔</span>
            <span class="px-1 py-0.2 rounded bg-sky-950/80 border border-sky-800 text-sky-300 font-bold" title="[自动计算的校验码]">
              {{ framePreview.checksum }}
            </span>
          </template>

          <!-- 帧尾 -->
          <template v-if="framePreview.tail">
            <span class="text-zinc-600 text-[10px]">➔</span>
            <span class="px-1 py-0.2 rounded bg-purple-950/80 border border-purple-800 text-purple-300 font-bold" title="[帧尾 Tail]">
              {{ framePreview.tail }}
            </span>
          </template>
        </div>
      </div>

      <!-- 发送控制行 -->
      <div class="flex items-center justify-between pt-0.5">
        <label class="flex items-center gap-1.5 text-[11px] text-zinc-300 cursor-pointer" title="滑动或点击任何控件时自动立即发送">
          <input
            type="checkbox"
            v-model="autoSendOnChange"
            class="rounded bg-zinc-800 border-zinc-700 text-emerald-500 focus:ring-0"
          />
          <Zap class="w-3.5 h-3.5 text-amber-400" />
          <span>数值变动实时下发</span>
        </label>

        <button
          @click="sendFrame"
          :disabled="!isConnected"
          class="flex items-center gap-1 px-3 py-1 bg-emerald-600 hover:bg-emerald-500 text-white rounded font-medium transition-colors disabled:opacity-40"
        >
          <Send class="w-3 h-3" />
          <span>立即发送此帧</span>
        </button>
      </div>
    </div>

    <!-- 2. 便捷控件库快捷托盘 (一键添加控件) -->
    <div class="px-3 py-2 bg-zinc-950/30 border-b border-zinc-800 flex items-center justify-between shrink-0">
      <span class="text-[10px] text-zinc-400 font-bold uppercase tracking-wider">快速添加控件:</span>
      <div class="flex items-center gap-1">
        <button
          @click="addQuickWidget('slider')"
          class="px-2 py-0.5 rounded bg-zinc-800 hover:bg-amber-950/60 hover:text-amber-300 text-zinc-300 border border-zinc-700 text-[10.5px] transition-colors"
          title="添加数值滑块 (用于调PWM/调速)"
        >
          + 滑块
        </button>
        <button
          @click="addQuickWidget('switch')"
          class="px-2 py-0.5 rounded bg-zinc-800 hover:bg-emerald-950/60 hover:text-emerald-300 text-zinc-300 border border-zinc-700 text-[10.5px] transition-colors"
          title="添加通断开关 (用于开关灯/使能)"
        >
          + 开关
        </button>
        <button
          @click="addQuickWidget('button')"
          class="px-2 py-0.5 rounded bg-zinc-800 hover:bg-cyan-950/60 hover:text-cyan-300 text-zinc-300 border border-zinc-700 text-[10.5px] transition-colors"
          title="添加触发按键 (点击发送单脉冲指令)"
        >
          + 按键
        </button>
        <button
          @click="addQuickWidget('number')"
          class="px-2 py-0.5 rounded bg-zinc-800 hover:bg-purple-950/60 hover:text-purple-300 text-zinc-300 border border-zinc-700 text-[10.5px] transition-colors"
          title="添加参数输入框"
        >
          + 参数
        </button>
      </div>
    </div>

    <!-- 3. 控件列表容器 -->
    <div class="flex-1 overflow-auto p-3 space-y-3 min-h-0">
      <div v-if="fields.length === 0" class="h-32 flex flex-col items-center justify-center text-zinc-500 text-xs text-center border border-dashed border-zinc-800 rounded-lg">
        <span>当前无控制控件</span>
        <span class="text-[10px] text-zinc-600 mt-1">点击上方「+ 滑块 / 开关 / 按键」快速添加</span>
      </div>

      <div
        v-for="(f, idx) in fields"
        :key="f.id"
        :data-field-idx="idx"
        class="bg-zinc-950 border rounded-lg p-2.5 transition-all space-y-2 shadow-xs group/card relative select-none"
        :class="[
          draggedIdx === idx ? 'opacity-40 border-amber-500 scale-[0.98] ring-1 ring-amber-500/50' : 'hover:border-zinc-700/80 border-zinc-800'
        ]"
      >
        <!-- 控件标题、拖动把手、类型与操作 -->
        <div class="flex items-center justify-between gap-1.5">
          <!-- 拖动抓手与序号 -->
          <div
            @pointerdown="onGripPointerDown(idx, $event)"
            class="flex items-center gap-1 cursor-grab active:cursor-grabbing text-zinc-500 hover:text-amber-400 p-0.5 rounded hover:bg-zinc-800/60 transition-colors select-none shrink-0 touch-none"
            title="按住鼠标拖拽实时调换前后顺序"
          >
            <GripVertical class="w-4 h-4 pointer-events-none" />
            <span class="text-[9.5px] font-mono text-zinc-400 font-semibold bg-zinc-900 border border-zinc-800 px-1 rounded pointer-events-none">#{{ idx + 1 }}</span>
          </div>

          <input
            v-model="f.name"
            class="bg-transparent text-zinc-200 font-bold border-b border-transparent hover:border-zinc-700 focus:border-amber-500 outline-none px-0.5 text-xs flex-1 truncate"
            title="点击修改控件标签名"
          />

          <!-- 字节长度/数据类型 -->
          <select
            v-model="f.type"
            @change="onWidgetChanged"
            class="bg-zinc-900 border border-zinc-800 text-[10px] text-amber-300 rounded px-1 py-0.5 outline-none shrink-0"
            title="选择该变量占用的字节大小"
          >
            <option value="uint8">1 字节 (uint8)</option>
            <option value="uint16">2 字节 (uint16)</option>
            <option value="int16">2 字节 (int16)</option>
            <option value="uint32">4 字节 (uint32)</option>
            <option value="bool">1 字节 (bool)</option>
          </select>

          <!-- 控件表现形式 -->
          <select
            v-model="f.widget"
            class="bg-zinc-900 border border-zinc-800 text-[10px] text-zinc-300 rounded px-1 py-0.5 outline-none shrink-0"
          >
            <option value="slider">滑块</option>
            <option value="switch">开关</option>
            <option value="button">按键</option>
            <option value="number">输入框</option>
            <option value="fixed">固定值</option>
          </select>

          <!-- 快速上移/下移与删除 -->
          <div class="flex items-center gap-0.5 shrink-0">
            <button
              @click="moveFieldUp(idx)"
              :disabled="idx === 0"
              class="text-zinc-600 hover:text-zinc-200 disabled:opacity-20 transition-colors p-0.5"
              title="向上移动一位"
            >
              <ArrowUp class="w-3.5 h-3.5" />
            </button>
            <button
              @click="moveFieldDown(idx)"
              :disabled="idx === fields.length - 1"
              class="text-zinc-600 hover:text-zinc-200 disabled:opacity-20 transition-colors p-0.5"
              title="向下移动一位"
            >
              <ArrowDown class="w-3.5 h-3.5" />
            </button>
            <button
              @click="removeField(idx)"
              class="text-zinc-600 hover:text-rose-400 transition-colors p-0.5 ml-0.5"
              title="删除此控件"
            >
              <Trash2 class="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        <!-- 控件交互交互区: Slider (数值滑块) -->
        <div v-if="f.widget === 'slider'" class="space-y-1 bg-zinc-900/40 p-2 rounded border border-zinc-800/40">
          <div class="flex items-center justify-between text-[11px]">
            <span class="text-zinc-500 font-mono">Min: {{ f.min }}</span>
            <span class="text-amber-400 font-bold font-mono text-sm">
              {{ f.value }} <span class="text-[10px] text-zinc-500 font-normal">{{ f.unit || '' }}</span>
            </span>
            <span class="text-zinc-500 font-mono">Max: {{ f.max }}</span>
          </div>
          <input
            v-model.number="f.value"
            type="range"
            :min="f.min"
            :max="f.max"
            :step="f.step"
            @input="onWidgetChanged"
            class="w-full accent-amber-500 cursor-pointer"
          />
          <div class="flex items-center gap-2 pt-1 text-[10px] text-zinc-500">
            <span>范围:</span>
            <input v-model.number="f.min" type="number" class="w-12 bg-zinc-950 border border-zinc-800 rounded px-1 text-zinc-300 outline-none text-center" />
            <span>~</span>
            <input v-model.number="f.max" type="number" class="w-12 bg-zinc-950 border border-zinc-800 rounded px-1 text-zinc-300 outline-none text-center" />
          </div>
        </div>

        <!-- 控件交互区: Switch (拨码开关) -->
        <div v-else-if="f.widget === 'switch'" class="flex items-center justify-between p-1.5 bg-zinc-900/40 rounded border border-zinc-800/40">
          <span class="text-[11px] text-zinc-400">
            状态: <strong :class="f.value ? 'text-emerald-400' : 'text-zinc-500'">{{ f.value ? '已接通 (1)' : '已断开 (0)' }}</strong>
          </span>
          <button
            @click="f.value = f.value ? 0 : 1; onWidgetChanged()"
            class="flex items-center gap-1.5 px-3 py-1 rounded text-[11px] font-bold transition-all border shadow-xs"
            :class="f.value ? 'bg-emerald-950 text-emerald-300 border-emerald-700' : 'bg-zinc-900 text-zinc-400 border-zinc-800'"
          >
            <component :is="f.value ? ToggleRight : ToggleLeft" class="w-4 h-4" />
            <span>{{ f.value ? 'ON' : 'OFF' }}</span>
          </button>
        </div>

        <!-- 控件交互区: Button (单发脉冲按键) -->
        <div v-else-if="f.widget === 'button'" class="flex items-center justify-between p-1.5 bg-zinc-900/40 rounded border border-zinc-800/40">
          <span class="text-[11px] text-zinc-400">发送此键值: {{ f.value }}</span>
          <button
            @click="onWidgetChanged()"
            class="flex items-center gap-1 px-3 py-1 bg-cyan-700 hover:bg-cyan-600 text-zinc-100 rounded text-xs font-semibold shadow-xs transition-colors"
          >
            <Send class="w-3 h-3" />
            <span>立即触发</span>
          </button>
        </div>

        <!-- 控件交互区: Number Input (参数输入框) -->
        <div v-else class="flex items-center gap-2 p-1.5 bg-zinc-900/40 rounded border border-zinc-800/40">
          <span class="text-zinc-400 text-[10px]">值:</span>
          <input
            v-model.number="f.value"
            type="number"
            :step="f.step"
            @change="onWidgetChanged"
            class="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-amber-300 font-bold font-mono outline-none focus:border-amber-500"
          />
          <span v-if="f.unit" class="text-zinc-500 text-xs">{{ f.unit }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
