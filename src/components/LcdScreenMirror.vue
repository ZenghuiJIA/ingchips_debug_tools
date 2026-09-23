<script setup lang="ts">
import { ref, onUnmounted } from 'vue';
import { safeInvoke } from '../utils/ipc';
import {
  Monitor,
  Camera,
  Play,
  Square,
  Download,
  AlertTriangle
} from '@lucide/vue';

const fbAddress = ref<string>('0x20000000');
const fbWidth = ref<number>(320);
const fbHeight = ref<number>(240);
const pixelFormat = ref<'rgb565' | 'rgb888' | 'argb8888' | 'mono'>('rgb565');

const isAutoRefreshing = ref<boolean>(false);
const refreshIntervalMs = ref<number>(500);
let autoTimer: any = null;

const isCapturing = ref<boolean>(false);
const errorMsg = ref<string>('');
const lastCaptureTime = ref<string>('');
const currentImageData = ref<string>('');
const capturedCount = ref<number>(0);

async function captureScreen() {
  if (isCapturing.value) return;
  isCapturing.value = true;
  errorMsg.value = '';

  try {
    const res: any = await safeInvoke('pyocd_capture_framebuffer', {
      address: fbAddress.value.trim(),
      width: fbWidth.value,
      height: fbHeight.value,
      pixelFormat: pixelFormat.value
    });

    if (res && res.status === 'success' && res.image_base64) {
      currentImageData.value = res.image_base64;
      capturedCount.value++;
      lastCaptureTime.value = new Date().toLocaleTimeString();
    } else {
      errorMsg.value = res?.message || '读取显存失败或目标未处于连接就绪状态';
    }
  } catch (err: any) {
    errorMsg.value = `截图发生异常: ${err}`;
  } finally {
    isCapturing.value = false;
  }
}

function toggleAutoRefresh() {
  if (isAutoRefreshing.value) {
    stopAutoRefresh();
  } else {
    startAutoRefresh();
  }
}

function startAutoRefresh() {
  isAutoRefreshing.value = true;
  captureScreen();
  autoTimer = setInterval(() => {
    captureScreen();
  }, Math.max(200, refreshIntervalMs.value));
}

function stopAutoRefresh() {
  isAutoRefreshing.value = false;
  if (autoTimer) {
    clearInterval(autoTimer);
    autoTimer = null;
  }
}

function downloadImage() {
  if (!currentImageData.value) return;
  const a = document.createElement('a');
  a.href = currentImageData.value;
  a.download = `lcd_screenshot_${new Date().toISOString().replace(/[:.]/g, '-')}.png`;
  a.click();
}

onUnmounted(() => {
  stopAutoRefresh();
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-mono text-xs overflow-hidden select-none">
    <!-- Top Action Toolbar -->
    <div class="bg-zinc-900 border-b border-zinc-800 px-4 py-2 flex items-center justify-between gap-3 shrink-0 flex-wrap">
      <div class="flex items-center gap-2 font-bold text-sm text-cyan-400">
        <Monitor class="w-4 h-4 text-cyan-400" />
        <span>屏幕显存实时镜像与截屏 (LCD Screen Mirror)</span>
      </div>

      <!-- Parameters Config -->
      <div class="flex items-center gap-2">
        <div class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1">
          <span class="text-[10px] text-zinc-400">显存基址:</span>
          <input
            v-model="fbAddress"
            type="text"
            placeholder="0x20000000"
            class="w-24 bg-transparent text-cyan-300 font-bold outline-none text-xs"
          />
        </div>

        <div class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1">
          <span class="text-[10px] text-zinc-400">分辨率:</span>
          <input
            v-model.number="fbWidth"
            type="number"
            class="w-12 bg-transparent text-zinc-200 outline-none text-center"
          />
          <span class="text-zinc-600">×</span>
          <input
            v-model.number="fbHeight"
            type="number"
            class="w-12 bg-transparent text-zinc-200 outline-none text-center"
          />
        </div>

        <div class="flex items-center gap-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1">
          <span class="text-[10px] text-zinc-400">格式:</span>
          <select
            v-model="pixelFormat"
            class="bg-transparent text-zinc-200 outline-none cursor-pointer"
          >
            <option value="rgb565" class="bg-zinc-900">RGB565 (16bit)</option>
            <option value="rgb888" class="bg-zinc-900">RGB888 (24bit)</option>
            <option value="argb8888" class="bg-zinc-900">ARGB8888 (32bit)</option>
            <option value="mono" class="bg-zinc-900">单色位图 (1bit)</option>
          </select>
        </div>

        <!-- Single Capture Button -->
        <button
          @click="captureScreen"
          :disabled="isCapturing"
          class="flex items-center gap-1.5 px-3 py-1 bg-cyan-600 hover:bg-cyan-500 text-white rounded font-semibold transition-colors disabled:opacity-40"
        >
          <Camera class="w-3.5 h-3.5" :class="{ 'animate-spin': isCapturing }" />
          <span>抓取单帧</span>
        </button>

        <!-- Continuous Auto Refresh -->
        <button
          @click="toggleAutoRefresh"
          class="flex items-center gap-1.5 px-3 py-1 rounded font-semibold transition-colors border"
          :class="isAutoRefreshing
            ? 'bg-rose-950 text-rose-300 border-rose-700 animate-pulse'
            : 'bg-zinc-800 text-zinc-200 border-zinc-700 hover:bg-zinc-700'"
        >
          <component :is="isAutoRefreshing ? Square : Play" class="w-3.5 h-3.5" />
          <span>{{ isAutoRefreshing ? '停止实时镜像' : '开启连续镜像' }}</span>
        </button>

        <!-- Save PNG -->
        <button
          v-if="currentImageData"
          @click="downloadImage"
          class="flex items-center gap-1.5 px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 rounded transition-colors"
          title="导出当前显存图像为 PNG"
        >
          <Download class="w-3.5 h-3.5 text-zinc-400" />
          <span>保存图片</span>
        </button>
      </div>
    </div>

    <!-- Error Alert -->
    <div v-if="errorMsg" class="bg-rose-950/60 border-b border-rose-800 text-rose-300 px-4 py-2 text-xs flex items-center gap-2">
      <AlertTriangle class="w-4 h-4 text-rose-400 shrink-0" />
      <span>{{ errorMsg }}</span>
    </div>

    <!-- Screen Preview Canvas / Image Stage -->
    <div class="flex-1 bg-zinc-950 flex flex-col items-center justify-center p-6 overflow-auto">
      <div v-if="currentImageData" class="flex flex-col items-center gap-3">
        <!-- Rendered Display Frame -->
        <div class="p-2.5 bg-zinc-900 border-2 border-zinc-700 rounded-xl shadow-2xl relative">
          <img
            :src="currentImageData"
            alt="LCD FrameBuffer Preview"
            class="rounded border border-zinc-800 object-contain max-h-[70vh] shadow-inner"
            :style="{
              imageRendering: 'pixelated',
              width: `${Math.min(fbWidth * 2, 800)}px`
            }"
          />
          <div class="absolute bottom-4 right-4 bg-black/75 px-2 py-0.5 rounded text-[10px] text-zinc-300 font-mono backdrop-blur border border-zinc-800">
            {{ fbWidth }} × {{ fbHeight }} | {{ pixelFormat.toUpperCase() }}
          </div>
        </div>

        <!-- Meta info -->
        <div class="text-[11px] text-zinc-500 font-mono flex items-center gap-4">
          <span>抓取帧数: <strong class="text-cyan-400">{{ capturedCount }}</strong></span>
          <span>更新时间: <strong class="text-zinc-300">{{ lastCaptureTime }}</strong></span>
          <span>显存地址: <strong class="text-emerald-400">{{ fbAddress }}</strong></span>
        </div>
      </div>

      <!-- Empty Guide Placeholder -->
      <div v-else class="text-center space-y-3 max-w-md text-zinc-500">
        <Monitor class="w-12 h-12 mx-auto text-zinc-700 animate-pulse" />
        <div class="text-sm font-semibold text-zinc-300">尚未捕获显存画面</div>
        <div class="text-[11px] text-zinc-500 leading-relaxed">
          通过 SWD 调试探针直接从目标单片机内存读取 FrameBuffer 显存像素数据并无损还原为画面，适用于 RTOS GUI (LVGL / TouchGFX / emWin / 裸机点阵) 在线远程监控与调试。
        </div>
      </div>
    </div>
  </div>
</template>
