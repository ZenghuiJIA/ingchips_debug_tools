const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '..');
// Optional dependency directory supports read-only staged review; ordinary repo runs need no environment setting.
const dependencies = process.argv[2] || process.env.SERIAL_TEST_DEPENDENCIES || root;
const dependencyRequire = createRequire(path.join(dependencies, 'package.json'));
const ts = dependencyRequire('typescript');
const compiler = dependencyRequire('vue/compiler-sfc');
function source(file) { return fs.readFileSync(path.join(root, file), 'utf8'); }
function moduleFromSource(file, base = root) {
  const exports = {};
  const code = ts.transpileModule(fs.readFileSync(path.join(base, file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, { exports, require: dependencyRequire, TextDecoder, TextEncoder, Uint8Array, console });
  return exports;
}
function functions(file, names, context) {
  const script = compiler.parse(source(file)).descriptor.scriptSetup.content;
  const ast = ts.createSourceFile(file + '.ts', script, ts.ScriptTarget.Latest, true);
  const declarations = ast.statements.filter(s => ts.isFunctionDeclaration(s) && names.includes(s.name.text));
  assert.equal(declarations.length, names.length);
  const code = ts.transpileModule(declarations.map(s => s.getText(ast)).join('\n'), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.createContext(context);
  vm.runInContext(code, context);
  return context;
}
const appearance = moduleFromSource('src/utils/serialAppearance.ts');
const serialLog = moduleFromSource('src/utils/serialLog.ts', fs.existsSync(path.join(root, 'src/utils/serialLog.ts')) ? root : dependencies);
const sessionFile = 'src/components/SerialTerminalSession.vue';
const xtermFile = 'src/components/SerialXtermView.vue';
let passed = 0;
async function test(name, run) { await run(); passed++; console.log('PASS ' + name); }
function session() {
  const ticks = [];
  const page = { status: { session_id: 'session-1' }, cursor: 1, events: [], gap: false };
  const context = functions(sessionFile, ['renderCaptured', 'redrawCaptured', 'refreshCapture', 'flushLogQueue', 'scrollToBottom'], {
    backendJournal: { value: true }, capturePolling: false, props: { portName: 'COM_TEST' },
    captureSession: 'session-1', captureCursor: 1, retainedRaw: { value: [] }, logs: { value: [] },
    captureDecoder: new TextDecoder(), captureStatus: { value: null }, sessionMode: { value: 'log' },
    viewMode: { value: 'string' }, nextLogId: 1, pendingLogQueue: [], logFlushRafId: null,
    autoScroll: { value: true }, logContainer: { value: { scrollTop: 17, scrollHeight: 900 } },
    nextTick: callback => ticks.push(callback), cancelAnimationFrame: () => {},
    appendBoundedLog: serialLog.appendBoundedLog, appendLog: () => { throw new Error('Unexpected gap'); },
    safeInvoke: async command => { assert.equal(command, 'serial_capture_read'); return page; },
    TextDecoder, Uint8Array,
  });
  return { context, page, drain: () => { while (ticks.length) ticks.shift()(); }, ticks };
}
(async () => {
  await test('appearance persists only validated preferences and reloads across sessions', () => {
    const values = new Map();
    const storage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
    const custom = { fontFamily: 'Courier New, monospace', fontSize: 18.5, foreground: '#112233', background: '#445566', txColor: '#778899', infoColor: '#abcdef', errorColor: '#fedcba', isConnected: true };
    assert.equal(appearance.saveSerialAppearance(() => storage, custom), '');
    const restored = appearance.loadSerialAppearance(() => storage);
    assert.equal(restored.error, '');
    assert.equal(restored.appearance.fontSize, 18.5);
    assert.equal(restored.appearance.foreground, '#112233');
    assert.equal(restored.appearance.fontFamily, 'Courier New, monospace');
    assert.equal('isConnected' in JSON.parse(values.get(appearance.SERIAL_APPEARANCE_KEY)), false);
    for (const invalid of [null, [], 7, { fontSize: 0 }, { fontSize: 33 }, { fontSize: Infinity }, { fontSize: '20', foreground: 'red', background: 'url(x)', fontFamily: 'a; color:red' }]) {
      const value = appearance.normalizeSerialAppearance(invalid);
      assert.equal(value.fontSize, appearance.DEFAULT_SERIAL_APPEARANCE.fontSize);
      assert.equal(value.background, appearance.DEFAULT_SERIAL_APPEARANCE.background);
    }
    values.set(appearance.SERIAL_APPEARANCE_KEY, '{invalid');
    assert.notEqual(appearance.loadSerialAppearance(() => storage).error, '');
    const denied = () => { throw new Error('Storage blocked'); };
    assert.match(appearance.loadSerialAppearance(denied).error, /Storage blocked/);
    assert.match(appearance.saveSerialAppearance(denied, custom), /Storage blocked/);
  });
  await test('production style adapters apply font, size, background and directional colors', () => {
    const value = { ...appearance.DEFAULT_SERIAL_APPEARANCE, fontFamily: 'monospace', fontSize: 20, foreground: '#123456', background: '#234567' };
    assert.equal(appearance.serialLogStyle(value).fontSize, '20px');
    assert.equal(appearance.serialLogStyle(value).backgroundColor, '#234567');
    for (const [type, key] of [['rx', 'foreground'], ['tx', 'txColor'], ['info', 'infoColor'], ['error', 'errorColor']]) assert.equal(appearance.serialLogColor(value, type), value[key]);
    assert.equal(appearance.serialXtermOptions(value).fontFamily, 'monospace');
    assert.equal(appearance.serialXtermOptions(value).fontSize, 20);
    assert.equal(appearance.serialXtermOptions(value).theme.foreground, '#123456');
    assert.equal(appearance.serialXtermOptions(value).theme.background, '#234567');
  });
  await test('actual capture polling leaves manual scrollback alone for empty polls', async () => {
    const s = session();
    for (let i = 0; i < 5; i++) { await s.context.refreshCapture(); s.drain(); }
    assert.equal(s.context.logContainer.value.scrollTop, 17);
    assert.equal(s.ticks.length, 0);
  });
  await test('actual text and HEX capture paths follow only new messages, not history redraw', async () => {
    for (const mode of ['string', 'hex']) {
      const s = session();
      s.context.viewMode.value = mode;
      s.page.events = [{ data: '4142', direction: 'RX', wall_time_ms: 0 }];
      await s.context.refreshCapture();
      assert.equal(s.context.logContainer.value.scrollTop, 17, 'wait for DOM update');
      s.drain();
      assert.equal(s.context.logContainer.value.scrollTop, 900);
      assert.equal(s.context.logs.value[0].text, mode === 'hex' ? '41 42 ' : 'AB');
      s.context.logContainer.value.scrollTop = 24;
      s.page.events = [];
      await s.context.refreshCapture(); s.drain();
      assert.equal(s.context.logContainer.value.scrollTop, 24);
      s.context.redrawCaptured(); s.drain();
      assert.equal(s.context.logContainer.value.scrollTop, 24, 're-rendering history is not a new message');
      s.context.autoScroll.value = false;
      s.page.events = [{ data: '43', direction: 'RX', wall_time_ms: 1 }];
      await s.context.refreshCapture(); s.drain();
      assert.equal(s.context.logContainer.value.scrollTop, 24);
    }
  });
  await test('actual batched log flush follows when bounded retention no longer grows', () => {
    const s = session();
    s.context.logs.value = Array.from({ length: 1200 }, (_, id) => ({ id, text: 'old\n', type: 'rx', timestamp: '' }));
    s.context.pendingLogQueue = [{ id: 1201, text: 'new\n', type: 'rx', timestamp: '' }];
    s.context.flushLogQueue(); s.drain();
    assert.equal(s.context.logContainer.value.scrollTop, 900);
    s.context.logContainer.value.scrollTop = 8;
    s.context.flushLogQueue(); s.drain();
    assert.equal(s.context.logContainer.value.scrollTop, 8);
    s.context.pendingLogQueue = [{ id: 1202, text: 'next\n', type: 'rx', timestamp: '' }];
    s.context.flushLogQueue();
    s.context.autoScroll.value = false;
    s.drain();
    assert.equal(s.context.logContainer.value.scrollTop, 8, 'honor unchecked checkbox before queued DOM update');
  });
  await test('actual xterm receive function follows asynchronously and respects disabled/disposed state', () => {
    let callback;
    let followed = 0;
    const restored = [];
    const term = { buffer: { active: { viewportY: 17 } }, write: (bytes, cb) => { assert.equal(bytes.length, 2); callback = cb; }, scrollToBottom: () => followed++, scrollToLine: line => restored.push(line) };
    const context = functions(xtermFile, ['writeRawBytes'], { term, props: { autoScroll: true }, writeSerialOutput: appearance.writeSerialOutput });
    context.writeRawBytes(new Uint8Array([65, 66]));
    assert.equal(followed, 0); callback(); assert.equal(followed, 1);
    assert.equal(followed, 1, 'idle time has no follow operation');
    context.props.autoScroll = false;
    context.writeRawBytes(new Uint8Array([65, 66])); callback();
    assert.equal(followed, 1); assert.deepEqual(restored, [17]);
    callback = null;
    context.writeRawBytes(new Uint8Array()); assert.equal(callback, null);
    context.props.autoScroll = true;
    context.writeRawBytes(new Uint8Array([65, 66])); context.term = null; callback();
    assert.equal(followed, 1);
  });
  await test('both production SFC templates compile and wire the shared display settings', () => {
    for (const file of [sessionFile, xtermFile]) {
      const { descriptor, errors } = compiler.parse(source(file));
      assert.equal(errors.length, 0);
      const script = compiler.compileScript(descriptor, { id: 'serial-test' });
      const compiled = compiler.compileTemplate({ source: descriptor.template.content, filename: file, id: 'serial-test', compilerOptions: { bindingMetadata: script.bindings } });
      assert.deepEqual(compiled.errors, []);
    }
    assert.match(source(sessionFile), /:appearance="appearance"/);
    assert.match(source(sessionFile), /:auto-scroll="autoScroll"/);
    assert.match(source(sessionFile), /:style="logAppearanceStyle"/);
    assert.match(source(sessionFile), /serialLogColor\(appearance, item.type\)/);
    assert.doesNotMatch(source(xtermFile), /background-color:.*!important/);
  });
  console.log(`Serial appearance/scroll production regression: ${passed} passed`);
})().catch(error => { console.error(error); process.exitCode = 1; });
