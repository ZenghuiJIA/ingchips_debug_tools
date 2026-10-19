<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { RefreshCw } from '@lucide/vue';
import { safeInvoke } from '../../utils/ipc';


export interface DebugProbeItem {
  unique_id: string;
  description: string;
  vendor_name?: string;
  product_name?: string;
}

const props = withDefaults(
  defineProps<{
    modelValue: string;
    disabled?: boolean;
    autoScan?: boolean;
    maxWidth?: string;
  }>(),
  {
    disabled: false,
    autoScan: true,
    maxWidth: '180px'
  }
);

const emit = defineEmits<{
  (e: 'update:modelValue', val: string): void;
  (e: 'refreshed', probes: DebugProbeItem[]): void;
}>();

const probes = ref<DebugProbeItem[]>([]);
const isScanning = ref<boolean>(false);

function formatProbeLabel(p: DebugProbeItem): string {
  const name = p.product_name || p.description || 'Probe';
  const shortId = p.unique_id ? p.unique_id.slice(-6) : '';
  return `${name} (${shortId})`;
}

async function scanProbes() {
  if (isScanning.value) return;
  isScanning.value = true;
  try {
    const res: any = await safeInvoke('pyocd_list_probes');
    if (Array.isArray(res)) {
      probes.value = res;
      emit('refreshed', res);
      // 如果当前绑定的 probe 仍在列表内，继续保持；否则若列表非空且原先为空，可选择
      if (props.modelValue && !res.some((p: any) => p.unique_id === props.modelValue)) {
        // 探针已拔出，保留或者在选择器显示
      }
    }
  } catch (e) {
    console.warn('[ProbeSelect] scanProbes error:', e);
  } finally {
    isScanning.value = false;
  }
}

function handleSelectChange(val: string) {
  emit('update:modelValue', val);
}

onMounted(() => {
  if (props.autoScan) {
    scanProbes();
  }
});
</script>

<template>
  <div class="flex items-center gap-1">
    <select
      :value="modelValue"
      :disabled="disabled"
      @change="(e: any) => handleSelectChange(e.target.value)"
      class="bg-transparent text-xs text-zinc-300 font-mono outline-none cursor-pointer truncate disabled:opacity-50"
      :style="{ maxWidth }"
      title="选择调试探针 (DAPLink / J-Link)"
    >
      <option value="" class="bg-zinc-900 text-zinc-300">
        {{ probes.length === 0 ? '未检测到调试设备' : '默认调试器 (自动识别)' }}
      </option>
      <option
        v-for="p in probes"
        :key="p.unique_id"
        :value="p.unique_id"
        class="bg-zinc-900 text-zinc-100"
      >
        {{ formatProbeLabel(p) }}
      </option>
    </select>
    <button
      @click="scanProbes"
      :disabled="isScanning || disabled"
      class="p-1 hover:bg-zinc-800 rounded text-zinc-400 hover:text-zinc-200 transition-colors disabled:opacity-50"
      title="刷新调试设备"
    >
      <RefreshCw class="w-3 h-3" :class="{ 'animate-spin': isScanning }" />
    </button>
  </div>
</template>
