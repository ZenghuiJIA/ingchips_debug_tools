<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { safeInvoke, isTauri } from '../utils/ipc';
import { t } from '../utils/i18n';
import { hilCall, displayReport, isHilSubmissionRejected, type HilStatus, type HilEvent, type HilReport } from '../utils/hilClient';
import { normalizePipeline, pipelineSnapshot, HilRunGeneration } from '../utils/hilPlan';
import type {
  HilTestPipeline,
  HilTestStep,
  HilStepAction,
  HilStepResult,
  HilExecutionReport,
  PortInfo,
  ProbeInfo
} from '../types';
import {
  Play,
  Square,
  Plus,
  Trash2,
  FileCode,
  Download,
  ArrowUp,
  ArrowDown,
  RotateCcw,
  Zap,
  Cpu,
  Terminal,
  Activity,
  Sliders,
  Clock,
  CheckCircle2,
  XCircle,
  FolderOpen
} from '@lucide/vue';
import ResizableDrawer from './common/ResizableDrawer.vue';

// Available action templates for the palette
const actionTemplates: Array<{
  action: HilStepAction;
  nameKey: string;
  descKey: string;
  icon: any;
  color: string;
  defaultParams: any;
}> = [
  { action: 'serial_open', nameKey: '打开串口采集', descKey: '在烧录和复位前持续采集日志', icon: Terminal,
    color: 'text-cyan-400', defaultParams: { port_name: '', baud_rate: 115200 } },
  { action: 'hil_observe', nameKey: 'HILv1 自测观察', descKey: '同时检查 BOOT、HB、RESULT 与 DONE', icon: Activity,
    color: 'text-emerald-400', defaultParams: { port_name: '', baud_rate: 115200, timeout_ms: 1800000, boot_timeout_ms: 10000, idle_timeout_ms: 15000, boot_count: 1, continue_on_failure: true } },
  {
    action: 'flash_firmware',
    nameKey: 'seq_act_flash',
    descKey: 'seq_act_flash_desc',
    icon: Zap,
    color: 'text-amber-400 border-amber-800/40 bg-amber-950/20',
    defaultParams: {
      flash_type: 'pyocd',
      file_path: '',
      baud_rate: 921600,
      target_device: '',
      single_addr: '0x02002000',
      probe_id: ''
    }
  },
  {
    action: 'reset_target',
    nameKey: 'seq_act_reset',
    descKey: 'seq_act_reset_desc',
    icon: RotateCcw,
    color: 'text-rose-400 border-rose-800/40 bg-rose-950/20',
    defaultParams: {
      reset_method: 'swd_soft_reset',
      pulse_ms: 100,
      port_name: '',
      probe_id: ''
    }
  },
  {
    action: 'serial_send',
    nameKey: 'seq_act_serial_send',
    descKey: 'seq_act_serial_send_desc',
    icon: Terminal,
    color: 'text-emerald-400 border-emerald-800/40 bg-emerald-950/20',
    defaultParams: {
      port_name: '',
      baud_rate: 115200,
      send_data: 'AT+PING',
      send_format: 'string',
      send_ending: 'crlf',
      character_delay_ms: 0
    }
  },
  {
    action: 'serial_wait_match',
    nameKey: 'seq_act_serial_match',
    descKey: 'seq_act_serial_match_desc',
    icon: Activity,
    color: 'text-cyan-400 border-cyan-800/40 bg-cyan-950/20',
    defaultParams: {
      port_name: '',
      baud_rate: 115200,
      match_type: 'contains',
      pattern: 'OK',
      timeout_ms: 3000
    }
  },
  {
    action: 'swd_read_assert',
    nameKey: 'seq_act_swd_assert',
    descKey: 'seq_act_swd_assert_desc',
    icon: Cpu,
    color: 'text-indigo-400 border-indigo-800/40 bg-indigo-950/20',
    defaultParams: {
      probe_id: '',
      memory_addr: '0x20000000',
      read_width: 32,
      operator: '==',
      expected_value: '0x00000000',
      timeout_ms: 2000
    }
  },
  {
    action: 'svd_check_reg',
    nameKey: 'seq_act_svd_reg',
    descKey: 'seq_act_svd_reg_desc',
    icon: Sliders,
    color: 'text-purple-400 border-purple-800/40 bg-purple-950/20',
    defaultParams: {
      probe_id: '',
      peripheral: 'UART0',
      register: 'LSR',
      field_name: '',
      operator: '==',
      expected_reg_val: '0x60',
      timeout_ms: 2000
    }
  },
  {
    action: 'delay',
    nameKey: 'seq_act_delay',
    descKey: 'seq_act_delay_desc',
    icon: Clock,
    color: 'text-blue-400 border-blue-800/40 bg-blue-950/20',
    defaultParams: {
      delay_ms: 500
    }
  }
];

// Current pipeline state
const pipeline = ref<HilTestPipeline>({
  schema_version: 2,
  bench: {},
  name: 'HIL_Regression_Pipeline_v1',
  version: '1.2.2',
  description: 'Automated Hardware-in-the-Loop test suite',
  loop_count: 1,
  stop_on_error: true,
  steps: []
});

// Available system serial ports & SWD probes
const availablePorts = ref<PortInfo[]>([]);
const availableProbes = ref<ProbeInfo[]>([]);
const isScanningProbes = ref<boolean>(false);
const baudPresets = [9600, 115200, 230400, 460800, 921600, 1000000, 1152000, 1500000];

function formatProbeLabel(p: ProbeInfo): string {
  const typeLabel = p.probe_type === 'jlink' || p.description.toLowerCase().includes('jlink') || p.description.toLowerCase().includes('j-link')
    ? '🔗 [J-Link]' : (p.probe_type === 'daplink' || p.description.toLowerCase().includes('dap') || p.description.toLowerCase().includes('cmsis')
    ? '⚡ [CMSIS-DAP]' : '🔌 [Probe]');
  return `${typeLabel} ${p.product_name || p.description} (SN: ${p.unique_id})`;
}

async function refreshProbes() {
  isScanningProbes.value = true;
  try {
    const list: ProbeInfo[] = await safeInvoke('pyocd_list_probes');
    availableProbes.value = list;
  } catch (e) {
    console.warn('Failed to load probes in sequencer:', e);
  } finally {
    isScanningProbes.value = false;
  }
}

// Execution state
const isRunning = ref<boolean>(false);
const isSubmitting = ref(false);
const isStopping = ref(false);
const currentLoopIndex = ref<number>(0);
const stepResults = ref<Record<string, HilStepResult>>({});
const runnerLogs = ref<Array<{ id: number; time: string; text: string; status: 'info' | 'success' | 'error' | 'warn' }>>([]);
let nextLogId = 1;


// Report Modal
const isReportModalOpen = ref<boolean>(false);
const executionReport = ref<HilExecutionReport | null>(null);


// Active selected step for property editing
const selectedStepId = ref<string | null>(null);
const selectedStep = computed(() => pipeline.value.steps.find(step => step.id === selectedStepId.value) || null);
function ensurePinReset(step: HilTestStep) {
  // Only an explicit user change creates pin-reset settings; selection/import is read-only.
  if (step.params.reset_method !== 'swd_soft_reset' && !step.params.pin_reset) {
    step.params.pin_reset = { profile_id: '', wiring_verified: false, reset_asserted_dtr: true, boot_asserted_rts: true, settle_ms: 50, pulse_ms: 100, boot_hold_ms: 50 };
  }
}
const sourceVisible = ref(false);
const sourceText = ref('');
const sourceError = ref('');
const sourceApplying = ref(false);
const importError = ref('');
const isImporting = ref(false);
function editSource() {
  sourceText.value = JSON.stringify(pipeline.value, null, 2);
  sourceError.value = '';
  sourceVisible.value = true;
}
async function applySource() {
  if (sourceApplying.value) return;
  sourceApplying.value = true;
  sourceError.value = '';
  try {
    const normalized = normalizePipeline(JSON.parse(sourceText.value));
    await hilCall('validate_hiltest', { document: normalized });
    pipeline.value = normalized;
    selectedStepId.value = normalized.steps[0]?.id || null;
    sourceVisible.value = false;
    addLog('脚本已校验并加载；参数、嵌套与旧版语义保留，当前运行不受影响', 'success');
  } catch (err) {
    sourceError.value = '脚本未应用: ' + String(err);
    addLog(sourceError.value, 'error');
  } finally { sourceApplying.value = false; }
}

async function importPipelineText(text: string) {
  if (isImporting.value) return;
  isImporting.value = true;
  importError.value = '';
  try {
    const normalized = normalizePipeline(JSON.parse(text));
    await hilCall('validate_hiltest', { document: normalized });
    pipeline.value = normalized;
    selectedStepId.value = normalized.steps[0]?.id || null;
    addLog('已校验并导入工程: ' + normalized.name + '；运行中任务仍使用原快照', 'success');
  } catch (err) {
    importError.value = '工程未导入: ' + String(err);
    addLog(importError.value, 'error');
  } finally { isImporting.value = false; }
}

function addLog(text: string, status: 'info' | 'success' | 'error' | 'warn' = 'info') {
  const time = new Date().toTimeString().split(' ')[0] + '.' + new Date().getMilliseconds().toString().padStart(3, '0');
  runnerLogs.value.unshift({ id: nextLogId++, time, text, status });
  if (runnerLogs.value.length > 500) runnerLogs.value.pop();
}

function clearLogs() {
  runnerLogs.value = [];
}

async function refreshPorts() {
  try {
    const list: PortInfo[] = await safeInvoke('list_serial_ports');
    availablePorts.value = list;
  } catch (e) {
    console.warn('Failed to load ports in sequencer:', e);
  }
}

// Add a step from template
function addStepFromTemplate(tmpl: typeof actionTemplates[0]) {
  const newId = `step_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
  const initialParams = JSON.parse(JSON.stringify(tmpl.defaultParams));

  const step: HilTestStep = {
    id: newId,
    name: t(tmpl.nameKey),
    action: tmpl.action,
    enabled: true,
    params: initialParams,
    timeout_ms: initialParams.timeout_ms || (tmpl.action === 'flash_firmware' ? 300000 : 3000),
    on_failure: 'abort',
    retry_count: 0
  };

  pipeline.value.steps.push(step);
  selectedStepId.value = newId;
  addLog(`添加测试步骤: [${step.name}] (${step.action})`, 'info');
}

function removeStep(index: number) {
  const removed = pipeline.value.steps.splice(index, 1)[0];
  if (selectedStepId.value === removed.id) {
    selectedStepId.value = pipeline.value.steps[0]?.id || null;
  }
}

function moveStepUp(index: number) {
  if (index <= 0) return;
  const temp = pipeline.value.steps[index];
  pipeline.value.steps[index] = pipeline.value.steps[index - 1];
  pipeline.value.steps[index - 1] = temp;
}

function moveStepDown(index: number) {
  if (index >= pipeline.value.steps.length - 1) return;
  const temp = pipeline.value.steps[index];
  pipeline.value.steps[index] = pipeline.value.steps[index + 1];
  pipeline.value.steps[index + 1] = temp;
}

function toggleStepEnabled(step: HilTestStep) {
  step.enabled = !step.enabled;
}

// Pick Firmware File helper
async function pickStepFirmware(step: HilTestStep) {
  try {
    const selected: string | null = await safeInvoke('pick_firmware_file', {
      title: '选择测试固件文件 (.bin / .hex / .elf / .ini)'
    });
    if (selected) {
      step.params.file_path = selected;
    }
  } catch (err: any) {
    addLog(`文件选择失败: ${err}`, 'error');
  }
}

// Open / Save Pipeline Project (.hiltest)
function savePipelineToFile() {
  const data = JSON.stringify(pipeline.value, null, 2);
  const blob = new Blob([data], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${pipeline.value.name.replace(/[^a-zA-Z0-9_-]/g, '_')}.hiltest`;
  a.click();
  URL.revokeObjectURL(url);
  addLog(`工程已成功导出为 ${a.download}`, 'success');
}

function openPipelineFromFile() {
  if (isImporting.value) return;
  importError.value = '';
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = '.hiltest,.json';
  input.onchange = () => {
    const file = input.files?.[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) { importError.value = '工程未导入：文件超过 2 MiB 编辑器上限'; return; }
    const reader = new FileReader();
    reader.onload = () => { void importPipelineText(String(reader.result ?? '')); };
    reader.onerror = () => { importError.value = '工程文件读取失败: ' + String(reader.error); addLog(importError.value, 'error'); };
    reader.onabort = () => { importError.value = '工程文件读取已取消'; };
    reader.readAsText(file);
  };
  input.click();
}

// The backend owns execution; edits affect only the next submitted snapshot.
const runId = ref(sessionStorage.getItem('hil.activeRun') || '');
const runState = ref('');
const cancellationDetail = ref('');
const reportDir = ref('');
const activeStepId = ref('');
const runGeneration = new HilRunGeneration();
let eventCursor = 0;
let pollTimer: ReturnType<typeof setTimeout> | undefined;
let disposed = false;
const serialViews = new Map<string, TextDecoder>();
// Restore the guard synchronously, before mounted device enumeration can yield.
if (runId.value) {
  isRunning.value = true;
  runState.value = 'UNKNOWN';
  cancellationDetail.value = '正在恢复已记录任务状态；尚未确认任务结束。';
}
if (sessionStorage.getItem('hil.submissionUnknown') === 'true' && !runId.value) {
  isRunning.value = true;
  runState.value = 'UNKNOWN';
  cancellationDetail.value = '上次提交结果未知且未获得任务 ID；请先核查后台任务，禁止重复提交。';
}

function rememberRun(key: string, value?: string) {
  try {
    if (value === undefined) sessionStorage.removeItem(key);
    else sessionStorage.setItem(key, value);
  } catch (err) { addLog('运行状态无法持久化，关闭页面后需人工核查后台任务: ' + String(err), 'warn'); }
}

function restoreStoredRun() {
  if (isSubmitting.value || disposed) return;
  try {
    const id = runId.value || sessionStorage.getItem('hil.activeRun');
    if (!id) { addLog('没有已记录任务 ID；请核查后台任务，不能据此认定任务未启动。', 'warn'); return; }
    runId.value = id;
    isRunning.value = true;
    if (pollTimer) clearTimeout(pollTimer);
    void pollRun(id, runGeneration.next());
  } catch (err) { addLog('无法恢复任务记录: ' + String(err), 'error'); }
}

function isCurrentRun(id: string, token: number): boolean {
  return !disposed && isRunning.value && runId.value === id && runGeneration.current(token);
}

function receiveRunEvent(event: HilEvent) {
  if (event.kind === 'step.started' && event.step_id) {
    stepResults.value[event.step_id] = { step_id: event.step_id, step_name: event.step_id, status: 'running', duration_ms: 0, timestamp: '' };
  } else if (event.kind === 'step.finished' && event.result) {
    stepResults.value[event.result.step_id] = event.result;
    addLog(event.result.step_name + ': ' + (event.result.message || event.result.status), event.result.status === 'pass' ? 'success' : 'error');
  } else if (event.kind === 'serial' && event.data) {
    const port = event.port || 'UART';
    if (!serialViews.has(port)) serialViews.set(port, new TextDecoder());
    const bytes = Uint8Array.from(event.data.match(/.{2}/g) || [], v => parseInt(v, 16));
    const text = serialViews.get(port)!.decode(bytes, { stream: true });
    addLog('[' + port + '] ' + text, 'info');
  } else if (event.line) addLog(event.line, 'info');
}

async function pollRun(id: string, token: number) {
  if (!id || !isCurrentRun(id, token)) return;
  let delay = 500;
  try {
    const state = await hilCall<HilStatus>('get_hiltest_status', { run_id: id });
    if (!isCurrentRun(id, token)) return;
    if (state.run_id !== id) throw new Error('后台返回了不匹配的任务 ID');
    runState.value = state.state;
    cancellationDetail.value = state.cancel_detail || state.stop_detail || (state.flash_state ? `烧录状态 ${state.flash_state.state} · 擦写停止确认 ${state.flash_state.erase_program_stopped ? '是' : '未确认'} · 目标暂停 ${state.flash_state.target_halted ? '是' : '未确认'}` : '');
    reportDir.value = state.report_dir;
    currentLoopIndex.value = state.loop || 0;
    activeStepId.value = state.current_step || '';
    // Drain at most 800 events per turn; yield to the UI before another bounded batch.
    // A terminal state is not permission to discard the event tail or release the run guard.
    let drained = false;
    for (let page = 0; page < 4; page++) {
      const after = eventCursor;
      const batch = await hilCall<{ events: HilEvent[]; cursor: number }>('get_hiltest_events', { run_id: id, after, limit: 200 });
      if (!isCurrentRun(id, token)) return;
      if (!Array.isArray(batch.events) || !Number.isSafeInteger(batch.cursor) || batch.cursor < after || (batch.events.length > 0 && batch.cursor <= after)) {
        throw new Error('后台事件游标无效；保留运行保护');
      }
      for (const event of batch.events) receiveRunEvent(event);
      eventCursor = batch.cursor;
      if (batch.events.length < 200) { drained = true; break; }
    }
    if (!drained) delay = 0;
    if (state.done && drained) {
      const report = await hilCall<HilReport>('get_hiltest_report', { run_id: id });
      if (!isCurrentRun(id, token)) return;
      executionReport.value = displayReport(report);
      for (const row of report.results || []) stepResults.value[row.step_id] = row;
      for (const [port, decoder] of serialViews) {
        const tail = decoder.decode();
        if (tail) addLog('[' + port + '] ' + tail, 'info');
      }
      serialViews.clear();
      addLog('运行结束: ' + state.state + ' · ' + (state.error || state.report_dir), state.state === 'PASS' ? 'success' : 'error');
      rememberRun('hil.activeRun');
      rememberRun('hil.submissionUnknown');
      isReportModalOpen.value = true;
      isStopping.value = false;
      isRunning.value = false;
      return;
    }
  } catch (err) {
    if (!isCurrentRun(id, token)) return;
    runState.value = 'UNKNOWN';
    cancellationDetail.value = '后台状态或最终报告暂不可确认；保持运行保护并继续查询。';
    addLog('后台状态未知（未判定成功，也未判定停止）: ' + String(err), 'error');
  }
  if (isCurrentRun(id, token)) pollTimer = setTimeout(() => pollRun(id, token), delay);
}

async function runPipeline(onlySelected = false) {
  if (isSubmitting.value || isRunning.value || isStopping.value) return;
  if (!isTauri()) { addLog('浏览器预览不能执行真实硬件测试', 'error'); return; }
  if (onlySelected && !selectedStep.value) return;
  isSubmitting.value = true;
  let submitted = false;
  try {
    const snapshot = pipelineSnapshot(pipeline.value, onlySelected ? selectedStep.value!.id : undefined);
    await hilCall('validate_hiltest', { document: snapshot });
    if (disposed) return;
    // Once dispatch begins a transport failure does not prove that no hardware job exists.
    submitted = true;
    isRunning.value = true;
    runState.value = 'SUBMITTING';
    runId.value = '';
    rememberRun('hil.submissionUnknown', 'true');
    const state = await hilCall<HilStatus>('run_hiltest', { document: snapshot });
    if (!state.run_id) throw new Error('后台未返回任务 ID');
    rememberRun('hil.activeRun', state.run_id);
    rememberRun('hil.submissionUnknown');
    if (disposed) return;
    clearLogs();
    stepResults.value = {};
    eventCursor = 0;
    serialViews.clear();
    executionReport.value = null;
    runId.value = state.run_id;
    reportDir.value = state.report_dir;
    runState.value = state.state;
    cancellationDetail.value = '';
    activeStepId.value = '';
    isStopping.value = false;
    addLog('后台任务已启动，当前参数已固定。串口由 runner 接管。', 'info');
    if (pollTimer) clearTimeout(pollTimer);
    const token = runGeneration.next();
    void pollRun(state.run_id, token);
  } catch (err) {
    if (submitted && isHilSubmissionRejected(err)) {
      isRunning.value = false;
      runState.value = 'REJECTED';
      cancellationDetail.value = '后台明确拒绝，尚未启动任务；可修改参数后重新提交。';
      rememberRun('hil.submissionUnknown');
      addLog('任务未启动: ' + String(err), 'error');
    } else if (submitted) {
      runState.value = 'UNKNOWN';
      cancellationDetail.value = '提交结果未知，不能重复提交；请核查后台任务。未获得任务 ID 时无法从此页停止。';
      addLog('任务提交结果未知: ' + String(err), 'error');
    } else addLog('校验失败，未启动任务: ' + String(err), 'error');
  } finally { isSubmitting.value = false; }
}

async function stopPipeline() {
  if (!runId.value || !isRunning.value || isStopping.value) return;
  const id = runId.value;
  const token = runGeneration.next();
  if (pollTimer) clearTimeout(pollTimer);
  isStopping.value = true;
  runState.value = 'STOPPING';
  cancellationDetail.value = '停止请求处理中；尚未确认设备释放。';
  try {
    const state = await hilCall<HilStatus>('stop_hiltest', { run_id: id });
    if (!isCurrentRun(id, token)) return;
    runState.value = state.state;
    addLog('已请求停止；以后台最终状态及报告为准。', 'warn');
  } catch (err) {
    if (!isCurrentRun(id, token)) return;
    runState.value = 'UNKNOWN';
    cancellationDetail.value = '停止结果未知；保持运行保护，继续查询后台状态。';
    isStopping.value = false;
    addLog('停止请求结果未知: ' + String(err), 'error');
  } finally {
    if (isCurrentRun(id, token)) void pollRun(id, token);
  }
}

// Export the backend result safely; never interpret device text as HTML.
function downloadHtmlReport() {
  if (!executionReport.value) return;
  const escaped = JSON.stringify(executionReport.value, null, 2).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const html = '<!doctype html><meta charset="utf-8"><title>HIL report</title><pre>' + escaped + '</pre>';
  const url = URL.createObjectURL(new Blob([html], { type: 'text/html;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url; link.download = 'HIL_Report.html'; link.click();
  URL.revokeObjectURL(url);
}

// Safe initial example: no hardware command is added automatically.
function loadDemoPipeline() {
  pipeline.value = {
    schema_version: 2, bench: {}, name: '无硬件流程示例', version: '2', loop_count: 1, stop_on_error: true,
    steps: [{ id: 'delay', name: '仅等待（不访问硬件）', action: 'delay', enabled: true, params: { delay_ms: 100 }, timeout_ms: 1000 }],
  };
  selectedStepId.value = 'delay';
  addLog('已加载无硬件示例；此结果不能用于宣称开发板已验证', 'info');
}

function loadSerialTemplate() {
  const bench = { ...pipeline.value.bench };
  pipeline.value = {
    schema_version: 2, bench, name: '纯串口发送与应答', version: '2', loop_count: 1, stop_on_error: true,
    steps: [
      { id: 'capture', name: '提前打开串口采集', action: 'serial_open', enabled: true, params: {} },
      { id: 'send', name: '发送（填写实际设备指令）', action: 'serial_send', enabled: true, params: { send_data: '', send_format: 'string', send_ending: 'crlf', character_delay_ms: 0 } },
      { id: 'expect', name: '等待应答（填写实际匹配内容）', action: 'serial_wait_match', enabled: true, params: { match_type: 'contains', pattern: '', timeout_ms: 3000 }, timeout_ms: 3000 },
    ],
  };
  selectedStepId.value = 'send';
}

function loadHilTemplate() {
  const bench = { ...pipeline.value.bench };
  pipeline.value = {
    schema_version: 2, version: '2', name: '固件自驱动 HIL 观察（不自动烧录或复位）', bench,
    loop_count: 1, stop_on_error: true,
    steps: [
      { id: 'capture', name: '持续串口采集', action: 'serial_open', enabled: true, params: {} },
      { id: 'observe', name: '等待固件已有自测结果', action: 'hil_observe', enabled: true, timeout_ms: 1800000,
        params: { timeout_ms: 1800000, boot_timeout_ms: 10000, idle_timeout_ms: 15000, boot_count: 1, continue_on_failure: true } },
    ],
  };
  selectedStepId.value = 'observe';
  addLog('HIL 观察模板不会复位或烧录；请按固件协议配置工位和停止策略，再显式添加硬件动作', 'info');
}

onMounted(async () => {
  if (runId.value) restoreStoredRun();
  await refreshPorts();
  await refreshProbes();
  if (pipeline.value.steps.length === 0) loadDemoPipeline();

});

onUnmounted(() => {
  disposed = true;
  runGeneration.next();
  if (pollTimer) clearTimeout(pollTimer);
  // Unmount only detaches the viewer. The worker continues independently.
});
</script>

<template>
  <div class="h-full flex flex-col bg-zinc-950 text-zinc-100 font-sans select-none overflow-hidden">
    <!-- Top Toolbar Header -->
    <div class="bg-zinc-900 border-b border-zinc-800 px-4 py-2.5 flex flex-wrap items-center justify-between gap-3 shrink-0">
      <div class="flex items-center gap-3">
        <div class="h-8 w-8 rounded-lg bg-emerald-500/10 border border-emerald-500/30 flex items-center justify-center text-emerald-400 font-bold shadow-inner">
          <Zap class="w-4 h-4" />
        </div>
        <div>
          <div class="flex items-center gap-2">
            <input
              v-model="pipeline.name"
              class="bg-transparent font-bold text-sm text-zinc-100 hover:bg-zinc-800/60 px-1 py-0.5 rounded border border-transparent hover:border-zinc-700 outline-none w-64"
              :placeholder="t('seq_pipeline_name')"
            />
            <span class="text-[10px] px-1.5 py-0.2 rounded bg-zinc-800 text-zinc-400 font-mono border border-zinc-700">v{{ pipeline.version }}</span>
          </div>
          <p class="text-[11px] text-zinc-400 truncate max-w-md">{{ t('seq_desc') }}</p>
        </div>
      </div>

      <!-- Center / Right Action Controls -->
      <div class="flex flex-wrap items-center gap-2">
        <div class="flex items-center gap-1.5 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-xs text-zinc-300">
          <span class="text-zinc-500">{{ t('seq_loop_count') }}:</span>
          <input
            type="number"
            v-model.number="pipeline.loop_count"
            min="1"
            max="10000"
            class="w-12 bg-zinc-900 border border-zinc-700 rounded px-1.5 py-0.5 text-center font-mono text-emerald-400 outline-none"
          />
        </div>

        <label class="flex items-center gap-1.5 text-xs text-zinc-400 cursor-pointer px-2">
          <input type="checkbox" v-model="pipeline.stop_on_error" class="rounded bg-zinc-800 border-zinc-700 text-emerald-500 focus:ring-0">
          <span>{{ t('seq_stop_on_error') }}</span>
        </label>

        <div class="h-4 w-[1px] bg-zinc-800 mx-1"></div>

        <button
          @click="openPipelineFromFile"
          :disabled="isImporting"
          class="flex items-center gap-1 px-2.5 py-1.5 rounded text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 transition-colors"
          :title="t('seq_open_pipeline')"
        >
          <FolderOpen class="w-3.5 h-3.5 text-sky-400" />
          <span>{{ t('seq_open_pipeline') }}</span>
        </button>

        <button
          @click="savePipelineToFile"
          class="flex items-center gap-1 px-2.5 py-1.5 rounded text-xs bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 transition-colors"
          :title="t('seq_save_pipeline')"
        >
          <Download class="w-3.5 h-3.5 text-emerald-400" />
          <span>{{ t('seq_save_pipeline') }}</span>
        </button>

        <button
          v-if="!isRunning"
          @click="runPipeline(false)"
          :disabled="isSubmitting || isStopping"
          class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-semibold bg-emerald-600 hover:bg-emerald-500 text-zinc-950 shadow-sm transition-all"
        >
          <Play class="w-3.5 h-3.5 fill-current" />
          <span>{{ isSubmitting ? '正在校验 / 提交…' : t('seq_run_all') }}</span>
        </button>

        <button
          v-else
          @click="stopPipeline"
          :disabled="isSubmitting || isStopping || !runId"
          class="flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-semibold bg-rose-600 hover:bg-rose-500 text-zinc-100 shadow-sm transition-all animate-pulse"
        >
          <Square class="w-3.5 h-3.5 fill-current" />
          <span>{{ isSubmitting ? '任务提交中…' : isStopping ? '等待停止确认…' : t('seq_stop_run') }}</span>
        </button>

        <button
          v-if="executionReport"
          @click="isReportModalOpen = true"
          class="flex items-center gap-1 px-2.5 py-1.5 rounded text-xs bg-indigo-950 hover:bg-indigo-900 text-indigo-300 border border-indigo-800 transition-colors"
        >
          <FileCode class="w-3.5 h-3.5 text-indigo-400" />
          <span>{{ t('seq_export_report') }}</span>
        </button>
      </div>
    </div>

    <!-- Main Workspace (Three Panes Layout) -->
    <div class="px-4 py-2 bg-zinc-900 border-b border-zinc-800 text-xs flex flex-wrap items-center gap-3">
      <span class="text-zinc-400">工位默认值</span>
      <input v-model="pipeline.bench!.probe_id" placeholder="探针 SN（必须明确选择）" class="bg-zinc-950 border border-zinc-700 rounded px-2 py-1 w-44" />
      <input v-model="pipeline.bench!.target_device" placeholder="芯片型号 / Pack 设备名" class="bg-zinc-950 border border-zinc-700 rounded px-2 py-1 w-40" />
      <input v-model="pipeline.bench!.port_name" placeholder="日志串口，如 COM3" class="bg-zinc-950 border border-zinc-700 rounded px-2 py-1 w-36" />
      <label class="flex items-center gap-1">波特率<input type="number" min="1" v-model.number="pipeline.bench!.baud_rate" placeholder="明确填写" class="bg-zinc-950 border border-zinc-700 rounded px-2 py-1 w-28" /></label>
      <label class="flex items-center gap-1">SWD Hz<input type="number" min="1" v-model.number="pipeline.bench!.frequency" placeholder="明确填写" class="bg-zinc-950 border border-zinc-700 rounded px-2 py-1 w-28" /></label>
      <input v-model="pipeline.bench!.pack_path" placeholder="Pack 路径（需要时填写）" class="bg-zinc-950 border border-zinc-700 rounded px-2 py-1 w-52" />
      <button @click="runPipeline(true)" :disabled="isSubmitting || isRunning || isStopping || !selectedStep" class="px-2 py-1 rounded bg-sky-900 disabled:opacity-40">运行选中步骤</button>
      <button @click="loadHilTemplate" :disabled="isSubmitting || isRunning" class="px-2 py-1 rounded bg-zinc-800 disabled:opacity-40">HIL 观察模板</button>
      <button @click="loadSerialTemplate" :disabled="isSubmitting || isRunning" class="px-2 py-1 rounded bg-zinc-800 disabled:opacity-40">纯串口起步模板</button>
      <button @click="loadDemoPipeline" :disabled="isSubmitting || isRunning" class="px-2 py-1 rounded bg-zinc-800 disabled:opacity-40">无硬件示例</button>
      <button @click="editSource" class="px-2 py-1 rounded bg-zinc-800">JSON 脚本</button>
      <span class="text-amber-400">{{ isRunning ? '运行使用启动快照；修改下次生效' : '支持 PyOCD / ING INI 后台烧录；ING 取消在页/扇区边界生效，需核对复位接线及停止应答' }}</span>
      <span v-if="runState" class="font-mono">{{ runState }}</span><button v-if="runState === 'UNKNOWN'" @click="restoreStoredRun" :disabled="isSubmitting" class="px-2 py-1 bg-zinc-800 rounded disabled:opacity-40">重新查询已记录任务</button>
      <span v-if="cancellationDetail" class="text-amber-300">{{ cancellationDetail }}</span>
      <span v-if="reportDir" class="text-zinc-400 select-text break-all">报告：{{ reportDir }}</span>
    </div>
    <p v-if="importError" role="alert" class="px-4 py-2 text-xs text-rose-300 bg-rose-950/30 select-text">{{ importError }}</p>
    <div class="flex-1 flex overflow-hidden">
      <div v-if="sourceVisible" class="absolute inset-8 z-40 bg-zinc-900 border border-zinc-600 rounded p-4 flex flex-col gap-3">
        <div class="text-sm">JSON 脚本编辑 · 嵌套步骤/未知字段原样保留；合法性由后台校验，旧版工程不自动改版</div>
        <textarea v-model="sourceText" spellcheck="false" class="flex-1 min-h-64 bg-zinc-950 p-3 font-mono text-xs select-text" />
        <p v-if="sourceError" role="alert" class="text-xs text-rose-300 whitespace-pre-wrap select-text">{{ sourceError }}</p>
        <div class="flex gap-2"><button @click="applySource" :disabled="sourceApplying" class="bg-emerald-800 rounded px-3 py-1 disabled:opacity-40">{{ sourceApplying ? '校验中…' : '校验并应用' }}</button><button @click="sourceVisible = false" :disabled="sourceApplying" class="bg-zinc-700 rounded px-3 py-1">关闭</button></div>
      </div>
      <!-- 1. Left: Action Palette (动作库) -->
      <div class="w-64 border-r border-zinc-800 bg-zinc-900/60 flex flex-col shrink-0">
        <div class="p-3 border-b border-zinc-800 bg-zinc-900/90 flex items-center justify-between">
          <div class="font-bold text-xs text-zinc-200">{{ t('seq_action_palette') }}</div>
          <span class="text-[10px] text-zinc-500">{{ actionTemplates.length }} 动作</span>
        </div>
        <p class="px-3 py-1.5 text-[10px] text-zinc-500 border-b border-zinc-800/40">{{ t('seq_palette_desc') }}</p>

        <div class="flex-1 p-2 space-y-2 overflow-y-auto">
          <div
            v-for="tmpl in actionTemplates"
            :key="tmpl.action"
            @click="addStepFromTemplate(tmpl)"
            class="p-2.5 rounded-lg border border-zinc-800/80 bg-zinc-900/80 hover:bg-zinc-800/80 hover:border-zinc-700 cursor-pointer transition-all group flex items-start gap-2.5 shadow-xs"
          >
            <div :class="`p-1.5 rounded ${tmpl.color} border shrink-0 mt-0.5`">
              <component :is="tmpl.icon" class="w-3.5 h-3.5" />
            </div>
            <div class="min-w-0 flex-1">
              <div class="font-medium text-xs text-zinc-200 group-hover:text-emerald-400 flex items-center justify-between">
                <span>{{ t(tmpl.nameKey) }}</span>
                <Plus class="w-3.5 h-3.5 text-zinc-500 opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
              <p class="text-[10.5px] text-zinc-400 line-clamp-2 mt-0.5 leading-tight">{{ t(tmpl.descKey) }}</p>
            </div>
          </div>
        </div>
      </div>

      <!-- 2. Center: Sequencer Flow & Step List (测试流水线) -->
      <div class="flex-1 flex flex-col border-r border-zinc-800 bg-zinc-950 overflow-hidden">
        <div class="p-3 border-b border-zinc-800 bg-zinc-900/50 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <span class="font-bold text-xs text-zinc-200">{{ t('seq_step_list') }}</span>
            <span class="text-[11px] px-2 py-0.2 rounded-full bg-zinc-800 text-zinc-400 font-mono">{{ pipeline.steps.length }} 步骤</span>
          </div>

          <div v-if="isRunning" class="flex items-center gap-2 text-xs font-mono text-emerald-400 animate-pulse">
            <span>第 {{ currentLoopIndex }} 轮 · 当前步骤 {{ activeStepId || "等待后台确认" }}</span>
          </div>
        </div>

        <!-- Step List Cards -->
        <div class="flex-1 p-3 overflow-y-auto space-y-2">
          <template v-if="pipeline.steps.length > 0">
            <div
              v-for="(step, idx) in pipeline.steps"
              :key="step.id"
              @click="selectedStepId = step.id"
              class="border rounded-lg p-3 transition-all cursor-pointer relative"
              :class="[
                selectedStepId === step.id
                  ? 'border-emerald-500/80 bg-zinc-900 shadow-md ring-1 ring-emerald-500/20'
                  : 'border-zinc-800/80 bg-zinc-900/40 hover:bg-zinc-900/80',
                !step.enabled ? 'opacity-50' : '',
                stepResults[step.id]?.status === 'running' ? 'border-sky-500 ring-2 ring-sky-500/30' : '',
                stepResults[step.id]?.status === 'pass' ? 'border-emerald-700/60' : '',
                stepResults[step.id]?.status === 'fail' ? 'border-rose-700/80 bg-rose-950/10' : ''
              ]"
            >
              <div class="flex items-center justify-between gap-2">
                <div class="flex items-center gap-2.5 min-w-0">
                  <!-- Step Index Badge -->
                  <span class="w-5 h-5 rounded-full bg-zinc-800 font-mono text-[10px] flex items-center justify-center text-zinc-400 shrink-0">
                    {{ idx + 1 }}
                  </span>

                  <!-- Status Icon -->
                  <div class="shrink-0">
                    <CheckCircle2 v-if="stepResults[step.id]?.status === 'pass'" class="w-4 h-4 text-emerald-400" />
                    <XCircle v-else-if="stepResults[step.id]?.status === 'fail'" class="w-4 h-4 text-rose-400" />
                    <Activity v-else-if="stepResults[step.id]?.status === 'running'" class="w-4 h-4 text-sky-400 animate-spin" />
                    <Clock v-else class="w-4 h-4 text-zinc-600" />
                  </div>

                  <!-- Step Name & Action Type -->
                  <div class="min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="font-semibold text-xs text-zinc-200 truncate">{{ step.name }}</span>
                      <span class="text-[9.5px] uppercase font-mono px-1.5 py-0.2 rounded bg-zinc-800 text-zinc-400 border border-zinc-700/60">
                        {{ step.action }}
                      </span>
                    </div>

                    <!-- Compact Param Info Preview -->
                    <div class="text-[11px] text-zinc-500 truncate mt-0.5 font-mono">
                      <span v-if="step.action === 'flash_firmware'">{{ step.params?.file_path || '未选择文件' }}</span>
                      <span v-else-if="step.action === 'reset_target'">{{ step.params?.reset_method }} ({{ step.params?.pulse_ms }}ms)</span>
                      <span v-else-if="step.action === 'serial_send'">[{{ step.params?.port_name }}] &gt;&gt; {{ step.params?.send_data }}</span>
                      <span v-else-if="step.action === 'serial_wait_match'">[{{ step.params?.port_name }}] 等待包含 "{{ step.params?.pattern }}"</span>
                      <span v-else-if="step.action === 'swd_read_assert'">{{ step.params?.memory_addr }} {{ step.params?.operator }} {{ step.params?.expected_value }}</span>
                      <span v-else-if="step.action === 'svd_check_reg'">{{ step.params?.peripheral }}->{{ step.params?.register }} == {{ step.params?.expected_reg_val }}</span>
                      <span v-else-if="step.action === 'delay'">延时 {{ step.params?.delay_ms }}ms</span>
                    </div>
                  </div>
                </div>

                <!-- Step Control Buttons -->
                <div class="flex items-center gap-1 shrink-0">
                  <span v-if="stepResults[step.id]?.duration_ms" class="text-[10px] font-mono text-zinc-500 mr-2">
                    {{ stepResults[step.id]?.duration_ms }}ms
                  </span>

                  <button
                    @click.stop="toggleStepEnabled(step)"
                    class="p-1 hover:bg-zinc-800 rounded text-zinc-400 hover:text-zinc-200"
                    :title="step.enabled ? t('seq_step_disable') : t('seq_step_enable')"
                  >
                    <span :class="step.enabled ? 'text-emerald-400 font-bold' : 'text-zinc-600'">●</span>
                  </button>

                  <button
                    @click.stop="moveStepUp(idx)"
                    :disabled="idx === 0"
                    class="p-1 hover:bg-zinc-800 rounded text-zinc-400 hover:text-zinc-200 disabled:opacity-20"
                    :title="t('seq_step_move_up')"
                  >
                    <ArrowUp class="w-3.5 h-3.5" />
                  </button>

                  <button
                    @click.stop="moveStepDown(idx)"
                    :disabled="idx === pipeline.steps.length - 1"
                    class="p-1 hover:bg-zinc-800 rounded text-zinc-400 hover:text-zinc-200 disabled:opacity-20"
                    :title="t('seq_step_move_down')"
                  >
                    <ArrowDown class="w-3.5 h-3.5" />
                  </button>

                  <button
                    @click.stop="removeStep(idx)"
                    class="p-1 hover:bg-zinc-800 hover:text-rose-400 rounded text-zinc-400"
                    :title="t('seq_step_delete')"
                  >
                    <Trash2 class="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              <!-- Inline Error/Success Result Message -->
              <div v-if="stepResults[step.id]?.message" class="mt-2 text-[11px] pt-1.5 border-t border-zinc-800/60 font-mono flex items-center justify-between">
                <span :class="stepResults[step.id]?.status === 'pass' ? 'text-emerald-400' : 'text-rose-400'">
                  {{ stepResults[step.id]?.message }}
                </span>
                <span v-if="stepResults[step.id]?.actual_output" class="text-zinc-500 truncate max-w-xs">
                  实际: {{ stepResults[step.id]?.actual_output }}
                </span>
              </div>
            </div>
          </template>

          <div v-else class="h-64 flex flex-col items-center justify-center text-zinc-500 border border-dashed border-zinc-800 rounded-xl">
            <Zap class="w-8 h-8 text-zinc-600 mb-2 stroke-1" />
            <p class="text-xs">{{ t('seq_empty_steps') }}</p>
          </div>
        </div>

        <!-- Bottom Runner Logs Drawer (Resizable) -->
        <ResizableDrawer
          direction="vertical"
          side="top"
          storage-key="hil_drawer_height_sequencer_logs"
          :min="100"
          :max="500"
          :default-size="176"
          class="border-t border-zinc-800 bg-zinc-950 flex flex-col shrink-0"
        >
          <div class="px-3 py-1.5 bg-zinc-900 border-b border-zinc-800 flex items-center justify-between text-xs">
            <div class="flex items-center gap-2">
              <Terminal class="w-3.5 h-3.5 text-emerald-400" />
              <span class="font-semibold text-zinc-300">{{ t('seq_log_title') }}</span><span class="text-[10px] text-zinc-500">最近 500 条；完整事件见报告目录</span>
            </div>
            <button
              @click="clearLogs"
              class="text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              {{ t('seq_clear_logs') }}
            </button>
          </div>
          <div class="flex-1 p-2 overflow-y-auto font-mono text-[11px] space-y-1">
            <div
              v-for="l in runnerLogs"
              :key="l.id"
              class="flex items-start gap-2 leading-relaxed"
            >
              <span class="text-zinc-600 shrink-0">[{{ l.time }}]</span>
              <span
                :class="[
                  l.status === 'info' ? 'text-zinc-300' : '',
                  l.status === 'success' ? 'text-emerald-400' : '',
                  l.status === 'error' ? 'text-rose-400 font-semibold' : '',
                  l.status === 'warn' ? 'text-amber-400' : ''
                ]"
              >
                {{ l.text }}
              </span>
            </div>
          </div>
        </ResizableDrawer>
      </div>

      <!-- 3. Right: Step Parameter Inspector (步骤参数配置检查器) -->
      <div class="w-80 border-l border-zinc-800 bg-zinc-900/50 flex flex-col shrink-0">
        <div class="p-3 border-b border-zinc-800 bg-zinc-900/90 font-bold text-xs text-zinc-200">
          步骤属性与参数配置
        </div>

        <div v-if="selectedStep && selectedStep.params" class="flex-1 p-3 overflow-y-auto space-y-3.5 text-xs">
          <div>
            <label class="block text-zinc-400 text-[11px] mb-1 font-medium">步骤名称</label>
            <input
              v-model="selectedStep.name"
              class="w-full bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 text-xs outline-none focus:border-emerald-500"
            />
          </div>

          <p v-if="selectedStep.steps?.length" class="text-amber-300 text-[11px]">含 {{ selectedStep.steps.length }} 个嵌套步骤；完整结构在 JSON 脚本中编辑，提交时不会丢弃。</p>
          <p v-if="!actionTemplates.some(item => item.action === selectedStep?.action)" class="text-amber-300 text-[11px]">此动作 / 旧版别名使用 JSON 编辑参数；保留原始字段，由后台解析与校验。</p>
          <!-- Parameter Fields per Action -->
          <div>
            <label class="block text-zinc-400 text-[11px] mb-1">步骤超时（ms 或 5s / 2m；JSON 删除字段使用默认）</label>
            <input type="text" v-model="selectedStep.timeout_ms" class="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1" />
            <label class="block text-zinc-400 text-[11px] mt-2 mb-1">失败处理</label>
            <select v-model="selectedStep.on_failure" class="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1">
              <option :value="undefined">使用流水线默认策略（遇错即停止设置）</option>
              <option value="abort">取证后停止</option><option value="continue">记录失败并继续（取证可能暂停目标）</option>
              <option value="retry" :disabled="!['swd_read_assert', 'swd_read_block', 'svd_check_reg'].includes(selectedStep.action)">只读断言重试</option>
            </select>
            <input v-if="selectedStep.on_failure === 'retry'" type="number" min="0" max="10" v-model.number="selectedStep.retry_count" class="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1 mt-1" />
          </div>
          <!-- flash_firmware -->
          <template v-if="selectedStep.action === 'flash_firmware'">
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_flash_type') }}</label>
              <select
                v-model="selectedStep.params.flash_type"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs"
              >
                <option value="pyocd">PyOCD 通用 SWD 烧录器</option>
                <option value="ing_ini">ING INI（HIL 后端下载）</option>
              </select>
            </div>
            <!-- SWD Probe Selector for PyOCD flash -->
            <div v-if="selectedStep.params.flash_type === 'pyocd'">
              <div class="flex items-center justify-between text-zinc-400 text-[11px] mb-1 font-medium">
                <span>SWD 硬件调试器</span>
                <button @click="refreshProbes" class="text-emerald-400 hover:underline text-[10px]">刷新</button>
              </div>
              <select
                v-model="selectedStep.params.probe_id"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
              >
                <option value="">使用工位默认探针（需明确指定）</option>
                <option v-for="pr in availableProbes" :key="pr.unique_id" :value="pr.unique_id">
                  {{ formatProbeLabel(pr) }}
                </option>
              </select>
            </div>
            <!-- Serial Port & Baud for ING ini flash -->
            <div v-if="selectedStep.params.flash_type === 'ing_ini'" class="space-y-2">
              <p class="text-xs text-amber-700">HIL 会由 Rust 后端执行 ING ISP 下载；请填写串口，取消只在当前页/扇区边界生效。压测固件停止需在流水线顶层配置 stop，等待 STOPPED 确认。</p>
              <div>
                <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_port_name') }}</label>
                <select
                  v-model="selectedStep.params.port_name"
                  class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
                >
                  <option value="">使用工位默认串口（需明确指定）</option>
                <option v-for="p in availablePorts" :key="p.port_name" :value="p.port_name">{{ p.port_name }}</option>
                </select>
              </div>
              <div>
                <label class="block text-zinc-400 text-[11px] mb-1 font-medium">运行串口波特率（ISP 速率读取 INI）</label>
                <select
                  v-model.number="selectedStep.params.baud_rate"
                  class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
                >
                  <option v-for="b in baudPresets" :key="b" :value="b">
                    {{ b >= 1000000 ? `${(b / 1000000).toFixed(b % 1000000 === 0 ? 0 : 2)}M` : b }} bps
                  </option>
                </select>
              </div>
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_target_file') }}</label>
              <div class="flex gap-1.5">
                <input
                  v-model="selectedStep.params.file_path"
                  class="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
                  placeholder="C:/firmware/app.hex"
                />
                <button
                  @click="pickStepFirmware(selectedStep)"
                  class="px-2 py-1 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded border border-zinc-700 text-[11px]"
                >
                  浏览
                </button>
              </div>
            </div>
          </template>

          <!-- reset_target -->
          <template v-if="selectedStep.action === 'reset_target'">
            <div v-if="selectedStep.params.reset_method !== 'swd_soft_reset' && selectedStep.params.pin_reset" class="space-y-2 border border-amber-800/50 rounded p-2">
              <label class="block">控制串口<input v-model="selectedStep.params.port_name" placeholder="留空使用工位默认串口" class="w-full bg-zinc-950 p-1" /></label>
              <label class="block">接线配置 ID<input v-model="selectedStep.params.pin_reset.profile_id" class="w-full bg-zinc-950 p-1" /></label>
              <label class="block text-amber-300"><input type="checkbox" v-model="selectedStep.params.pin_reset.wiring_verified" /> 已核对本工位 RTS/DTR 接线及极性</label>
              <label class="block">DTR 复位有效值<select v-model="selectedStep.params.pin_reset.reset_asserted_dtr" class="bg-zinc-950"><option :value="true">true</option><option :value="false">false</option></select></label>
              <label class="block">RTS Boot 有效值<select v-model="selectedStep.params.pin_reset.boot_asserted_rts" class="bg-zinc-950"><option :value="true">true</option><option :value="false">false</option></select></label>
              <label class="block">Boot 稳定 ms<input type="number" v-model.number="selectedStep.params.pin_reset.settle_ms" class="w-full bg-zinc-950" /></label>
              <label class="block">复位后 Boot 保持 ms<input type="number" v-model.number="selectedStep.params.pin_reset.boot_hold_ms" class="w-full bg-zinc-950" /></label>
              <p class="text-zinc-400">控制线完成不代表进入 Boot 成功；请添加串口应答断言。</p>
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_reset_method') }}</label>
              <select
                v-model="selectedStep.params.reset_method"
                @change="ensurePinReset(selectedStep)"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs"
              >
                <option value="pin_dtr_pulse">DTR 引脚复位（需核对接线）</option>
                <option value="swd_soft_reset">SWD 软复位 (NVIC_SystemReset)</option>
                <option value="bootloader_reset">RTS + DTR Bootloader（需核对接线）</option>
              </select>
            </div>
            <div v-if="selectedStep.params.reset_method === 'swd_soft_reset'">
              <div class="flex items-center justify-between text-zinc-400 text-[11px] mb-1 font-medium">
                <span>SWD 硬件调试器</span>
                <button @click="refreshProbes" class="text-emerald-400 hover:underline text-[10px]">刷新</button>
              </div>
              <select
                v-model="selectedStep.params.probe_id"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
              >
                <option value="">使用工位默认探针（需明确指定）</option>
                <option v-for="pr in availableProbes" :key="pr.unique_id" :value="pr.unique_id">
                  {{ formatProbeLabel(pr) }}
                </option>
              </select>
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_pulse_ms') }}</label>
              <input
                type="number"
                v-model.number="selectedStep.params.pulse_ms"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
              />
            </div>
          </template>

          <!-- serial_send -->
          <label v-if="selectedStep.action === 'serial_send'" class="block text-zinc-400 text-[11px]">逐字节发送间隔（ms；0 为整块发送）
            <input type="number" min="0" v-model.number="selectedStep.params.character_delay_ms" class="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1 mt-1" />
          </label>
          <template v-if="selectedStep.action === 'serial_send'">
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_port_name') }}</label>
              <select
                v-model="selectedStep.params.port_name"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs"
              >
                <option value="">使用工位默认串口（需明确指定）</option>
                <option v-for="p in availablePorts" :key="p.port_name" :value="p.port_name">
                  {{ p.port_name }}
                </option>
              </select>
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">串口波特率 (Baud)</label>
              <div class="flex items-center gap-1.5">
                <select
                  :value="selectedStep ? (baudPresets.includes(Number(selectedStep.params.baud_rate)) ? selectedStep.params.baud_rate : 'custom') : ''"
                  @change="(e: any) => {
                    const v = e.target.value;
                    if (selectedStep && v !== 'custom') selectedStep.params.baud_rate = Number(v);
                  }"
                  class="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
                >
                  <option v-for="b in baudPresets" :key="b" :value="b">
                    {{ b >= 1000000 ? `${(b / 1000000).toFixed(b % 1000000 === 0 ? 0 : 2)}M` : b }} bps
                  </option>
                  <option value="custom">自定义...</option>
                </select>
                <input
                  v-if="!baudPresets.includes(Number(selectedStep.params.baud_rate)) || selectedStep.params.baud_rate === 0"
                  v-model.number="selectedStep.params.baud_rate"
                  type="number"
                  placeholder="Baud"
                  class="w-24 bg-zinc-950 border border-amber-600/70 rounded px-2 py-1 text-amber-300 text-xs font-mono text-center"
                />
              </div>
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_send_format') }}</label>
              <div class="flex gap-2">
                <label class="flex items-center gap-1 text-[11px] text-zinc-400 cursor-pointer">
                  <input type="radio" value="string" v-model="selectedStep.params.send_format" /> ASCII
                </label>
                <label class="flex items-center gap-1 text-[11px] text-zinc-400 cursor-pointer">
                  <input type="radio" value="hex" v-model="selectedStep.params.send_format" /> HEX
                </label>
              </div>
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_line_ending') }}</label>
              <select
                v-model="selectedStep.params.send_ending"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs"
              >
                <option value="crlf">+ CRLF (\r\n)</option>
                <option value="lf">+ LF (\n)</option>
                <option value="none">无 (Raw)</option>
              </select>
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_send_payload') }}</label>
              <textarea
                v-model="selectedStep.params.send_data"
                rows="3"
                class="w-full bg-zinc-950 border border-zinc-800 rounded p-2 text-zinc-200 text-xs font-mono outline-none"
              ></textarea>
            </div>
          </template>

          <!-- serial_wait_match -->
          <template v-if="selectedStep.action === 'serial_open' || selectedStep.action === 'hil_observe'">
            <label class="text-xs text-zinc-400">串口（留空使用工位默认值）</label>
            <input v-model="selectedStep.params.port_name" class="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1 text-xs" />
            <label class="text-xs text-zinc-400">波特率</label>
            <input type="number" v-model.number="selectedStep.params.baud_rate" class="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1 text-xs" />
            <template v-if="selectedStep.action === 'hil_observe'">
              <label class="text-xs text-zinc-400">观察总超时（ms 或 30m）</label>
              <input type="text" v-model="selectedStep.params.timeout_ms" class="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1 text-xs" />
              <label class="text-xs text-zinc-400">启动超时 / 心跳超时（ms）</label>
              <input type="text" v-model="selectedStep.params.boot_timeout_ms" class="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1 text-xs" />
              <input type="text" v-model="selectedStep.params.idle_timeout_ms" class="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1 text-xs" />
              <label class="text-xs text-zinc-400">本轮预期 BOOT 次数</label>
              <input type="number" min="1" v-model.number="selectedStep.params.boot_count" class="w-full bg-zinc-950 border border-zinc-700 rounded px-2 py-1 text-xs" />
              <label class="text-xs text-zinc-400"><input type="checkbox" v-model="selectedStep.params.continue_on_failure" /> FAIL / CRASH 后继续收集至 DONE（仍判失败）</label>
            </template>
          </template>
          <template v-if="selectedStep.action === 'serial_wait_match'">
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_port_name') }}</label>
              <select
                v-model="selectedStep.params.port_name"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs"
              >
                <option value="">使用工位默认串口（需明确指定）</option>
                <option v-for="p in availablePorts" :key="p.port_name" :value="p.port_name">
                  {{ p.port_name }}
                </option>
              </select>
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">串口波特率 (Baud)</label>
              <div class="flex items-center gap-1.5">
                <select
                  :value="selectedStep ? (baudPresets.includes(Number(selectedStep.params.baud_rate)) ? selectedStep.params.baud_rate : 'custom') : ''"
                  @change="(e: any) => {
                    const v = e.target.value;
                    if (selectedStep && v !== 'custom') selectedStep.params.baud_rate = Number(v);
                  }"
                  class="flex-1 bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
                >
                  <option v-for="b in baudPresets" :key="b" :value="b">
                    {{ b >= 1000000 ? `${(b / 1000000).toFixed(b % 1000000 === 0 ? 0 : 2)}M` : b }} bps
                  </option>
                  <option value="custom">自定义...</option>
                </select>
                <input
                  v-if="!baudPresets.includes(Number(selectedStep.params.baud_rate)) || selectedStep.params.baud_rate === 0"
                  v-model.number="selectedStep.params.baud_rate"
                  type="number"
                  placeholder="Baud"
                  class="w-24 bg-zinc-950 border border-amber-600/70 rounded px-2 py-1 text-amber-300 text-xs font-mono text-center"
                />
              </div>
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_match_type') }}</label>
              <select
                v-model="selectedStep.params.match_type"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs"
              >
                <option value="contains">字符串包含 (Contains)</option>
                <option value="regex">正则表达式 (Regex)</option>
              </select>
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_match_pattern') }}</label>
              <input
                v-model="selectedStep.params.pattern"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2.5 py-1.5 text-zinc-200 text-xs font-mono outline-none"
                placeholder="OK 或 System Boot"
              />
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_timeout_ms') }}</label>
              <input
                type="text"
                v-model="selectedStep.params.timeout_ms"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
              />
            </div>
          </template>

          <!-- swd_read_assert -->
          <template v-if="selectedStep.action === 'swd_read_assert'">
            <div>
              <div class="flex items-center justify-between text-zinc-400 text-[11px] mb-1 font-medium">
                <span>SWD 硬件调试器</span>
                <button @click="refreshProbes" class="text-emerald-400 hover:underline text-[10px]">刷新</button>
              </div>
              <select
                v-model="selectedStep.params.probe_id"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
              >
                <option value="">使用工位默认探针（需明确指定）</option>
                <option v-for="pr in availableProbes" :key="pr.unique_id" :value="pr.unique_id">
                  {{ formatProbeLabel(pr) }}
                </option>
              </select>
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_mem_addr') }}</label>
              <input
                v-model="selectedStep.params.memory_addr"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
                placeholder="0x20000000"
              />
            </div>
            <div class="grid grid-cols-2 gap-2">
              <div>
                <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_operator') }}</label>
                <select
                  v-model="selectedStep.params.operator"
                  class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
                >
                  <option value="==">== (等于)</option>
                  <option value="!=">!= (不等于)</option>
                  <option value=">">&gt; (大于)</option>
                  <option value="<">&lt; (小于)</option>
                  <option value=">=">&gt;= (大于等于)</option>
                  <option value="<=">&lt;= (小于等于)</option>
                </select>
              </div>
              <div>
                <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_read_width') }}</label>
                <select
                  v-model="selectedStep.params.read_width"
                  class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
                >
                  <option :value="32">32-Bit Word</option>
                  <option :value="16">16-Bit Half</option>
                  <option :value="8">8-Bit Byte</option>
                </select>
              </div>
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_expected_val') }}</label>
              <input
                v-model="selectedStep.params.expected_value"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
                placeholder="0xAA550001"
              />
            </div>
          </template>

          <!-- svd_check_reg -->
          <template v-if="selectedStep.action === 'svd_check_reg'">
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">芯片型号（Pack 设备名）</label>
              <input v-model="selectedStep.params.target_device" class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono" />
            </div>
            <div>
              <div class="flex items-center justify-between text-zinc-400 text-[11px] mb-1 font-medium">
                <span>SWD 硬件调试器</span>
                <button @click="refreshProbes" class="text-emerald-400 hover:underline text-[10px]">刷新</button>
              </div>
              <select
                v-model="selectedStep.params.probe_id"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
              >
                <option value="">使用工位默认探针（需明确指定）</option>
                <option v-for="pr in availableProbes" :key="pr.unique_id" :value="pr.unique_id">
                  {{ formatProbeLabel(pr) }}
                </option>
              </select>
            </div>
            <div class="grid grid-cols-2 gap-2">
              <div>
                <label class="block text-zinc-400 text-[11px] mb-1 font-medium">外设名称</label>
                <input
                  v-model="selectedStep.params.peripheral"
                  class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
                  placeholder="UART0"
                />
              </div>
              <div>
                <label class="block text-zinc-400 text-[11px] mb-1 font-medium">寄存器</label>
                <input
                  v-model="selectedStep.params.register"
                  class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
                  placeholder="LSR"
                />
              </div>
            </div>
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">预期值 (HEX)</label>
              <input
                v-model="selectedStep.params.expected_reg_val"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
                placeholder="0x60"
              />
            </div>
          </template>

          <!-- delay -->
          <template v-if="selectedStep.action === 'delay'">
            <div>
              <label class="block text-zinc-400 text-[11px] mb-1 font-medium">{{ t('seq_param_delay_ms') }}</label>
              <input
                type="number"
                v-model.number="selectedStep.params.delay_ms"
                class="w-full bg-zinc-950 border border-zinc-800 rounded px-2 py-1 text-zinc-200 text-xs font-mono"
              />
            </div>
          </template>
        </div>

        <div v-else class="flex-1 flex items-center justify-center text-zinc-600 text-xs p-4 text-center">
          在中间流水线中点击任意测试步骤，即可在此编辑具体执行参数
        </div>
      </div>
    </div>

    <!-- Execution Report Modal (执行报告弹窗) -->
    <div
      v-if="isReportModalOpen && executionReport"
      class="fixed inset-0 z-50 bg-black/70 backdrop-blur-xs flex items-center justify-center p-6"
    >
      <div class="bg-zinc-900 border border-zinc-700/80 rounded-xl shadow-2xl w-full max-w-4xl max-h-[85vh] flex flex-col overflow-hidden">
        <div class="p-4 border-b border-zinc-800 flex items-center justify-between">
          <div class="flex items-center gap-2">
            <FileCode class="w-5 h-5 text-emerald-400" />
            <span class="font-bold text-sm text-zinc-100">{{ t('seq_report_title') }} - {{ executionReport.pipeline_name }}</span>
          </div>
          <button
            @click="isReportModalOpen = false"
            class="text-zinc-400 hover:text-zinc-100 p-1 rounded"
          >
            ✕
          </button>
        </div>

        <!-- Metrics Cards -->
        <div class="p-4 grid grid-cols-4 gap-3 bg-zinc-950/50 border-b border-zinc-800">
          <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
            <div class="text-[11px] text-zinc-400">计划步骤</div>
            <div class="text-xl font-bold font-mono text-zinc-200 mt-1">{{ executionReport.planned_steps ?? '未知' }}</div>
          </div>
          <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
            <div class="text-[11px] text-zinc-400">{{ t('seq_summary_passed') }}</div>
            <div class="text-xl font-bold font-mono text-emerald-400 mt-1">{{ executionReport.passed_steps ?? '未知' }}</div>
          </div>
          <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
            <div class="text-[11px] text-zinc-400">{{ t('seq_summary_failed') }}</div>
            <div class="text-xl font-bold font-mono text-rose-400 mt-1">{{ executionReport.failed_steps ?? '未知' }}</div>
          </div>
          <div class="p-3 bg-zinc-900 border border-zinc-800 rounded-lg">
            <div class="text-[11px] text-zinc-400">全计划通过率</div>
            <div class="text-xl font-bold font-mono text-sky-400 mt-1">{{ executionReport.success_rate === null ? '未知' : executionReport.success_rate + '%' }}</div>
          </div>
        </div>

        <div class="px-4 py-2 text-xs flex flex-wrap gap-3 border-b border-zinc-800">
          <span>已执行：{{ executionReport.executed_steps ?? '未知' }}</span>
          <span>未执行 / 跳过：{{ executionReport.skipped_steps ?? '未知' }}</span>
          <span>取消：{{ executionReport.cancelled_steps ?? '未知' }}</span>
          <span>尝试次数（含重试）：{{ executionReport.attempt_count ?? '未知' }}</span>
          <span class="text-amber-300">硬件验证：{{ executionReport.hardware_verified === true ? '后端报告已验证' : executionReport.hardware_verified === false ? '未验证（不可作为硬件验收）' : '未知（旧报告未提供）' }}</span>
          <p class="w-full text-zinc-400">{{ executionReport.statistics_note }}；下表保留每次尝试，不以重试行数冒充计划步骤数。</p>
        </div>
        <!-- Table of Results -->
        <div class="flex-1 p-4 overflow-y-auto">
          <table class="w-full text-left text-xs border border-zinc-800 border-collapse">
            <thead>
              <tr class="bg-zinc-800 text-zinc-400 font-mono text-[11px]">
                <th class="p-2 border border-zinc-700/60">时间</th>
                <th class="p-2 border border-zinc-700/60">用例名称</th>
                <th class="p-2 border border-zinc-700/60">状态</th>
                <th class="p-2 border border-zinc-700/60">耗时</th>
                <th class="p-2 border border-zinc-700/60">实际输出 / 判定说明</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="(item, resultIndex) in executionReport.results"
                :key="resultIndex"
                class="hover:bg-zinc-800/40 font-mono text-[11px]"
              >
                <td class="p-2 border border-zinc-800 text-zinc-500">{{ item.timestamp }}</td>
                <td class="p-2 border border-zinc-800 font-sans text-zinc-200">{{ item.step_name }}</td>
                <td class="p-2 border border-zinc-800">
                  <span
                    :class="[
                      item.status === 'pass' ? 'text-emerald-400 font-bold' : '',
                      item.status === 'fail' ? 'text-rose-400 font-bold' : '',
                      item.status === 'skipped' ? 'text-zinc-500' : ''
                    ]"
                  >
                    {{ item.status.toUpperCase() }}
                  </span>
                </td>
                <td class="p-2 border border-zinc-800 text-zinc-400">{{ item.duration_ms }}ms</td>
                <td class="p-2 border border-zinc-800 text-zinc-300">
                  {{ item.message || '-' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="p-3 bg-zinc-950 border-t border-zinc-800 flex items-center justify-between">
          <span class="text-[11px] text-zinc-500">耗时: {{ executionReport.duration_ms === null ? '未知' : (executionReport.duration_ms / 1000).toFixed(2) + ' 秒' }}</span>
          <div class="flex items-center gap-2">
            <button
              @click="downloadHtmlReport"
              class="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-zinc-950 font-semibold rounded text-xs transition-colors"
            >
              <Download class="w-3.5 h-3.5" />
              <span>{{ t('seq_report_download_html') }}</span>
            </button>
            <button
              @click="isReportModalOpen = false"
              class="px-3 py-1.5 bg-zinc-800 hover:bg-zinc-700 text-zinc-300 rounded text-xs transition-colors"
            >
              {{ t('seq_report_close') }}
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
