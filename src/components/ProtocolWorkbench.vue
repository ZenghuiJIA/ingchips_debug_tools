<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue';
import { listen, type UnlistenFn } from '@tauri-apps/api/event';
import { safeInvoke, isTauri } from '../utils/ipc';
import { serialIdentity } from '../utils/serialSession';
import { exampleProtocol, protocolHilDocument, type ProtocolSpec, type ProtocolFrame } from '../utils/protocol';
const props = defineProps<{ portName: string; baudRate?: number; isConnected: boolean }>();
const spec = ref<ProtocolSpec>(JSON.parse(JSON.stringify(exampleProtocol)));
const source = ref(''); const values = ref('{"seq":1,"value":0,"status":0}'); const expected = ref('{"seq":1,"status":0}');
const timeoutMs = ref(1000); const preview = ref(''); const message = ref(''); const busy = ref(false);
const frames = ref<(ProtocolFrame & { stamp: number; session: string })[]>([]);
const selected = ref<ProtocolFrame | null>(null); const selectedField = ref('');
const identity = ref<string | null>(null); let unsubscribe: UnlistenFn | undefined;
const activeRequest = ref<{ portName: string; sessionId: string; requestId: string } | null>(null);
async function cancelRequest() {
  if (!activeRequest.value) return;
  try { await safeInvoke('protocol_cancel', { ...activeRequest.value }); message.value = '已请求停止，等待后端释放事务'; }
  catch (error) { message.value = String(error); }
}
const bytes = computed(() => selected.value?.data.match(/.{2}/g) || []);
const selectedRange = computed(() => {
  const field = spec.value.fields.find(f => f.name === selectedField.value);
  if (!field) return [-1, -1];
  const width = field.size || ({ uint8: 1, int8: 1, bool: 1, uint16: 2, int16: 2, uint32: 4, int32: 4, float32: 4, float64: 8 } as Record<string, number>)[field.type] || 1;
  return [field.offset, field.offset + width];
});
function parsed(text: string): Record<string, unknown> { const value = JSON.parse(text); if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error('参数必须为 JSON 对象'); return value; }
function save() { localStorage.setItem('hil.protocol.' + props.portName, JSON.stringify(spec.value)); source.value = JSON.stringify(spec.value, null, 2); }
async function encode() {
  try {
    if (!isTauri()) throw new Error('浏览器预览不具备原生协议后端');
    const result = await safeInvoke<{ hex: string }>('protocol_encode', { protocol: spec.value, values: parsed(values.value) });
    preview.value = result.hex.match(/.{2}/g)?.join(' ') || ''; message.value = '编码已校验；尚未发送'; save();
  } catch (error) { message.value = String(error); }
}
async function applySource() { try { const p = JSON.parse(source.value); if (p.schema_version !== 1 || !Array.isArray(p.fields)) throw new Error('不是 v1 协议模板'); spec.value = p; await encode(); } catch (error) { message.value = String(error); } }
async function configure() {
  try {
    identity.value = await serialIdentity(props.portName);
    await safeInvoke('protocol_configure', { portName: props.portName, protocol: spec.value });
    message.value = '当前会话已绑定协议；后续 RX 会进入帧列表'; save();
  } catch (error) { message.value = String(error); }
}
async function request() {
  if (busy.value) return; busy.value = true;
  try {
    const snapshot = JSON.parse(JSON.stringify(spec.value)); const v = parsed(values.value); const e = parsed(expected.value);
    const sessionId = await serialIdentity(props.portName); if (!sessionId) throw new Error('请求应答目前需要串口或 RTT 会话');
    message.value = '正在发送并等待对应应答…';
    activeRequest.value = { portName: props.portName, sessionId, requestId: crypto.randomUUID() };
    const result = await safeInvoke<{ duration_ms: number; frame: ProtocolFrame }>('protocol_request', { ...activeRequest.value, protocol: snapshot, values: v, expected: e, timeoutMs: timeoutMs.value });
    selected.value = result.frame; message.value = `应答完成，${result.duration_ms} ms`;
  } catch (error) { message.value = String(error); }
  finally { busy.value = false; activeRequest.value = null; }
}
function download(name: string, object: unknown) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(object, null, 2)], { type: 'application/json' }));
  const link = document.createElement('a'); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url);
}
function exportHil() {
  try { download('protocol-request.hiltest', protocolHilDocument(props.portName, props.baudRate || 115200, spec.value, parsed(values.value), parsed(expected.value), timeoutMs.value)); }
  catch (error) { message.value = String(error); }
}
function nextSequence() {
  try {
    const v = parsed(values.value), e = parsed(expected.value);
    if (typeof v.seq !== 'number' || !Number.isInteger(v.seq) || v.seq >= 255) throw new Error('示例 seq 必须为 0..254；其他序列字段请手动调整');
    v.seq++; e.seq = v.seq; values.value = JSON.stringify(v); expected.value = JSON.stringify(e);
  } catch (error) { message.value = String(error); }
}
onMounted(async () => {
  try { const stored = localStorage.getItem('hil.protocol.' + props.portName); if (stored) spec.value = JSON.parse(stored); } catch { /* invalid profile */ }
  source.value = JSON.stringify(spec.value, null, 2);
  if (isTauri()) unsubscribe = await listen<{ port: string; session_id: string; timestamp_ms: number; frames: ProtocolFrame[] }>('protocol-frames', ({ payload }) => {
    if (payload.port !== props.portName || (identity.value && payload.session_id !== identity.value)) return;
    frames.value = [...frames.value, ...payload.frames.map(f => ({ ...f, stamp: payload.timestamp_ms, session: payload.session_id }))].slice(-500);
  });
});
onUnmounted(() => unsubscribe?.());
watch(() => [props.portName, props.isConnected], () => { identity.value = null; frames.value = []; selected.value = null; });
</script>
<template>
  <div class="p-3 space-y-3 overflow-auto text-xs h-full">
    <div class="text-emerald-300 font-semibold">共用协议工作台 · 手动 / HIL 同一编码器</div>
    <input v-model="spec.name" class="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1" />
    <div class="flex gap-2"><label>帧长 <input type="number" v-model.number="spec.fixed_length" min="1" class="w-16 bg-zinc-950 border border-zinc-700" /></label><select v-model="spec.endian" class="bg-zinc-950 border border-zinc-700"><option value="little">小端</option><option value="big">大端</option></select></div>
    <table class="w-full text-left"><thead><tr><th>字段</th><th>偏移</th><th>类型</th></tr></thead><tbody><tr v-for="f in spec.fields" :key="f.name"><td><input v-model="f.name" class="w-24 bg-zinc-950" /></td><td><input type="number" v-model.number="f.offset" class="w-12 bg-zinc-950" /></td><td><select v-model="f.type" class="bg-zinc-950"><option v-for="type in ['uint8','int8','uint16','int16','uint32','int32','float32','float64','bool','bytes','string']" :key="type">{{ type }}</option></select></td></tr></tbody></table>
    <details><summary class="cursor-pointer text-sky-300">完整协议模板（长度字段、位域、校验范围）</summary><textarea v-model="source" rows="12" class="w-full bg-zinc-950 font-mono p-2 select-text" /><button @click="applySource" class="px-2 py-1 bg-zinc-800 rounded">加载并校验</button></details>
    <label class="block">发送字段值<textarea v-model="values" rows="2" class="w-full bg-zinc-950 p-2 font-mono" /></label>
    <label class="block">期望应答字段（序列号 / 命令码 / 状态）<textarea v-model="expected" rows="2" class="w-full bg-zinc-950 p-2 font-mono" /></label>
    <label>超时 ms <input type="number" min="1" max="30000" v-model.number="timeoutMs" class="w-20 bg-zinc-950 border border-zinc-700" /></label>
    <button @click="nextSequence" :disabled="busy" class="ml-2 text-sky-300">示例 seq +1</button>
    <button v-if="busy" @click="cancelRequest" class="ml-2 text-rose-400">停止当前请求</button>
    <p class="text-zinc-400">每次请求使用新的序列号；重复应答身份会被拒绝，避免迟到响应误匹配。超时后需重新连接。</p>
    <div class="flex flex-wrap gap-2"><button @click="encode" class="px-2 py-1 bg-zinc-800 rounded">预览编码</button><button @click="configure" :disabled="!isConnected || busy" class="px-2 py-1 bg-sky-900 rounded disabled:opacity-40">绑定接收解析</button><button @click="request" :disabled="!isConnected || busy" class="px-2 py-1 bg-emerald-900 rounded disabled:opacity-40">{{ busy ? '等待应答…' : '发送并检查应答' }}</button><button @click="download('protocol.json', spec)" class="px-2 py-1 bg-zinc-800 rounded">导出协议</button><button @click="exportHil" class="px-2 py-1 bg-zinc-800 rounded">导出 HIL 步骤</button></div>
    <pre class="whitespace-pre-wrap break-all select-text bg-zinc-950 p-2">{{ preview || '预览不会向设备发送数据' }}</pre>
    <p class="text-amber-300 break-all">{{ message }}</p>
    <div class="max-h-40 overflow-auto border border-zinc-800"><button v-for="(f,i) in frames" :key="i" @click="selected = f" class="block w-full text-left px-2 py-1 hover:bg-zinc-800 truncate" :class="f.valid ? 'text-emerald-300' : 'text-rose-400'">{{ new Date(f.stamp).toLocaleTimeString() }} {{ f.valid ? 'OK' : f.error }} · {{ f.data }}</button></div>
    <div v-if="selected" class="space-y-2"><div class="flex flex-wrap gap-1 font-mono select-text"><span v-for="(byte,i) in bytes" :key="i" :class="i >= selectedRange[0]! && i < selectedRange[1]! ? 'bg-amber-700' : 'bg-zinc-800'" class="px-1">{{ byte }}</span></div><button v-for="(value,key) in selected.fields" :key="key" @click="selectedField = String(key)" class="block w-full text-left">{{ key }} = {{ value }} {{ selected.labels[key] || '' }}</button><p class="text-rose-400">{{ selected.error }}</p></div>
  </div>
</template>
