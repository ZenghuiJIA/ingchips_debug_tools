<script setup lang="ts">
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    modelValue: number;
    disabled?: boolean;
    label?: string;
    presets?: { label: string; value: number }[];
  }>(),
  {
    disabled: false,
    label: 'CLK:',
    presets: () => [
      { label: '1 MHz', value: 1000000 },
      { label: '2 MHz', value: 2000000 },
      { label: '5 MHz', value: 5000000 },
      { label: '10 MHz (推荐)', value: 10000000 },
      { label: '20 MHz (高速)', value: 20000000 },
      { label: '50 MHz (极速)', value: 50000000 }
    ]
  }
);

const emit = defineEmits<{
  (e: 'update:modelValue', val: number): void;
}>();

const currentVal = computed({
  get: () => props.modelValue,
  set: (val: number) => emit('update:modelValue', Number(val))
});
</script>

<template>
  <div class="flex items-center gap-1 text-xs font-mono">
    <span v-if="label" class="text-zinc-500 text-[11px]">{{ label }}</span>
    <select
      v-model.number="currentVal"
      :disabled="disabled"
      class="bg-transparent text-cyan-300 font-bold outline-none cursor-pointer disabled:opacity-50"
      title="SWD 探针通信时钟频率 (CLK)"
    >
      <option v-for="sp in presets" :key="sp.value" :value="sp.value" class="bg-zinc-900 text-zinc-100">
        {{ sp.label }}
      </option>
    </select>
  </div>
</template>
