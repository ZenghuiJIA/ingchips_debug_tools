<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';

const props = withDefaults(
  defineProps<{
    modelValue?: number;
    min?: number;
    max?: number;
    defaultSize?: number;
    direction?: 'horizontal' | 'vertical'; // 'horizontal' means resize width (handle on left/right), 'vertical' means resize height (handle on top/bottom)
    side?: 'left' | 'right' | 'top' | 'bottom'; // Which border edge the handle is located
    storageKey?: string;
  }>(),
  {
    min: 280,
    max: 800,
    defaultSize: 384,
    direction: 'horizontal',
    side: 'left',
    storageKey: ''
  }
);

const emit = defineEmits<{
  (e: 'update:modelValue', val: number): void;
  (e: 'resize', val: number): void;
}>();

// Read initial size from storage or modelValue or defaultSize
function getInitialSize(): number {
  if (props.storageKey) {
    const saved = localStorage.getItem(props.storageKey);
    if (saved) {
      const num = parseInt(saved, 10);
      if (!isNaN(num) && num >= props.min && num <= props.max) {
        return num;
      }
    }
  }
  return props.modelValue ?? props.defaultSize;
}

const currentSize = ref<number>(getInitialSize());
const isDragging = ref<boolean>(false);
let startCoord = 0;
let startSize = 0;

function persistSize(val: number) {
  if (props.storageKey) {
    try {
      localStorage.setItem(props.storageKey, val.toString());
    } catch {}
  }
}

function onMouseDown(e: MouseEvent) {
  isDragging.value = true;
  startSize = currentSize.value;
  startCoord = props.direction === 'horizontal' ? e.clientX : e.clientY;

  document.body.style.userSelect = 'none';
  document.body.style.cursor = props.direction === 'horizontal' ? 'col-resize' : 'row-resize';

  window.addEventListener('mousemove', onMouseMove);
  window.addEventListener('mouseup', onMouseUp);
}

function onMouseMove(e: MouseEvent) {
  if (!isDragging.value) return;

  let delta = 0;
  if (props.direction === 'horizontal') {
    // If handle is on the 'left' side of a right-docked drawer, dragging left (clientX decreases) should INCREASE the width!
    if (props.side === 'left') {
      delta = startCoord - e.clientX;
    } else {
      delta = e.clientX - startCoord;
    }
  } else {
    // Vertical: if handle is on 'top' of a bottom-docked drawer, dragging up (clientY decreases) should INCREASE the height!
    if (props.side === 'top') {
      delta = startCoord - e.clientY;
    } else {
      delta = e.clientY - startCoord;
    }
  }

  let nextSize = Math.round(startSize + delta);
  if (nextSize < props.min) nextSize = props.min;
  if (nextSize > props.max) nextSize = props.max;

  currentSize.value = nextSize;
  emit('update:modelValue', nextSize);
  emit('resize', nextSize);
}

function onMouseUp() {
  if (isDragging.value) {
    isDragging.value = false;
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
    persistSize(currentSize.value);
    window.removeEventListener('mousemove', onMouseMove);
    window.removeEventListener('mouseup', onMouseUp);
  }
}

function onDoubleClick() {
  // Double-click to reset to defaultSize
  currentSize.value = props.defaultSize;
  emit('update:modelValue', props.defaultSize);
  emit('resize', props.defaultSize);
  persistSize(props.defaultSize);
}

onMounted(() => {
  emit('update:modelValue', currentSize.value);
});

onUnmounted(() => {
  if (isDragging.value) {
    document.body.style.userSelect = '';
    document.body.style.cursor = '';
    window.removeEventListener('mousemove', onMouseMove);
    window.removeEventListener('mouseup', onMouseUp);
  }
});
</script>

<template>
  <div
    class="relative flex flex-col shrink-0"
    :style="direction === 'horizontal' ? { width: `${currentSize}px` } : { height: `${currentSize}px` }"
  >
    <!-- Resize Handle Bar -->
    <div
      v-if="direction === 'horizontal'"
      @mousedown="onMouseDown"
      @dblclick="onDoubleClick"
      title="拖拽调整宽度，双击复位默认大小"
      class="absolute top-0 bottom-0 z-30 w-2 cursor-col-resize flex items-center justify-center group/handle transition-colors select-none"
      :class="[
        side === 'left' ? '-left-1' : '-right-1',
        isDragging ? 'bg-emerald-500/40' : 'hover:bg-emerald-500/20'
      ]"
    >
      <!-- Center Indicator Line / Dots -->
      <div
        class="w-[2px] h-8 rounded-full transition-colors"
        :class="isDragging ? 'bg-emerald-400' : 'bg-transparent group-hover/handle:bg-emerald-400/80'"
      ></div>
    </div>

    <!-- Vertical Handle Bar -->
    <div
      v-else
      @mousedown="onMouseDown"
      @dblclick="onDoubleClick"
      title="拖拽调整高度，双击复位默认大小"
      class="absolute left-0 right-0 z-30 h-2 cursor-row-resize flex items-center justify-center group/handle transition-colors select-none"
      :class="[
        side === 'top' ? '-top-1' : '-bottom-1',
        isDragging ? 'bg-emerald-500/40' : 'hover:bg-emerald-500/20'
      ]"
    >
      <div
        class="h-[2px] w-8 rounded-full transition-colors"
        :class="isDragging ? 'bg-emerald-400' : 'bg-transparent group-hover/handle:bg-emerald-400/80'"
      ></div>
    </div>

    <!-- Inner Slot Content -->
    <div class="w-full h-full min-w-0 min-h-0 flex flex-col overflow-hidden">
      <slot :size="currentSize"></slot>
    </div>
  </div>
</template>
