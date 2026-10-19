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
    label: 'CPU 主频:',
    presets: () => [16, 24, 32, 48, 64, 80, 96, 120, 168, 216]
  }
);

const emit = defineEmits<{
  (e: 'update:modelValue', val: number): void;
}>();

const isCustom = ref<boolean>(!props.presets.includes(props.modelValue));
const customInput = ref<number>(props.modelValue);

watch(
  () => props.modelValue,
  (newVal) => {
    if (!props.presets.includes(newVal)) {
      isCustom.value = true;
      customInput.value = newVal;
    } else {
      isCustom.value = false;
    }
  }
);

function handleSelectChange(val: string) {
  if (val === 'custom') {
    isCustom.value = true;
  } else {
    isCustom.value = false;
    emit('update:modelValue', Number(val));
  }
}

function handleCustomApply() {
  if (customInput.value && customInput.value > 0) {
    emit('update:modelValue', Number(customInput.value));
  }
}
</script>

<template>
  <div class="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded px-2 py-0.5 text-xs font-mono">
    <span v-if="label" class="text-zinc-500">{{ label }}</span>
    <select
      :value="isCustom ? 'custom' : modelValue"
      :disabled="disabled"
      @change="(e: any) => handleSelectChange(e.target.value)"
      class="bg-transparent text-amber-400 font-bold outline-none cursor-pointer disabled:opacity-50"
      title="选择或自定义设置 MCU 当前运行主频"
    >
      <option v-for="f in presets" :key="f" :value="f" class="bg-zinc-900 text-zinc-100">
        {{ f }} MHz
      </option>
      <option value="custom" class="bg-zinc-900 text-amber-300">自定义主频...</option>
    </select>
    <input
      v-if="isCustom"
      v-model.number="customInput"
      type="number"
      :disabled="disabled"
      placeholder="MHz"
      @keyup.enter="handleCustomApply"
      @blur="handleCustomApply"
      class="w-16 bg-zinc-900 border border-amber-500/80 rounded px-1 text-amber-300 font-bold outline-none text-center"
      title="输入自定义 CPU 主频 (MHz) 并回车"
    />
  </div>
</template>
