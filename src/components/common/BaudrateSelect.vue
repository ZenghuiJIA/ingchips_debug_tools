<script setup lang="ts">
import { ref, watch } from 'vue';

const props = withDefaults(
  defineProps<{
    modelValue: number;
    disabled?: boolean;
    label?: string;
    presets?: number[];
  }>(),
  {
    disabled: false,
    label: '',
    presets: () => [
      9600,
      19200,
      38400,
      57600,
      115200,
      230400,
      460800,
      921600,
      1000000,
      1152000,
      1500000,
      2000000,
      3000000
    ]
  }
);

const emit = defineEmits<{
  (e: 'update:modelValue', val: number): void;
}>();

// 本地缓冲字符串，允许用户自由输入任意数字而不立即触发父组件频繁重连
const textInput = ref<string>(String(props.modelValue || 115200));

watch(
  () => props.modelValue,
  (newVal) => {
    if (newVal && String(newVal) !== textInput.value) {
      textInput.value = String(newVal);
    }
  }
);

function applyValue(valStr: string) {
  const num = parseInt(valStr.trim(), 10);
  if (!isNaN(num) && num > 0) {
    textInput.value = String(num);
    emit('update:modelValue', num);
  } else {
    // 还原
    textInput.value = String(props.modelValue);
  }
}

function handleInputKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter') {
    applyValue(textInput.value);
    (e.target as HTMLInputElement)?.blur();
  }
}

function handleDropdownChange(val: string) {
  applyValue(val);
}
</script>

<template>
  <div class="flex items-center gap-1 text-xs font-mono">
    <span v-if="label" class="text-zinc-500 text-[11px] shrink-0">{{ label }}</span>
    <div class="flex items-center bg-zinc-950 border border-zinc-800 rounded hover:border-zinc-700 transition-colors px-1 py-0.5">
      <!-- 自由输入任意非标波特率 -->
      <input
        type="text"
        v-model="textInput"
        :disabled="disabled"
        @blur="applyValue(textInput)"
        @keydown="handleInputKeydown"
        placeholder="波特率"
        class="w-20 bg-transparent text-amber-300 font-bold outline-none text-xs text-center"
        title="可直接输入任意自定义波特率，按回车或失焦生效"
      />
      <!-- 快速选择预设波特率 -->
      <select
        :value="presets.includes(modelValue) ? modelValue : ''"
        :disabled="disabled"
        @change="(e: any) => handleDropdownChange(e.target.value)"
        class="bg-transparent text-zinc-400 outline-none cursor-pointer w-4 text-[10px] hover:text-zinc-200"
        title="选择常用标准波特率"
      >
        <option value="" disabled class="bg-zinc-900 text-zinc-500">常用预设...</option>
        <option v-for="b in presets" :key="b" :value="b" class="bg-zinc-900 text-zinc-200">
          {{ b >= 1000000 ? (b / 1000000) + 'M' : b }}
        </option>
      </select>
    </div>
  </div>
</template>

