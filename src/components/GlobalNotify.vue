<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue';
import { toasts, confirmState, dismissToast, resolveConfirm } from '../utils/notify';
import { CheckCircle2, AlertTriangle, AlertCircle, Info, X } from '@lucide/vue';

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape' && confirmState.value.open) {
    resolveConfirm(false);
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown));
onUnmounted(() => window.removeEventListener('keydown', onKeydown));
</script>

<template>
  <Teleport to="body">
    <div class="fixed top-4 right-4 z-[70] flex flex-col gap-2 max-w-sm w-full pointer-events-none">
      <div
        v-for="item in toasts"
        :key="item.id"
        role="alert"
        class="pointer-events-auto flex items-start gap-2.5 px-3.5 py-2.5 rounded-lg border shadow-xl text-xs backdrop-blur-sm"
        :class="{
          'bg-emerald-950/90 border-emerald-700/80 text-emerald-100': item.type === 'success',
          'bg-amber-950/90 border-amber-700/80 text-amber-100': item.type === 'warn',
          'bg-rose-950/90 border-rose-700/80 text-rose-100': item.type === 'error',
          'bg-zinc-900/95 border-zinc-700 text-zinc-100': item.type === 'info',
        }"
      >
        <CheckCircle2 v-if="item.type === 'success'" class="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
        <AlertTriangle v-else-if="item.type === 'warn'" class="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
        <AlertCircle v-else-if="item.type === 'error'" class="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
        <Info v-else class="w-4 h-4 text-cyan-400 shrink-0 mt-0.5" />
        <span class="flex-1 whitespace-pre-wrap leading-relaxed">{{ item.message }}</span>
        <button
          type="button"
          @click="dismissToast(item.id)"
          class="p-0.5 rounded hover:bg-white/10 text-zinc-400 hover:text-zinc-100 shrink-0"
        >
          <X class="w-3.5 h-3.5" />
        </button>
      </div>
    </div>

    <div
      v-if="confirmState.open"
      class="fixed inset-0 z-[75] flex items-center justify-center bg-black/65 backdrop-blur-xs p-4"
      @click.self="resolveConfirm(false)"
    >
      <div class="bg-zinc-900 border border-zinc-700 rounded-xl shadow-2xl w-full max-w-md overflow-hidden text-xs text-zinc-200">
        <div class="px-5 py-3.5 border-b border-zinc-800 bg-zinc-950/60 font-semibold text-sm text-zinc-100">
          {{ confirmState.title }}
        </div>
        <div class="px-5 py-4 whitespace-pre-wrap leading-relaxed text-zinc-300">
          {{ confirmState.message }}
        </div>
        <div class="flex items-center justify-end gap-2 px-5 py-3 border-t border-zinc-800 bg-zinc-950/60">
          <button
            type="button"
            @click="resolveConfirm(false)"
            class="px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 transition-colors"
          >
            取消
          </button>
          <button
            type="button"
            @click="resolveConfirm(true)"
            class="px-3 py-1.5 rounded-md bg-rose-600 hover:bg-rose-500 text-white font-medium transition-colors"
          >
            确认
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
