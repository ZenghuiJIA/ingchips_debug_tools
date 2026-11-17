const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { createRequire } = require('node:module');
const root = path.resolve(__dirname, '..');
const deps = process.argv[2] || root;
const req = createRequire(path.join(deps, 'package.json'));
const ts = req('typescript');
const compiler = req('vue/compiler-sfc');
const source = fs.readFileSync(path.join(root, 'src/components/SerialTerminal.vue'), 'utf8');
const sessionSource = fs.readFileSync(path.join(root, 'src/components/SerialTerminalSession.vue'), 'utf8');
const script = compiler.parse(source).descriptor.scriptSetup.content;
function functions(names, context) {
  const ast = ts.createSourceFile('SerialTerminal.ts', script, ts.ScriptTarget.Latest, true);
  const selected = ast.statements.filter(s => ts.isFunctionDeclaration(s) && names.includes(s.name.text));
  assert.equal(selected.length, names.length);
  const code = ts.transpileModule(selected.map(s => s.getText(ast)).join('\n'), { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText;
  vm.createContext(context); vm.runInContext(code, context); return context;
}
let passed = 0;
async function test(name, fn) { await fn(); passed++; console.log('PASS ' + name); }
(async () => {
  const ctx = functions(['networkSpec', 'toggleTabConnection'], {
    reconnectPending: new Set(),
    syncActiveSessions: async () => { ctx.synced = (ctx.synced || 0) + 1; },
    safeInvoke: async (name, args) => { ctx.calls.push({ name, args }); },
    calls: [],
  });
  await test('network names parse strictly and reject malformed ports', () => {
    assert.equal(JSON.stringify(ctx.networkSpec('TCP-Client:127.0.0.1:9000')), JSON.stringify({ mode: 'tcp_client', host: '127.0.0.1', port: 9000 }));
    assert.equal(JSON.stringify(ctx.networkSpec('TCP-Server:localhost:1')), JSON.stringify({ mode: 'tcp_server', host: 'localhost', port: 1 }));
    assert.equal(JSON.stringify(ctx.networkSpec('UDP:127.0.0.1:65535')), JSON.stringify({ mode: 'udp_socket', host: '127.0.0.1', port: 65535 }));
    assert.equal(ctx.networkSpec('UDP:127.0.0.1:0'), null);
    assert.equal(ctx.networkSpec('COM3'), null);
  });
  await test('network connect/disconnect uses network IPC and never serial IPC', async () => {
    const tab = { id: 'n1', portName: 'TCP-Client:127.0.0.1:9000', isConnected: false, isListening: false };
    await ctx.toggleTabConnection(tab);
    assert.equal(JSON.stringify(ctx.calls.at(-1)), JSON.stringify({ name: 'start_network_stream', args: { name: tab.portName, mode: 'tcp_client', host: '127.0.0.1', port: 9000 } }));
    tab.isConnected = true;
    await ctx.toggleTabConnection(tab);
    assert.equal(JSON.stringify(ctx.calls.at(-1)), JSON.stringify({ name: 'stop_network_stream', args: { name: tab.portName } }));
    assert.equal(ctx.calls.some(c => c.name === 'open_serial_port' || c.name === 'close_serial_port'), false);
  });
  await test('network tab keeps server-listening state distinct from connected state', () => {
    assert.match(source, /tab\.isConnected = Boolean\(net\?\.is_connected\)/);
    assert.match(source, /tab\.isListening = Boolean\(net && net\.mode === 'tcp_server' && !net\.is_connected\)/);
    assert.match(source, /Restore network sessions after a page remount/);
    assert.match(sessionSource, /!isNetworkPortName\(portName\)/);
    assert.match(sessionSource, /event\.payload\.session_id && captureSession/);
    assert.match(source, /event\.payload\.session_id === targetTab\.sessionId/);
  });
  console.log(`Serial network production regression: ${passed} passed`);
})().catch(error => { console.error(error); process.exitCode = 1; });
