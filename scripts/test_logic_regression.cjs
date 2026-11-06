const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
const dependencyRoot = process.argv[2] || root;
const dependencyRequire = require('node:module').createRequire(path.join(dependencyRoot, 'package.json'));
const ts = dependencyRequire('typescript');
function sourcePath(file) { const candidate = path.join(root, file); return fs.existsSync(candidate) ? candidate : path.join(dependencyRoot, file); }
let passed = 0;
function moduleFromSource(file) {
  const code = ts.transpileModule(fs.readFileSync(sourcePath(file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, require, TextEncoder, TextDecoder, Uint8Array, console });
  return exports;
}
function functions(file, names, context) {
  const source = fs.readFileSync(sourcePath(file), 'utf8').split('<script setup lang="ts">')[1].split('</script>')[0];
  const ast = ts.createSourceFile(file + '.ts', source, ts.ScriptTarget.Latest, true);
  const selected = ast.statements.filter(s => ts.isFunctionDeclaration(s) && names.includes(s.name.text));
  assert.equal(selected.length, names.length);
  const code = ts.transpileModule(selected.map(s => s.getText(ast)).join('\n'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.createContext(context);
  vm.runInContext(code, context);
  return context;
}
async function test(name, run) { await run(); passed++; console.log('PASS ' + name); }
const contracts = moduleFromSource('src/utils/hardwareContracts.ts');
const { encodeCommand } = moduleFromSource('src/utils/commandEncoder.ts');
const { H4Decoder, buildDtmCommand, DTM_TEST_END } = moduleFromSource('src/utils/bleProtocol.ts');
const { readMemoryRange } = moduleFromSource('src/utils/memorySnapshot.ts');
const { parseTelemetryLine } = moduleFromSource('src/utils/telemetryParser.ts');
const { TriggerMatcher } = moduleFromSource('src/utils/serialLog.ts');
const hilPlan = moduleFromSource('src/utils/hilPlan.ts');

(async () => {
  await test('production telemetry parser accepts CSV/KV/JSON and rejects text logs', () => {
    assert.equal(JSON.stringify(parseTelemetryLine('12.5, -7.8')), '{"CH0":12.5,"CH1":-7.8}');
    assert.equal(parseTelemetryLine('roll:12.3, pitch:-45.6').pitch, -45.6);
    assert.equal(parseTelemetryLine('{"voltage":3.3}').voltage, 3.3);
    assert.equal(parseTelemetryLine('[INFO] Application started at 115200'), null);
  });
  await test('production trigger matcher respects one-shot and disabled rules', () => {
    const rule = { enabled: true, matchType: 'contains', matchPattern: 'READY', mode: 'once', hits: 0 };
    const context = functions('src/components/TriggerPanel.vue', ['checkAndMatchTriggers'], { rules: { value: [rule] }, matcher: new TriggerMatcher() });
    assert.equal(context.checkAndMatchTriggers('READY').length, 1);
    assert.equal(context.checkAndMatchTriggers('READY').length, 0);
    assert.equal(rule.hits, 1);
  });
  await test('negations/questions/incomplete writes never execute hardware', () => {
    for (const input of ['不要复位', '怎样复位单片机？', '不要写内存 0x20000000', '写入 RAM 内存 0x20000000', 'write memory 0x20000000']) {
      assert.equal(contracts.parseHardwareIntent(input), null);
    }
    assert.equal(contracts.parseHardwareIntent('复位单片机并重启').action, 'reset');
    assert.throws(() => contracts.parseHardwareIntent('write memory 0x20000001 0x12'));
  });
  await test('actual command encoder rejects malformed HEX and encodes CRLF', () => {
    assert.throws(() => encodeCommand({ format: 'hex', payload: 'ab0' }));
    assert.throws(() => encodeCommand({ format: 'hex', payload: 'xz' }));
    assert.equal(JSON.stringify(encodeCommand({ format: 'string', payload: 'AT', lineEnding: 'crlf' }).bytes), '[65,84,13,10]');
  });
  await test('legacy DTM golden vectors and unsupported capabilities', () => {
    assert.equal(JSON.stringify(buildDtmCommand('tx', 0, 37, '1111', '1M')), '[128,149]');
    assert.equal(JSON.stringify(buildDtmCommand('rx', 39, 0, 'prbs9', '1M')), '[103,0]');
    assert.equal(JSON.stringify(DTM_TEST_END), '[192,0]');
    assert.throws(() => buildDtmCommand('tx', 0, 64, 'prbs9', '1M'));
    assert.throws(() => buildDtmCommand('tx', 0, 37, 'prbs9', '2M'));
    assert.throws(() => buildDtmCommand('tx', 0, 37, 'single_carrier', '1M'));
  });
  await test('H4 split headers/payloads and coalesced frames at every byte boundary', () => {
    const input = [4, 0x3e, 1, 2, 4, 0x0e, 0, 2, 1, 0, 2, 0, 0xaa, 0xbb];
    for (let split = 0; split <= input.length; split++) {
      const decoder = new H4Decoder();
      const frames = [...decoder.push(Uint8Array.from(input.slice(0, split))), ...decoder.push(Uint8Array.from(input.slice(split)))];
      assert.equal(frames.length, 3);
      assert.equal(JSON.stringify(frames.flatMap(f => Array.from(f))), JSON.stringify(input));
    }
  });
  await test('16 KB snapshot reads all four pages and rejects short reads', async () => {
    const addresses = [];
    const bytes = await readMemoryRange(async (_, args) => {
      addresses.push(args.address);
      return { bytes: Array(args.count).fill(addresses.length) };
    }, 0x20000000, 16384, 'probe');
    assert.equal(bytes.length, 16384);
    assert.equal(bytes[16383], 4);
    assert.equal(addresses[3], '0x20003000');
    await assert.rejects(readMemoryRange(async () => ({ bytes: [1] }), 0x20000000, 4096, 'probe'));
  });
  await test('Sequencer submits a validated frozen snapshot to the shared runner', async () => {
    const pipeline = { name: 'test', version: '2', loop_count: 1, stop_on_error: true, steps: [
      { id: 'delay', name: 'delay', action: 'delay', enabled: true, params: { delay_ms: 50 } },
    ] };
    const calls = [];
    const seq = functions('src/components/HilTestSequencer.vue', ['runPipeline'], {
      ...hilPlan, pipeline: { value: pipeline }, isRunning: { value: false }, isTauri: () => true,
      isSubmitting: { value: false }, isStopping: { value: false }, disposed: false,
      rememberRun() {}, runGeneration: new hilPlan.HilRunGeneration(), executionReport: { value: null },
      cancellationDetail: { value: '' }, activeStepId: { value: '' },
      selectedStep: { value: pipeline.steps[0] }, addLog() {}, clearLogs() {}, stepResults: { value: {} },
      eventCursor: 0, serialViews: new Map(), runId: { value: '' }, reportDir: { value: '' },
      runState: { value: '' }, sessionStorage: { setItem() {} }, pollTimer: null, pollRun: async () => {},
      hilCall: async (op, args) => {
        calls.push({ op, args });
        if (op === 'validate_hiltest') pipeline.steps[0].params.delay_ms = 999;
        return { run_id: 'job', report_dir: 'reports/job', state: 'QUEUED' };
      },
    });
    await seq.runPipeline(false);
    assert.equal(calls[0].op, 'validate_hiltest');
    assert.equal(calls[1].op, 'run_hiltest');
    assert.equal(calls[1].args.document.steps[0].params.delay_ms, 50);
    assert.equal(seq.isRunning.value, true);
  });
  await test('Sequencer validation rejection never starts hardware', async () => {
    const calls = [];
    const seq = functions('src/components/HilTestSequencer.vue', ['runPipeline'], {
      ...hilPlan, pipeline: { value: { steps: [] } }, isRunning: { value: false }, isTauri: () => true,
      isSubmitting: { value: false }, isStopping: { value: false }, disposed: false,
      addLog() {}, hilCall: async op => { calls.push(op); throw new Error('invalid target'); },
    });
    await seq.runPipeline(false);
    assert.deepEqual(calls, ['validate_hiltest']);
    assert.equal(seq.isRunning.value, false);
  });
  await test('memory writes freeze snapshot target across await and reject stale selection', async () => {
    const calls = [];
    const ctx = functions('src/components/MemoryInspector.vue', ['commitEditChunk'], {
      ...contracts, editingStartIndex: { value: 0 }, editingChunkSize: { value: 2 }, editingValue: { value: '1234' },
      isWritingByte: { value: false }, isLoading: { value: false }, snapshot: { value: { address: 0x20000000, probeId: 'A', frequency: 1000000 } },
      addressInput: { value: '0x20000000' }, selectedProbeId: { value: 'A' }, memoryBytes: { value: [0, 0] }, previousBytes: { value: [0, 0] },
      alert() {}, t: key => key,
      safeInvoke: async (_, args) => { calls.push(args); ctx.addressInput.value = '0x20001000'; ctx.selectedProbeId.value = 'B'; },
    });
    await ctx.commitEditChunk();
    assert.equal(calls[1].address, '0x20000001');
    assert.equal(calls[1].probeId, 'A');
    ctx.editingStartIndex.value = 0; ctx.editingValue.value = '1234';
    await ctx.commitEditChunk();
    assert.equal(calls.length, 2);
  });
  await test('Sequencer prepares schema v2 losslessly and leaves duration/default validation to backend', () => {
    const raw = {
      schema_version: 2, name: 'sample', bench: { port_name: 'COM_EXPLICIT', baud_rate: 115200, probe_id: 'PROBE_EXPLICIT', target_device: 'ing2000' },
      steps: [
        { id: 'capture', action: 'serial_open' },
        { id: 'flash', action: 'flash_firmware', timeout_ms: '5m', params: { file_path: 'firmware.hex' } },
        { id: 'observe', action: 'hil_observe', timeout_ms: '23h', params: { boot_timeout_ms: '5s' } },
      ],
    };
    const normalized = hilPlan.normalizePipeline(raw);
    assert.equal(normalized.steps.length, raw.steps.length);
    assert.equal(normalized.steps[0].name, 'capture');
    assert.equal(normalized.steps[0].enabled, true);
    assert.equal(normalized.steps[0].params.port_name, undefined);
    assert.equal(normalized.steps[0].params.baud_rate, undefined);
    assert.equal(normalized.steps[0].params.probe_id, undefined);
    assert.equal(normalized.bench.port_name, 'COM_EXPLICIT');
    assert.equal(normalized.steps[1].timeout_ms, '5m');
    assert.equal(normalized.steps[2].timeout_ms, '23h');
    assert.equal(normalized.steps[2].params.boot_timeout_ms, '5s');
    assert.equal(raw.steps[0].params, undefined, 'input must not mutate');
    const legacy = hilPlan.normalizePipeline({ steps: [{ action: 'swd_read_assert', params: { expected_value: '0010' } }] });
    assert.equal(legacy.schema_version, undefined);
    assert.equal(legacy.steps[0].params.expected_value, '0010');
  });
  console.log(`${passed} regression checks passed (no hardware accessed).`);
})().catch(error => { console.error(error); process.exitCode = 1; });
