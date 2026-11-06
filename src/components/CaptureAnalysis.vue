<script setup lang="ts">
import { ref, computed, onUnmounted, watch, nextTick } from 'vue';
import { safeInvoke, isTauri } from '../utils/ipc';
import { normalizeEvent, statistics, parseSamplesCsv, samplesCsv, extremaDecimation, compareRuns, type Sample, type TimelineEvent } from '../utils/captureAnalysis';
import { exampleProtocol, type ProtocolFrame } from '../utils/protocol';
import EmbeddedDebugPanel from './EmbeddedDebugPanel.vue';
const emit = defineEmits<{ (event: 'close'): void }>();
const embeddedDebugOpen = ref(false);
const props = defineProps<{ initialPath?: string }>();
const path = ref(props.initialPath || ''); const protocolText = ref(JSON.stringify(exampleProtocol, null, 2));
const rawEvents = ref<Record<string, unknown>[]>([]); const events = ref<TimelineEvent[]>([]); const samples = ref<Sample[]>([]); const comparison = ref<Sample[]>([]);
const message = ref('离线分析，不连接设备'); const busy = ref(false); const from = ref(0); const to = ref(1000); const position = ref(0); const speed = ref(1); const playing = ref(false);
const anchorA = ref(0); const anchorB = ref(0); const pluginPath = ref(''); const selectedEvent = ref<TimelineEvent | null>(null);
const selectedChannel = ref(''); const canvas = ref<HTMLCanvasElement | null>(null);
const channels = computed(() => [...new Set(samples.value.map(s => s.channel))]);
const stats = computed(() => { try { return statistics(samples.value, from.value, to.value); } catch { return []; } });
const differences = computed(() => { try { return compareRuns(samples.value, comparison.value, from.value, to.value, anchorA.value, anchorB.value); } catch { return []; } });
const timeline = computed(() => events.value.filter(e => e.t >= from.value && e.t <= Math.min(to.value, position.value)).slice(-300));
let timer: ReturnType<typeof setInterval> | undefined; let lastTick = 0;
let selectionStart: number | null = null;
function selectStart(event: MouseEvent) {
  if (!event.shiftKey || !canvas.value) return;
  const rect = canvas.value.getBoundingClientRect();
  selectionStart = from.value + Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width))*(to.value-from.value);
  stop();
}
function selectEnd(event: MouseEvent) {
  if (selectionStart === null || !canvas.value) return;
  const rect = canvas.value.getBoundingClientRect();
  const end = from.value + Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width))*(to.value-from.value);
  const start = selectionStart; selectionStart = null;
  from.value = Math.min(start,end); to.value = Math.max(start,end); position.value = to.value;
}
function stop() { playing.value = false; if (timer) clearInterval(timer); timer = undefined; }
function play() {
  if (playing.value) { stop(); return; }
  if (position.value >= to.value) position.value = from.value;
  playing.value = true; lastTick = performance.now();
  timer = setInterval(() => { const now = performance.now(); position.value = Math.min(to.value, position.value + (now - lastTick) * speed.value); lastTick = now; if (position.value >= to.value) stop(); }, 30);
}
function range() {
  const times = [...events.value.map(e => e.t), ...samples.value.map(s => s.t)];
  from.value = times.length ? times.reduce((a,b) => Math.min(a,b), Infinity) : 0;
  to.value = times.length ? times.reduce((a,b) => Math.max(a,b), 0) : 1000; position.value = to.value;
  selectedChannel.value = channels.value[0] || ''; nextTick(draw);
}
async function pick() { const selected = await safeInvoke<string | null>('capture_pick_file'); if (selected) path.value = selected; }
async function load() {
  if (busy.value) return; stop(); busy.value = true;
  try {
    if (!isTauri()) throw new Error('需要桌面后端读取记录');
    events.value = []; rawEvents.value = []; samples.value = []; selectedEvent.value = null;
    if (/\.csv$/i.test(path.value)) samples.value = parseSamplesCsv(await safeInvoke<string>('capture_read_csv', { path: path.value }));
    else {
      let cursor = 0; const all: Record<string, unknown>[] = []; const warnings: string[] = []; let bytes = 0;
      while (true) {
        const page = await safeInvoke<{ events: Record<string, unknown>[]; cursor: number; eof: boolean; warnings: string[] }>('capture_read_file', { path: path.value, after: cursor, limit: 1000 });
        all.push(...page.events); warnings.push(...page.warnings); bytes += JSON.stringify(page.events).length;
        if (all.length > 200000 || bytes > 64 * 1024 * 1024) throw new Error('预览超过 20 万事件 / 64 MiB，请选择较小分卷');
        cursor = page.cursor; if (page.eof) break;
      }
      rawEvents.value = all; events.value = all.map(normalizeEvent); message.value = warnings.join('\n') || `已读取 ${all.length} 个事件`;
    }
    range();
  } catch (error) { message.value = String(error); }
  finally { busy.value = false; }
}
async function decode() {
  busy.value = true; stop();
  try {
    const result = await safeInvoke<{ frames: { session_id: string; seq: number; elapsed_ms: number; frame: ProtocolFrame }[] }>('protocol_replay', { protocol: JSON.parse(protocolText.value), events: rawEvents.value });
    const next: Sample[] = []; let invalid = 0;
    for (const item of result.frames) {
      if (!item.frame.valid) { invalid++; continue; }
      for (const [channel, value] of Object.entries(item.frame.fields)) if (typeof value === 'number' && Number.isFinite(value)) next.push({ t: item.elapsed_ms, channel, value, source: item.seq, session: item.session_id });
    }
    samples.value = next; range(); message.value = `离线重解析完成：${next.length} 个数值，${invalid} 个错误帧。时间为主机接收时间，非设备采样时间。`;
  } catch (error) { message.value = String(error); }
  finally { busy.value = false; }
}
async function runPlugin() {
  busy.value = true;
  try {
    const result = await safeInvoke<{ samples: Sample[]; annotations: { message: string }[]; plugin_sha256: string }>('protocol_plugin_analyze', { pluginPath: pluginPath.value, payload: { events: rawEvents.value }, timeoutMs: 5000 });
    samples.value = result.samples; range(); message.value = '可信本地插件离线分析，未验证硬件。SHA256: ' + result.plugin_sha256 + '\n' + result.annotations.map(a => a.message).join('\n');
  } catch (error) { message.value = String(error); }
  finally { busy.value = false; }
}
async function loadComparison() {
  try { const file = await safeInvoke<string | null>('capture_pick_file'); if (file) { comparison.value = parseSamplesCsv(await safeInvoke<string>('capture_read_csv', { path: file })); message.value = '已加载比较运行；设置两个锚点后比较区间统计，不自动插值'; } }
  catch (error) { message.value = String(error); }
}
function exportCsv() {
  const url = URL.createObjectURL(new Blob([samplesCsv(samples.value)], { type: 'text/csv' })); const a = document.createElement('a'); a.href = url; a.download = 'capture-analysis.csv'; a.click(); URL.revokeObjectURL(url);
}
function draw() {
  const c = canvas.value, context = c?.getContext('2d'); if (!c || !context) return;
  c.width = Math.max(500, c.clientWidth); c.height = 200; context.clearRect(0,0,c.width,c.height);
  const points = samples.value.filter(s => s.channel === selectedChannel.value && s.t >= from.value && s.t <= Math.min(to.value, position.value));
  if (!points.length) return;
  const minimum = points.reduce((v,p) => Math.min(v,p.value), Infinity), maximum = points.reduce((v,p) => Math.max(v,p.value), -Infinity);
  const reduced = extremaDecimation(points, Math.floor(c.width / 2)); context.strokeStyle = '#34d399'; context.beginPath();
  reduced.forEach((p,i) => { const x = 10 + (p.t - from.value) / Math.max(1, to.value - from.value) * (c.width-20); const y = 190 - (p.value-minimum) / Math.max(1e-9, maximum-minimum) * 180; if (!i || p.session !== reduced[i-1]?.session) context.moveTo(x,y); else context.lineTo(x,y); }); context.stroke();
}
function pickPoint(event: MouseEvent) {
  const rect = canvas.value!.getBoundingClientRect(); const t = from.value + (event.clientX - rect.left) / rect.width * (to.value-from.value);
  let closest: Sample | undefined;
  for (const point of samples.value) if (point.channel === selectedChannel.value && (!closest || Math.abs(point.t-t) < Math.abs(closest.t-t))) closest = point;
  if (closest) { position.value = closest.t; selectedEvent.value = events.value.find(e => e.seq === closest!.source && (!closest!.session || e.session === closest!.session)) || null; }
}
watch([samples, from, to, position, selectedChannel], () => nextTick(draw));
onUnmounted(stop);
</script>
<template>
  <div class="absolute inset-3 z-40 bg-zinc-950 border border-zinc-600 rounded shadow-xl flex flex-col text-xs text-zinc-200">
    <div class="flex items-center gap-3 p-3 border-b border-zinc-800"><strong class="text-amber-300">离线记录分析 / 回放 · 不操作设备</strong><button @click="embeddedDebugOpen = true" class="px-2 py-1 bg-sky-900 rounded">嵌入式分析</button><button class="ml-auto" @click="emit('close')">关闭</button></div>
    <EmbeddedDebugPanel v-if="embeddedDebugOpen" @close="embeddedDebugOpen = false" />
    <div class="p-3 overflow-auto flex-1 space-y-3">
      <div class="flex gap-2"><input v-model="path" placeholder="JSONL 文件、分卷目录或时间戳 CSV" class="flex-1 bg-zinc-900 border border-zinc-700 p-2 select-text" /><button @click="pick">浏览</button><button @click="load" :disabled="busy">加载</button></div>
      <details><summary>用协议模板重新解析</summary><textarea v-model="protocolText" rows="8" class="w-full bg-zinc-900 font-mono p-2" /><button @click="decode" :disabled="busy || !rawEvents.length" class="bg-emerald-900 px-3 py-1 rounded">重新解析（保留原始记录）</button></details>
      <details><summary>可信本地 Python 插件（独立进程，非安全沙箱）</summary><div class="flex gap-2"><input v-model="pluginPath" placeholder="C:/project/decoder.py，需定义 decode(payload)" class="flex-1 bg-zinc-900 p-2" /><button @click="runPlugin" :disabled="busy || !rawEvents.length">运行离线解析</button></div></details>
      <pre class="text-amber-300 whitespace-pre-wrap select-text">{{ message }}</pre>
      <div class="flex flex-wrap items-center gap-3"><label>起点 ms <input type="number" v-model.number="from" class="w-24 bg-zinc-900" /></label><label>终点 ms <input type="number" v-model.number="to" class="w-24 bg-zinc-900" /></label><select v-model="selectedChannel" class="bg-zinc-900"><option v-for="channel in channels" :key="channel">{{ channel }}</option></select><button @click="play">{{ playing ? '暂停播放' : '播放' }}</button><select v-model.number="speed" class="bg-zinc-900"><option :value="0.5">0.5×</option><option :value="1">1×</option><option :value="10">10×</option></select><button @click="exportCsv" :disabled="!samples.length">导出时间戳 CSV</button></div>
      <input type="range" :min="from" :max="Math.max(from + 1, to)" v-model.number="position" class="w-full" /><span>{{ position.toFixed(1) }} ms</span>
      <p class="text-zinc-400">Shift 拖动选择统计区间；点击曲线定位原始帧。统计使用未降采样数据。</p>
      <canvas ref="canvas" class="w-full h-[200px] bg-zinc-900 cursor-crosshair" @click="!$event.shiftKey && pickPoint($event)" @mousedown="selectStart" @mouseup="selectEnd" @mouseleave="selectionStart = null" />
      <table class="w-full text-left"><thead><tr><th>通道 / 会话</th><th>样本数</th><th>最小</th><th>最大</th><th>均值</th><th>总体标准差</th><th>峰峰值</th></tr></thead><tbody><tr v-for="row in stats" :key="row.channel"><td>{{ row.channel }}</td><td>{{ row.count }}</td><td>{{ row.min }}</td><td>{{ row.max }}</td><td>{{ row.mean.toFixed(4) }}</td><td>{{ row.stddev.toFixed(4) }}</td><td>{{ row.peakToPeak }}</td></tr></tbody></table>
      <details><summary>比较另一轮记录</summary><button @click="loadComparison">加载第二轮时间戳 CSV</button><label class="ml-3">本轮锚点 <input type="number" v-model.number="anchorA" class="w-24 bg-zinc-900" /></label><label class="ml-3">第二轮锚点 <input type="number" v-model.number="anchorB" class="w-24 bg-zinc-900" /></label><pre class="whitespace-pre-wrap">{{ differences }}</pre></details>
      <div class="grid grid-cols-2 gap-3"><div class="max-h-48 overflow-auto border border-zinc-800"><button v-for="event in timeline" :key="event.session + ':' + event.seq" @click="selectedEvent = event" class="block w-full text-left px-2 py-1 hover:bg-zinc-800 truncate">{{ event.t.toFixed(1) }} ms [{{ event.port }}] {{ event.direction }} {{ event.message }} {{ event.data.slice(0,60) }}</button></div><pre class="max-h-48 overflow-auto bg-zinc-900 p-2 whitespace-pre-wrap break-all select-text">{{ selectedEvent || '点击事件或波形点查看原始数据和来源' }}</pre></div>
    </div>
  </div>
</template>
