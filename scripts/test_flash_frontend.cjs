// Exercise the production SFC setup and request builder without Tauri/hardware.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const { parse, compileTemplate } = require('vue/compiler-sfc');
const source = fs.readFileSync(path.resolve(__dirname, '../src/components/IngSerialFlasher.vue'), 'utf8');
const { descriptor, errors } = parse(source);
assert.deepEqual(errors, []);
const ast = ts.createSourceFile('IngSerialFlasher.ts', descriptor.scriptSetup.content, ts.ScriptTarget.Latest, true);
const code = ts.transpileModule(ast.statements.filter(s => !ts.isImportDeclaration(s))
  .map(s => s.getText(ast)).join('\n') + '\nglobalThis.testApi = { startFlash, mode, singlePath, manualBoot };',
  { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
const calls = [];
const watchers = [];
const storageReads = [];
const context = {
  console, Date,
  ref: value => ({ value }),
  watch: (source, callback) => watchers.push({ source, callback }),
  onMounted: () => {}, onUnmounted: () => {},
  defineProps: () => ({ tabId: 'test-tab', portName: 'MOCK-PORT', isOpen: true }),
  defineEmits: () => () => {},
  localStorage: {
    getItem(key) { storageReads.push(key); return key.includes('manual_boot') ? 'false' : null; },
    setItem() {},
  },
  t: key => key,
  crypto: { randomUUID: () => 'mock-flash-job' },
  alert: text => { throw new Error(text); },
  safeInvoke: async (name, payload) => calls.push({ name, payload }),
};
vm.createContext(context);
vm.runInContext(code, context);

(async () => {
  const api = context.testApi;
  assert.equal(api.manualBoot.value, false);
  watchers.find(w => Array.isArray(w.source)).callback(['new-tab', 'MOCK-PORT-2']);
  api.mode.value = 'single';
  api.singlePath.value = 'mock-firmware.bin';
  await api.startFlash();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].name, 'ing_start_flash');
  assert.equal(calls[0].payload.request.manual_boot, false);
  assert.equal(calls[0].payload.request.timeout_sec, 15);

  const template = compileTemplate({ source: descriptor.template.content, filename: 'IngSerialFlasher.vue', id: 'test' });
  assert.deepEqual(template.errors, []);
  function nodes(node) { return [node, ...[...(node.children || []), ...(node.branches || [])].flatMap(nodes)]; }
  const elements = nodes(template.ast);
  const checkbox = elements.find(n => n.tag === 'input' && n.props.some(p => p.name === 'aria-describedby' && p.value?.content === 'ing-boot-policy'));
  assert.ok(checkbox, 'Manual boot control checkbox exists and enabled');
  assert.ok(!checkbox.props.some(p => p.type === 6 && p.name === 'disabled'), 'Must not be disabled');
  assert.ok(elements.some(n => n.tag === 'p' && n.props.some(p => p.name === 'id' && p.value?.content === 'ing-boot-policy')),
    'Policy notice must be present');
  console.log('PASS production ING flash UI: automatic reset enabled by default, interactive manualBoot toggle');
  await testPyocdCapabilities();
})().catch(error => { console.error(error); process.exitCode = 1; });

async function testPyocdCapabilities() {
  const exports = {};
  const helperCode = ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../src/utils/flashCapabilities.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(helperCode, { exports });
  const { pyocdFlashUnsupportedReason } = exports;
  const blocked = ['ing20', 'ING2000', ' ing200 ', 'ING_2000', 'ing-20', 'ing_200'];
  for (const target of blocked) assert.match(pyocdFlashUnsupportedReason(target), /SWD.*暂不可用/);
  for (const target of ['ing91800', 'ing91600', 'stm32f103c8', 'nrf52840', '', 'ing20000']) {
    assert.equal(pyocdFlashUnsupportedReason(target), null);
  }

  const text = fs.readFileSync(path.resolve(__dirname, '../src/components/PyocdFlasher.vue'), 'utf8');
  const { descriptor, errors } = parse(text);
  assert.deepEqual(errors, []);
  const ast = ts.createSourceFile('PyocdFlasher.ts', descriptor.scriptSetup.content, ts.ScriptTarget.Latest, true);
  const code = ts.transpileModule(ast.statements.filter(s => !ts.isImportDeclaration(s)).map(s => s.getText(ast)).join('\n')
    + '\nglobalThis.api = { handleFlash, targetMcu, filePath, selectedPackPath, selectedProbeId, flashDisabled, flashUnsupportedReason };',
    { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  const calls = [];
  const { ref, computed } = require('vue');
  const context = {
    ref, computed, pyocdFlashUnsupportedReason, console, Date,
    onMounted: () => {}, watch: () => {}, defineProps: () => ({}), defineEmits: () => () => {},
    t: key => key,
    safeInvoke: async (name, payload) => { calls.push({ name, payload }); return { message: 'mock-only' }; },
  };
  vm.createContext(context);
  vm.runInContext(code, context);
  const api = context.api;
  api.filePath.value = 'mock-firmware.hex';
  api.selectedProbeId.value = 'MOCK-PROBE';
  for (const target of blocked) {
    for (const pack of ['', 'explicit.pack']) {
      api.targetMcu.value = target;
      api.selectedPackPath.value = pack;
      assert.equal(api.flashDisabled.value, true);
      assert.match(api.flashUnsupportedReason.value, /Pack/);
      await api.handleFlash();
    }
  }
  assert.equal(calls.length, 0, 'Unsupported aliases must not invoke the daemon, even with an explicit Pack');
  for (const target of ['ing91800', 'ing91600', 'stm32f103c8']) {
    api.targetMcu.value = target;
    assert.equal(api.flashUnsupportedReason.value, null);
    assert.equal(api.flashDisabled.value, false, 'Other chip paths must remain available');
    await api.handleFlash();
    assert.equal(calls.at(-1).name, 'pyocd_flash_firmware');
    assert.equal(calls.at(-1).payload.targetOverride, target);
    assert.equal(calls.at(-1).payload.packPath, 'explicit.pack');
  }
  assert.equal(calls.length, 3);

  const template = compileTemplate({ source: descriptor.template.content, filename: 'PyocdFlasher.vue', id: 'test-pyocd' });
  assert.deepEqual(template.errors, []);
  function nodes(node) { return [node, ...[...(node.children || []), ...(node.branches || [])].flatMap(nodes)]; }
  const elements = nodes(template.ast);
  const button = elements.find(n => n.tag === 'button' && n.props.some(p => p.type === 7 && p.name === 'on' && p.exp?.content.includes('handleFlash')));
  assert.ok(button.props.some(p => p.type === 7 && p.arg?.content === 'disabled' && p.exp?.content.includes('flashDisabled')));
  const notice = elements.find(n => n.tag === 'p' && n.props.some(p => p.name === 'id' && p.value?.content === 'pyocd-flash-capability'));
  assert.ok(notice, 'Unsupported SWD target needs a visible pre-execution notice');
  assert.ok(notice.children.some(n => n.type === 5 && n.content?.content.includes('flashUnsupportedReason')));
  console.log('PASS production PyOCD UI: ING20 aliases disabled before IPC with visible reason; other chips unchanged');
}

