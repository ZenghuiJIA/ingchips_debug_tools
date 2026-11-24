<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { check, type Update } from '@tauri-apps/plugin-updater';
import pkg from '../../package.json';
import { isTauri, safeInvoke } from '../utils/ipc';
import {
  UPDATER_AUTO_CHECK_KEY,
  UPDATER_AUTO_DOWNLOAD_KEY,
  readUpdaterPref,
  saveUpdaterPref,
  formatBytesMiB,
  formatUpdateError,
} from '../utils/updater';
import {
  RefreshCw,
  Download,
  ExternalLink,
  CheckCircle2,
  AlertTriangle,
  Sparkles,
  X,
} from '@lucide/vue';

type Phase = 'idle' | 'checking' | 'current' | 'available' | 'downloading' | 'ready' | 'installing';

const appVersion = pkg.version;
const open = ref(false);
const phase = ref<Phase>('idle');
const info = ref<{ version: string; notes?: string; date?: string } | null>(null);
const error = ref('');
const guardBlocked = ref('');
const received = ref(0);
const total = ref<number | undefined>(undefined);
const autoCheck = ref<boolean>(readUpdaterPref(UPDATER_AUTO_CHECK_KEY, true));
const autoDownload = ref<boolean>(readUpdaterPref(UPDATER_AUTO_DOWNLOAD_KEY, false));

let pendingUpdate: Update | null = null;
let working = false;
let mounted = true;
let checkedOnce = false;
let startupTimer: ReturnType<typeof setTimeout> | null = null;

async function releaseHandle() {
  const prev = pendingUpdate;
  pendingUpdate = null;
  if (prev) {
    await prev.close().catch(() => {});
  }
}

const isBusy = computed(
  () => phase.value === 'checking' || phase.value === 'downloading' || phase.value === 'installing'
);

const statusLabel = computed(() => {
  if (phase.value === 'ready') return '更新已就绪';
  if (phase.value === 'downloading') return '下载更新中';
  if (info.value) return `新版本 ${info.value.version}`;
  if (error.value) return '检查失败';
  return '检查更新';
});

const progressPct = computed(() => {
  if (!total.value || total.value <= 0) return 0;
  return Math.min(100, Math.round((received.value / total.value) * 100));
});

function toggleAutoCheck(e: Event) {
  const checked = (e.target as HTMLInputElement).checked;
  try {
    saveUpdaterPref(UPDATER_AUTO_CHECK_KEY, checked);
    autoCheck.value = checked;
  } catch (err) {
    error.value = `保存更新偏好失败: ${err}`;
  }
}

function toggleAutoDownload(e: Event) {
  const checked = (e.target as HTMLInputElement).checked;
  try {
    saveUpdaterPref(UPDATER_AUTO_DOWNLOAD_KEY, checked);
    autoDownload.value = checked;
  } catch (err) {
    error.value = `保存更新偏好失败: ${err}`;
  }
}

async function checkUpdate() {
  if (working || !isTauri()) return;
  checkedOnce = true;
  working = true;
  phase.value = 'checking';
  error.value = '';
  guardBlocked.value = '';
  info.value = null;
  let shouldDownload = false;
  try {
    await releaseHandle();
    const found = await check({ timeout: 30000 });
    if (!mounted) {
      if (found) await found.close().catch(() => {});
      return;
    }
    pendingUpdate = found;
    info.value = found ? { version: found.version, notes: found.body, date: found.date } : null;
    phase.value = found ? 'available' : 'current';
    shouldDownload = !!found && autoDownload.value;
  } catch (err) {
    if (mounted) {
      phase.value = 'idle';
      error.value = formatUpdateError(err);
    }
  } finally {
    working = false;
    if (!mounted) await releaseHandle();
  }
  if (shouldDownload && mounted) {
    await downloadUpdate();
  }
}

async function downloadUpdate() {
  if (working || !pendingUpdate) return;
  working = true;
  phase.value = 'downloading';
  error.value = '';
  received.value = 0;
  total.value = undefined;
  let bytes = 0;
  try {
    await pendingUpdate.download(
      (event) => {
        if (!mounted) return;
        if (event.event === 'Started') total.value = event.data.contentLength;
        if (event.event === 'Progress') {
          bytes += event.data.chunkLength;
          received.value = bytes;
        }
      },
      { timeout: 300000 }
    );
    if (mounted) {
      phase.value = 'ready';
      const guard = await safeInvoke<string | null>('check_update_install_guard').catch(() => null);
      guardBlocked.value = guard || '';
    }
  } catch (err) {
    if (mounted) {
      phase.value = 'available';
      error.value = formatUpdateError(err);
    }
  } finally {
    working = false;
    if (!mounted) await releaseHandle();
  }
}

async function installUpdate() {
  if (working || !pendingUpdate || phase.value !== 'ready') return;
  error.value = '';
  try {
    const reason = await safeInvoke<string | null>('check_update_install_guard');
    if (reason) {
      guardBlocked.value = reason;
      error.value = reason;
      return;
    }
    guardBlocked.value = '';
    working = true;
    phase.value = 'installing';
    await safeInvoke('prepare_for_update');
    await pendingUpdate.install({ restartAfterInstall: true });
  } catch (err) {
    if (mounted) {
      phase.value = 'ready';
      error.value = formatUpdateError(err);
    }
  } finally {
    working = false;
    if (!mounted) await releaseHandle();
  }
}

async function openReleasePage() {
  try {
    await safeInvoke('open_release_page');
  } catch (err) {
    error.value = formatUpdateError(err);
  }
}

onMounted(() => {
  mounted = true;
  if (autoCheck.value && isTauri()) {
    startupTimer = setTimeout(() => {
      if (!checkedOnce && mounted) void checkUpdate();
    }, 5000);
  }
});

onUnmounted(() => {
  mounted = false;
  if (startupTimer) {
    clearTimeout(startupTimer);
    startupTimer = null;
  }
  if (!working) {
    void releaseHandle();
  }
});
</script>

<template>
  <button
    type="button"
    @click="open = true"
    title="检查软件更新"
    class="flex items-center gap-1.5 px-2.5 py-1 rounded-md border text-[11px] font-mono transition-colors cursor-pointer"
    :class="
      info || phase === 'ready'
        ? 'bg-emerald-950/60 border-emerald-500/60 text-emerald-300 hover:bg-emerald-900/60'
        : 'bg-zinc-950 border-zinc-800 text-zinc-400 hover:text-zinc-200 hover:border-zinc-700'
    "
  >
    <Sparkles v-if="info || phase === 'ready'" class="w-3 h-3 text-emerald-400 animate-pulse" />
    <RefreshCw v-else-if="isBusy" class="w-3 h-3 text-cyan-400 animate-spin" />
    <span>v{{ appVersion }} · {{ statusLabel }}</span>
  </button>

  <Teleport to="body">
    <div
      v-if="open"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/65 backdrop-blur-xs p-4"
      @click.self="phase !== 'installing' && (open = false)"
    >
      <div class="bg-zinc-900 border border-zinc-700/80 rounded-xl shadow-2xl w-full max-w-lg overflow-hidden flex flex-col max-h-[85vh] text-xs text-zinc-200">
        <div class="flex items-center justify-between px-5 py-3.5 border-b border-zinc-800 bg-zinc-950/60">
          <div class="flex items-center gap-2">
            <Download class="w-4 h-4 text-emerald-400" />
            <h2 class="font-semibold text-sm text-zinc-100">软件更新</h2>
          </div>
          <button
            type="button"
            :disabled="phase === 'installing'"
            @click="open = false"
            class="p-1 rounded text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 disabled:opacity-40"
          >
            <X class="w-4 h-4" />
          </button>
        </div>

        <div class="p-5 overflow-y-auto space-y-4">
          <div class="flex items-center justify-between bg-zinc-950/70 border border-zinc-800 rounded-lg px-3.5 py-2.5 font-mono">
            <span>当前版本：v{{ appVersion }}</span>
            <span v-if="info" class="text-emerald-400 font-semibold">最新版本：v{{ info.version }}</span>
          </div>

          <div class="space-y-2">
            <label class="flex items-center gap-2 cursor-pointer select-none text-zinc-300">
              <input type="checkbox" :checked="autoCheck" @change="toggleAutoCheck" class="accent-emerald-500" />
              <span>启动时自动检查 GitHub Releases 更新</span>
            </label>
            <label class="flex items-center gap-2 cursor-pointer select-none text-zinc-300">
              <input type="checkbox" :checked="autoDownload" @change="toggleAutoDownload" class="accent-emerald-500" />
              <span>发现新版本后自动后台下载并校验签名</span>
            </label>
          </div>

          <div v-if="phase === 'checking'" role="status" class="flex items-center gap-2 text-cyan-300">
            <RefreshCw class="w-3.5 h-3.5 animate-spin" />
            <span>正在检查 GitHub Releases…</span>
          </div>

          <div v-if="phase === 'current'" role="status" class="flex items-center gap-2 text-emerald-400">
            <CheckCircle2 class="w-4 h-4" />
            <span>当前已是最新版本。</span>
          </div>

          <section v-if="info" class="border border-zinc-800 rounded-lg bg-zinc-950/80 p-3 space-y-1.5">
            <div class="flex items-center justify-between text-zinc-300 font-semibold">
              <span>v{{ info.version }} 发布说明</span>
              <span v-if="info.date" class="text-[11px] font-mono text-zinc-500">{{ info.date }}</span>
            </div>
            <pre class="whitespace-pre-wrap text-[11px] text-zinc-400 max-h-40 overflow-y-auto font-sans leading-relaxed">{{ info.notes || '此版本未提供发布说明。' }}</pre>
          </section>

          <div v-if="phase === 'downloading'" role="status" class="space-y-1.5">
            <div class="w-full h-2 bg-zinc-800 rounded-full overflow-hidden">
              <div
                class="h-full bg-emerald-500 transition-all duration-150"
                :style="{ width: total ? `${progressPct}%` : '40%' }"
              ></div>
            </div>
            <p class="text-[11px] text-zinc-400 font-mono">
              已下载 {{ formatBytesMiB(received) }}{{ total ? ` / ${formatBytesMiB(total)} (${progressPct}%)` : '' }}，完成后校验 Minisign 签名
            </p>
          </div>

          <div v-if="phase === 'ready'" role="status" class="p-3 rounded-lg bg-emerald-950/40 border border-emerald-700/60 text-emerald-300">
            更新包已下载并通过签名校验。安装前会自动释放串口、网络与后台守护进程，完成后重启应用。
          </div>

          <div v-if="phase === 'installing'" role="status" class="p-3 rounded-lg bg-cyan-950/40 border border-cyan-700/60 text-cyan-200">
            正在释放硬件会话并启动安装程序，请稍候…
          </div>

          <div v-if="guardBlocked" class="flex items-start gap-2 p-3 rounded-lg bg-amber-950/50 border border-amber-700/60 text-amber-200">
            <AlertTriangle class="w-4 h-4 shrink-0 mt-0.5 text-amber-400" />
            <span>{{ guardBlocked }}</span>
          </div>

          <pre v-if="error" role="alert" class="whitespace-pre-wrap p-3 rounded-lg bg-rose-950/50 border border-rose-800/70 text-rose-200 text-[11px] font-sans">{{ error }}</pre>
        </div>

        <div class="flex items-center justify-end gap-2 px-5 py-3.5 border-t border-zinc-800 bg-zinc-950/60">
          <button
            type="button"
            :disabled="isBusy || !isTauri()"
            @click="checkUpdate"
            class="px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-200 disabled:opacity-40 transition-colors"
          >
            检查更新
          </button>
          <button
            v-if="phase === 'available'"
            type="button"
            @click="downloadUpdate"
            class="px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white font-medium transition-colors"
          >
            下载更新
          </button>
          <button
            v-if="phase === 'ready'"
            type="button"
            :disabled="!!guardBlocked"
            @click="installUpdate"
            class="px-3 py-1.5 rounded-md bg-emerald-600 hover:bg-emerald-500 text-white font-medium disabled:opacity-40 transition-colors"
          >
            安装并重启
          </button>
          <button
            type="button"
            :disabled="phase === 'installing'"
            @click="openReleasePage"
            class="flex items-center gap-1 px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 disabled:opacity-40 transition-colors"
          >
            <ExternalLink class="w-3.5 h-3.5" />
            <span>GitHub 发布页</span>
          </button>
          <button
            type="button"
            :disabled="phase === 'installing'"
            @click="open = false"
            class="px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-300 disabled:opacity-40 transition-colors"
          >
            {{ phase === 'downloading' ? '后台下载' : '关闭' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>
