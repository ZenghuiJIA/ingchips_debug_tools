// Real Chromium rendering of the built frontend in its explicitly labelled browser-preview mode.
// No Tauri bridge is injected, no physical device is accessed, no browser package is installed.
import { createServer } from 'node:http';
import { readFile, writeFile, mkdtemp, mkdir, rm, access } from 'node:fs/promises';
import { resolve, dirname, extname, join, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { spawn } from 'node:child_process';
import assert from 'node:assert/strict';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dist = join(root, 'dist');
const output = join(root, 'build_work', 'ui-regression');
const sleep = ms => new Promise(r => setTimeout(r, ms));
let executable;
for (const candidate of [process.env.HIL_BROWSER_EXE, 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Microsoft/Edge/Application/msedge.exe', 'C:/Program Files/Google/Chrome/Application/chrome.exe'].filter(Boolean)) {
  try { await access(candidate); executable = candidate; break; } catch {}
}
assert.ok(executable, 'Set HIL_BROWSER_EXE to a Chromium browser');
await access(join(dist, 'index.html'));
await mkdir(output, { recursive: true });
const server = createServer(async (req, res) => {
  try {
    const relative = decodeURIComponent(new URL(req.url, 'http://localhost').pathname).replace(/^\/+/, '') || 'index.html';
    const file = resolve(dist, relative);
    if (!file.startsWith(dist + sep)) { res.writeHead(403).end(); return; }
    const data = await readFile(file);
    res.setHeader('Content-Type', ({ '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml' })[extname(file)] || 'application/octet-stream');
    res.end(data);
  } catch { res.writeHead(404).end(); }
});
await new Promise(r => server.listen(0, '127.0.0.1', r));
const url = `http://127.0.0.1:${server.address().port}`;
const profile = await mkdtemp(join(tmpdir(), 'hil-ui-preview-'));
const browser = spawn(executable, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { stdio: 'ignore' });
let socket;
try {
  let port;
  const deadline = Date.now() + 20000;
  while (!port && Date.now() < deadline) {
    try { port = (await readFile(join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0].trim(); } catch { await sleep(100); }
  }
  assert.ok(port, 'Chromium DevTools endpoint did not start');
  const target = await (await fetch(`http://127.0.0.1:${port}/json/new?${url}`, { method: 'PUT' })).json();
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r, reject) => { socket.onopen = r; socket.onerror = reject; });
  let sequence = 0;
  const pending = new Map();
  socket.onmessage = message => {
    const data = JSON.parse(message.data);
    if (pending.has(data.id)) { const [done, fail, timer] = pending.get(data.id); pending.delete(data.id); clearTimeout(timer); data.error ? fail(new Error(JSON.stringify(data.error))) : done(data.result); }
  };
  const cdp = (method, params = {}) => new Promise((done, fail) => {
    const id = ++sequence;
    const timer = setTimeout(() => { pending.delete(id); fail(new Error(`CDP timeout: ${method}`)); }, 15000);
    pending.set(id, [done, fail, timer]); socket.send(JSON.stringify({ id, method, params }));
  });
  const evaluate = async expression => {
    const response = await cdp('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
    return response.result.value;
  };
  const waitFor = async expression => {
    const until = Date.now() + 15000;
    while (Date.now() < until) { if (await evaluate(expression)) return; await sleep(100); }
    throw new Error(`UI condition timed out: ${expression}`);
  };
  const clickText = async text => {
    assert.equal(await evaluate(`(() => { const b=[...document.querySelectorAll('button')].find(b => b.textContent.trim()===${JSON.stringify(text)} && b.getClientRects().length); if(!b)return false; b.click(); return true; })()`), true, `Button missing: ${text}`);
  };
  const screenshot = async name => { const image = await cdp('Page.captureScreenshot', { format: 'png' }); await writeFile(join(output, name), Buffer.from(image.data, 'base64')); };
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1280, height: 840, deviceScaleFactor: 1, mobile: false });
  await waitFor(`document.querySelector('#app')?.textContent.includes('串口')`);
  assert.equal(await evaluate(`document.body.textContent.includes('浏览器预览') || document.body.textContent.includes('浏览器模拟') || document.body.textContent.includes('浏览器预览模式')`), true, 'Preview mode must remain visible');
  // Seed only a disconnected saved tab in this disposable preview profile.
  // No connection flag or Tauri bridge is injected.
  await evaluate(`localStorage.setItem('ai_hil_serial_tabs', JSON.stringify([{id:'ui-preview',portName:'COM_PREVIEW',baudRate:115200,isDaplink:false,autoReconnect:false}])); localStorage.setItem('ai_hil_serial_active_tab','ui-preview')`);
  await cdp('Page.reload');
  await waitFor(`!![...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='外观')`);
  await clickText('外观');
  await evaluate(`(() => { const input=[...document.querySelectorAll('input[type=number]')].find(e=>e.min==='8'&&e.max==='32'); input.value='18'; input.dispatchEvent(new Event('change',{bubbles:true})); })()`);
  await waitFor(`JSON.parse(localStorage.getItem('ai_hil_serial_appearance_v1'))?.fontSize === 18`);
  assert.equal(await evaluate(`!![...document.querySelectorAll('div')].find(e=>e.style.fontSize==='18px'&&e.style.fontFamily)`), true);
  await screenshot('serial-appearance-1280.png');
  await cdp('Page.reload');
  await waitFor(`!![...document.querySelectorAll('div')].find(e=>e.style.fontSize==='18px'&&e.style.fontFamily)`);
  console.log('PASS actual browser font-size edit, style binding and reload persistence');
  await evaluate(`localStorage.setItem('hil_app_current_tab', JSON.stringify('sequencer'))`);
  await cdp('Page.reload');
  await waitFor(`document.body.textContent.includes('工位默认值')`);
  await screenshot('hil-sequencer-1280.png');
  await clickText('JSON 脚本');
  await waitFor(`!!document.querySelector('textarea[spellcheck=false]')`);
  await screenshot('hil-editor-1280.png');
  await cdp('Emulation.setDeviceMetricsOverride', { width: 1000, height: 650, deviceScaleFactor: 1, mobile: false });
  await screenshot('hil-editor-1000.png');
  console.log('PASS actual browser HIL editor render at default and minimum window sizes');
  console.log(`SCREENSHOTS ${output}`);
} finally {
  socket?.close();
  if (browser.exitCode === null) { browser.kill(); await Promise.race([new Promise(r => browser.once('exit', r)), sleep(5000)]); }
  await new Promise(r => server.close(r));
  // Only this test's newly-created browser profile may be removed.
  assert.equal(dirname(profile), resolve(tmpdir()));
  try { await rm(profile, { recursive: true, force: true }); } catch (error) { console.warn(`Temporary profile still in use: ${profile}: ${error.message}`); }
}
