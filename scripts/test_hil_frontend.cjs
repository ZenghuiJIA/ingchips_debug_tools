const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '..');
const dependencyRoot = process.argv[2] || root;
const dependencyRequire = createRequire(path.join(dependencyRoot, 'package.json'));
const ts = dependencyRequire('typescript');
const compiler = dependencyRequire('vue/compiler-sfc');
const file = 'src/components/HilTestSequencer.vue';
function source(name) { return fs.readFileSync(path.join(root, name), 'utf8'); }
function productionModule(name) {
  const exports = {};
  const code = ts.transpileModule(source(name), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.runInNewContext(code, { exports, require: key => { if (key === './ipc') return { safeInvoke: () => { throw new Error('Unexpected hardware boundary'); } }; return dependencyRequire(key); } });
  return exports;
}
const plan = productionModule('src/utils/hilPlan.ts');
const client = productionModule('src/utils/hilClient.ts');
function functions(names, context) {
  const text = compiler.parse(source(file)).descriptor.scriptSetup.content;
  const ast = ts.createSourceFile('sequencer.ts', text, ts.ScriptTarget.Latest, true);
  const statements = ast.statements.filter(s => ts.isFunctionDeclaration(s) && names.includes(s.name.text));
  assert.equal(statements.length, names.length);
  const code = ts.transpileModule(statements.map(s => s.getText(ast)).join('\n'), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.createContext(context); vm.runInContext(code, context);
  return context;
}
function deferred() { let resolve, reject; const promise = new Promise((r, j) => { resolve = r; reject = j; }); return { promise, resolve, reject }; }
const ref = value => ({ value });
function document() { return { schema_version: 2, name: 'plan', version: '2', loop_count: 1, stop_on_error: true, bench: {}, steps: [{ id: 'send', name: 'send', action: 'serial_send', enabled: true, params: { port_name: 'COM_EXPLICIT', send_data: 'QUERY', character_delay_ms: 15 } }] }; }
function harness(names, overrides = {}) {
  const logs = [], timers = [], stored = new Map();
  const generation = new plan.HilRunGeneration(); generation.next();
  const context = {
    ...plan, pipeline: ref(document()), selectedStep: ref(null), selectedStepId: ref(null),
    isSubmitting: ref(false), isRunning: ref(false), isStopping: ref(false), disposed: false,
    runId: ref(''), runState: ref(''), cancellationDetail: ref(''), reportDir: ref(''), activeStepId: ref(''),
    stepResults: ref({}), executionReport: ref(null), isReportModalOpen: ref(false),
    eventCursor: 0, pollTimer: undefined, serialViews: new Map(), currentLoopIndex: ref(0),
    runGeneration: generation, isTauri: () => true, displayReport: client.displayReport,
    isHilSubmissionRejected: client.isHilSubmissionRejected,
    addLog: (text, status) => logs.push({ text, status }), clearLogs: () => { logs.length = 0; },
    rememberRun: (key, value) => value === undefined ? stored.delete(key) : stored.set(key, value),
    setTimeout: (fn, ms) => { const timer = { fn, ms }; timers.push(timer); return timer; },
    clearTimeout: timer => { const i = timers.indexOf(timer); if (i >= 0) timers.splice(i, 1); },
    TextDecoder, Uint8Array, console,
    hilCall: async () => { throw new Error('Unexpected RPC'); }, pollRun: async () => {},
    ...overrides,
  };
  return { context: functions(names, context), logs, timers, stored };
}
const pollFunctions = ['isCurrentRun', 'receiveRunEvent', 'pollRun'];
const row = (id, status) => ({ step_id: id, step_name: id, status, duration_ms: 1, timestamp: '' });
function report(extra = {}) { return { pipeline_name: 'test', state: 'PASS', start_time: 1, end_time: 2, report_dir: 'reports/r', planned_steps: 1, executed_steps: 1, skipped_steps: 0, attempt_count: 1, passed_steps: 1, failed_steps: 0, cancelled_steps: 0, hardware_verified: false, results: [row('send', 'pass')], ...extra }; }
let passed = 0;
async function test(name, run) { await run(); console.log('PASS ' + name); passed++; }
(async () => {
  await test('production normalizer preserves nested/legacy/unknown parameters without action defaults', () => {
    const raw = { name: 'legacy', steps: [{ id: 'outer', action: 'repeat', params: { count: 2, unsupported: 'must reach validator' }, steps: [{ id: 'nested', action: 'serial.send', params: { character_delay_ms: 21, send_data: 'X' }, timeout_ms: '5s' }, { id: 'read', action: 'swd_read_assert', params: { expected_value: '0010' } }] }] };
    const normalized = plan.normalizePipeline(raw);
    assert.equal(normalized.schema_version, undefined);
    assert.equal(normalized.steps[0].action, 'repeat');
    assert.equal(normalized.steps[0].params.unsupported, 'must reach validator');
    assert.equal(normalized.steps[0].steps[0].params.character_delay_ms, 21);
    assert.equal(normalized.steps[0].steps[0].timeout_ms, '5s');
    assert.equal(normalized.steps[0].steps[1].params.expected_value, '0010');
    assert.equal(normalized.steps[0].steps[0].params.port_name, undefined);
    assert.equal(raw.steps[0].name, undefined);
    assert.throws(() => plan.normalizePipeline({ steps: [{ id: 'x', action: 'delay', steps: [{ id: 'x', action: 'delay' }] }] }), /重复/);
    assert.throws(() => plan.normalizePipeline({ bench: 'relative.json', steps: [] }), /bench/);
  });
  await test('production snapshot isolates single-step selection including nested content', () => {
    const raw = document(); raw.steps[0].enabled = false; raw.steps[0].steps = [{ id: 'child', action: 'delay', params: { delay_ms: '2s' } }];
    const snapshot = plan.pipelineSnapshot(raw, 'send');
    raw.steps[0].params.character_delay_ms = 99;
    assert.equal(snapshot.steps[0].enabled, true); assert.equal(raw.steps[0].enabled, false);
    assert.equal(snapshot.steps[0].params.character_delay_ms, 15);
    assert.equal(snapshot.steps[0].steps[0].params.delay_ms, '2s');
    assert.throws(() => plan.pipelineSnapshot(raw, 'gone'), /不存在/);
  });
  await test('actual runPipeline locks before await and sends one lossless frozen snapshot', async () => {
    const gate = deferred(), calls = [];
    const h = harness(['runPipeline'], { hilCall: async (op, args) => { calls.push({ op, args }); if (op === 'validate_hiltest') await gate.promise; return { run_id: 'r', state: 'QUEUED', report_dir: 'reports/r' }; } });
    h.context.selectedStep.value = h.context.pipeline.value.steps[0];
    const first = h.context.runPipeline(false);
    assert.equal(h.context.isSubmitting.value, true);
    await h.context.runPipeline(true);
    h.context.pipeline.value.steps[0].params.character_delay_ms = 99;
    gate.resolve(); await first;
    assert.deepEqual(calls.map(x => x.op), ['validate_hiltest', 'run_hiltest']);
    assert.equal(calls[1].args.document.steps[0].params.character_delay_ms, 15);
    assert.equal(h.context.isSubmitting.value, false); assert.equal(h.context.isRunning.value, true);
    assert.equal(h.stored.get('hil.activeRun'), 'r'); assert.equal(h.stored.has('hil.submissionUnknown'), false);
  });
  await test('validation rejection unlocks but uncertain submission never allows duplicate hardware dispatch', async () => {
    const validate = harness(['runPipeline'], { hilCall: async () => { throw new Error('invalid action parameter'); } });
    await validate.context.runPipeline();
    assert.equal(validate.context.isSubmitting.value, false); assert.equal(validate.context.isRunning.value, false);
    let starts = 0;
    const unknown = harness(['runPipeline'], { hilCall: async op => { if (op === 'run_hiltest') { starts++; throw new Error('transport lost'); } return {}; } });
    await unknown.context.runPipeline(); await unknown.context.runPipeline();
    assert.equal(starts, 1); assert.equal(unknown.context.runState.value, 'UNKNOWN');
    assert.equal(unknown.context.isRunning.value, true); assert.equal(unknown.context.isSubmitting.value, false);
    assert.equal(unknown.stored.get('hil.submissionUnknown'), 'true');
  });
  await test('only exact pre-start rejection unlocks submission, blocks concurrent start and allows corrected retry', async () => {
    assert.equal(client.isHilSubmissionRejected('HIL_NOT_STARTED: busy'), true);
    for (const error of ['transport: HIL_NOT_STARTED: busy', 'HIL_NOT_STARTED:busy', new Error('HIL_NOT_STARTED: busy'), { message: 'HIL_NOT_STARTED: busy' }, null]) {
      assert.equal(client.isHilSubmissionRejected(error), false);
    }
    const gate = deferred(), entered = deferred(); let starts = 0;
    const h = harness(['runPipeline'], { hilCall: async op => {
      if (op === 'validate_hiltest') return { valid: true };
      starts++;
      if (starts === 1) { entered.resolve(); return gate.promise; }
      return { run_id: 'retry', state: 'QUEUED', report_dir: 'reports/retry' };
    } });
    const first = h.context.runPipeline(); await entered.promise;
    await h.context.runPipeline(); assert.equal(starts, 1);
    gate.reject('HIL_NOT_STARTED: resource busy'); await first;
    assert.equal(h.context.runState.value, 'REJECTED'); assert.equal(h.context.isRunning.value, false);
    assert.equal(h.context.isSubmitting.value, false); assert.equal(h.stored.has('hil.submissionUnknown'), false);
    await h.context.runPipeline();
    assert.equal(starts, 2); assert.equal(h.context.isRunning.value, true); assert.equal(h.context.runId.value, 'retry');
    const ambiguous = harness(['runPipeline'], { hilCall: async op => { if (op === 'run_hiltest') throw 'transport: HIL_NOT_STARTED: text from remote'; return {}; } });
    await ambiguous.context.runPipeline();
    assert.equal(ambiguous.context.runState.value, 'UNKNOWN'); assert.equal(ambiguous.context.isRunning.value, true);
  });
  await test('actual final poll drains more than 200 events with bounded scheduling before report/unlock', async () => {
    let reports = 0;
    const events = Array.from({ length: 1001 }, (_, i) => ({ seq: i + 1, kind: 'log', time: i, line: 'line-' + (i + 1) }));
    const h = harness(pollFunctions, { runId: ref('r'), isRunning: ref(true), hilCall: async (op, args) => {
      assert.equal(args.run_id, 'r');
      if (op === 'get_hiltest_status') return { run_id: 'r', state: 'PASS', done: true, report_dir: 'reports/r' };
      if (op === 'get_hiltest_events') { const batch = events.filter(e => e.seq > args.after).slice(0, args.limit); return { events: batch, cursor: batch.at(-1)?.seq ?? args.after }; }
      if (op === 'get_hiltest_report') { reports++; return report(); }
      throw new Error(op);
    } });
    await h.context.pollRun('r', 1);
    assert.equal(h.context.eventCursor, 800); assert.equal(reports, 0); assert.equal(h.context.isRunning.value, true);
    assert.equal(h.timers.length, 1); assert.equal(h.timers[0].ms, 0);
    await h.timers.shift().fn();
    assert.equal(h.context.eventCursor, 1001); assert.equal(reports, 1);
    assert.ok(h.logs.some(x => x.text === 'line-1001'));
    assert.equal(h.context.isRunning.value, false); assert.equal(h.context.isReportModalOpen.value, true);
  });
  await test('actual poll keeps running while final report is pending and through RPC failure', async () => {
    const gate = deferred();
    const h = harness(pollFunctions, { runId: ref('r'), isRunning: ref(true), hilCall: async (op, args) => {
      if (op === 'get_hiltest_status') return { run_id: 'r', state: 'PASS', done: true, report_dir: 'reports/r' };
      if (op === 'get_hiltest_events') return { events: [], cursor: args.after };
      return gate.promise;
    } });
    const pending = h.context.pollRun('r', 1);
    await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
    assert.equal(h.context.isRunning.value, true);
    gate.reject(new Error('report not yet available')); await pending;
    assert.equal(h.context.isRunning.value, true); assert.equal(h.context.runState.value, 'UNKNOWN');
    assert.equal(h.context.isReportModalOpen.value, false); assert.equal(h.timers.length, 1);
  });
  await test('late status, event and report responses cannot mutate a newer run generation', async () => {
    for (const paused of ['get_hiltest_status', 'get_hiltest_events', 'get_hiltest_report']) {
      const gate = deferred(), entered = deferred();
      const h = harness(pollFunctions, { runId: ref('old'), isRunning: ref(true), hilCall: async (op, args) => {
        if (op === paused) { entered.resolve(); return gate.promise; }
        if (op === 'get_hiltest_status') return { run_id: 'old', state: 'PASS', done: true, report_dir: 'old' };
        if (op === 'get_hiltest_events') return { events: [], cursor: args.after };
        return report();
      } });
      const pending = h.context.pollRun('old', 1); await entered.promise;
      h.context.runId.value = 'new'; h.context.runState.value = 'RUNNING'; h.context.runGeneration.next();
      gate.resolve(paused === 'get_hiltest_status' ? { run_id: 'old', state: 'FAIL', done: true } : paused === 'get_hiltest_events' ? { events: [{ seq: 1, line: 'stale' }], cursor: 1 } : report());
      await pending;
      assert.equal(h.context.runState.value, 'RUNNING'); assert.equal(h.context.isRunning.value, true);
      assert.equal(h.context.executionReport.value, null); assert.equal(h.timers.length, 0);
      assert.equal(h.logs.some(x => x.text === 'stale'), false);
    }
  });
  await test('actual stop binds target and blocks duplicate stop while preserving uncertain state', async () => {
    const gate = deferred(); let calls = 0, polls = 0;
    const h = harness(['isCurrentRun', 'stopPipeline'], { runId: ref('r'), isRunning: ref(true), pollRun: async () => { polls++; }, hilCall: async (op, args) => { calls++; assert.equal(op, 'stop_hiltest'); assert.equal(args.run_id, 'r'); return gate.promise; } });
    const pending = h.context.stopPipeline(); await h.context.stopPipeline();
    assert.equal(calls, 1); assert.equal(h.context.isStopping.value, true);
    gate.reject(new Error('stop response lost')); await pending;
    assert.equal(h.context.runState.value, 'UNKNOWN'); assert.equal(h.context.isRunning.value, true);
    assert.equal(h.context.isStopping.value, false); assert.equal(polls, 1);
  });
  await test('actual recovery only queries a recorded run and never releases an unknown submission guard', () => {
    const polls = [];
    const h = harness(['restoreStoredRun'], { isRunning: ref(true), runState: ref('UNKNOWN'), sessionStorage: { getItem: () => null }, pollRun: async (id, token) => { polls.push({ id, token }); } });
    h.context.restoreStoredRun();
    assert.equal(polls.length, 0); assert.equal(h.context.isRunning.value, true);
    h.context.sessionStorage.getItem = () => 'recovered';
    h.context.restoreStoredRun();
    assert.equal(h.context.runId.value, 'recovered'); assert.equal(h.context.isRunning.value, true);
    assert.equal(polls.length, 1); assert.equal(polls[0].id, 'recovered');
    assert.match(source(file), /if \(runId.value\) \{\s*isRunning.value = true;/);
    assert.match(source(file), /onMounted\(async \(\) => \{\s*if \(runId.value\) restoreStoredRun\(\);\s*await refreshPorts/);
  });
  await test('actual source/file import exposes validation errors and never replaces document on failure', async () => {
    const h = harness(['applySource', 'importPipelineText'], { sourceText: ref(JSON.stringify(document())), sourceError: ref(''), sourceVisible: ref(true), sourceApplying: ref(false), importError: ref(''), isImporting: ref(false), hilCall: async () => { throw new Error('unsupported field'); } });
    const original = h.context.pipeline.value;
    await h.context.applySource();
    assert.equal(h.context.sourceVisible.value, true); assert.match(h.context.sourceError.value, /unsupported field/);
    assert.equal(h.context.sourceApplying.value, false); assert.equal(h.context.pipeline.value, original);
    await h.context.importPipelineText('{broken');
    assert.match(h.context.importError.value, /工程未导入/); assert.equal(h.context.pipeline.value, original);
    h.context.hilCall = async () => ({ valid: true });
    const legacy = { name: 'legacy', steps: [{ action: 'serial.send', params: { character_delay_ms: 9 }, timeout_ms: '3s' }] };
    await h.context.importPipelineText(JSON.stringify(legacy));
    assert.equal(h.context.pipeline.value.schema_version, undefined);
    assert.equal(h.context.pipeline.value.steps[0].params.character_delay_ms, 9);
    assert.equal(h.context.pipeline.value.steps[0].params.port_name, undefined);
  });
  await test('actual templates never guess COM1/first port and initial example contains no hardware operation', () => {
    const h = harness(['addStepFromTemplate', 'loadDemoPipeline', 'loadSerialTemplate', 'loadHilTemplate'], { availablePorts: ref([{ port_name: 'COM_UNRELATED' }]), t: key => key });
    h.context.addStepFromTemplate({ action: 'serial_open', nameKey: 'open', defaultParams: { port_name: '', baud_rate: 115200 } });
    assert.equal(h.context.pipeline.value.steps.at(-1).params.port_name, '');
    h.context.loadDemoPipeline(); assert.equal(h.context.pipeline.value.steps.every(s => s.action === 'delay'), true);
    h.context.loadSerialTemplate(); assert.deepEqual(Array.from(h.context.pipeline.value.steps, s => s.action), ['serial_open', 'serial_send', 'serial_wait_match']);
    assert.equal(h.context.pipeline.value.steps[1].params.send_data, '');
    h.context.loadHilTemplate(); assert.equal(h.context.pipeline.value.steps.some(s => ['reset_target', 'flash_firmware'].includes(s.action)), false);
  });
  await test('production report uses plan denominator, separates retry attempts and keeps legacy/hardware uncertainty', () => {
    const current = client.displayReport(report({ planned_steps: 5, executed_steps: 2, skipped_steps: 3, attempt_count: 3, passed_steps: 1, failed_steps: 1, results: [row('a', 'fail'), row('a', 'pass'), row('b', 'fail')] }));
    assert.equal(current.success_rate, 20); assert.equal(current.attempt_count, 3); assert.equal(current.failed_steps, 1);
    assert.equal(current.hardware_verified, false);
    const legacy = client.displayReport({ state: 'PASS', start_time: 1, end_time: 2, report_dir: 'old', results: [row('one', 'pass')] });
    assert.equal(legacy.success_rate, null); assert.equal(legacy.planned_steps, null); assert.equal(legacy.hardware_verified, null);
    assert.match(legacy.statistics_note, /未知/);
    assert.equal(client.displayReport(report({ planned_steps: -1 })).success_rate, null);
    assert.equal(client.displayReport(report({ skipped_steps: 2 })).success_rate, null);
    assert.equal(client.displayReport(report({ planned_steps: 0, executed_steps: 0, passed_steps: 0, attempt_count: 0 })).success_rate, null);
    const cancelled = client.displayReport(report({ state: 'CANCELLED', planned_steps: 3, executed_steps: 1, passed_steps: 0, cancelled_steps: 1, skipped_steps: 2 }));
    assert.equal(cancelled.success_rate, 0); assert.equal(cancelled.cancelled_steps, 1);
  });
  await test('failed retry then cancellation may overlap backend counters without inventing unknown rate', () => {
    const result = client.displayReport(report({ state: 'CANCELLED', planned_steps: 3, executed_steps: 1, skipped_steps: 2, passed_steps: 0, failed_steps: 1, cancelled_steps: 1, attempt_count: 2, results: [row('send', 'fail'), row('send', 'cancelled')] }));
    assert.equal(result.success_rate, 0); assert.equal(result.failed_steps, 1); assert.equal(result.cancelled_steps, 1);
    assert.equal(result.attempt_count, 2); assert.equal(result.hardware_verified, false);
    assert.equal(client.displayReport(report({ executed_steps: 1, failed_steps: 2 })).success_rate, null);
  });
  await test('actual HIL SFC compiles and exposes complete serial/bench/report controls', () => {
    const { descriptor, errors } = compiler.parse(source(file)); assert.deepEqual(errors, []);
    const script = compiler.compileScript(descriptor, { id: 'hil-test' });
    const template = compiler.compileTemplate({ source: descriptor.template.content, filename: file, id: 'hil-test', compilerOptions: { bindingMetadata: script.bindings } });
    assert.deepEqual(template.errors, []);
    for (const binding of ['pipeline.bench!.baud_rate', 'pipeline.bench!.pack_path', 'pipeline.bench!.frequency', 'selectedStep.params.character_delay_ms', 'sourceError', 'importError', 'executionReport.attempt_count', 'executionReport.hardware_verified']) assert.ok(source(file).includes(binding), binding);
    assert.doesNotMatch(source(file), /allowedMap|availablePorts\.value\[0\]|'COM1'/);
  });
  console.log(`HIL frontend production regression: ${passed} passed (no hardware accessed)`);
})().catch(error => { console.error(error); process.exitCode = 1; });
