const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');
const assert = require('node:assert/strict');
const root = path.resolve(__dirname, '..');
function moduleFromSource(file) {
  const text = ts.transpileModule(fs.readFileSync(path.join(root,file),'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const exports = {}; vm.runInNewContext(text, { exports, require, TextEncoder, TextDecoder, Uint8Array, console }); return exports;
}
const { TriggerMatcher, appendBoundedLog, filterLogs, highlightParts } = moduleFromSource('src/utils/serialLog.ts');
const { deviceKey, reconnectCandidate } = moduleFromSource('src/utils/deviceIdentity.ts');
const { statistics, samplesCsv, parseSamplesCsv, extremaDecimation, compareRuns } = moduleFromSource('src/utils/captureAnalysis.ts');
const { protocolHilDocument, exampleProtocol } = moduleFromSource('src/utils/protocol.ts');
let count = 0;
function test(name, fn) { fn(); count++; console.log('PASS ' + name); }
test('trigger split/coalesced responses retain independent rule cursors', () => {
  const matcher = new TriggerMatcher();
  const rules = ['BOOT','DONE'].map((p,i) => ({ id: String(i), enabled:true, matchType:'contains',matchPattern:p,hits:0,mode:'continuous' }));
  assert.equal(matcher.feed('BO',rules).length,0);
  assert.equal(matcher.feed('OT\nDONE\nBOOT\n',rules).length,3);
  assert.equal(rules[0].hits,2); assert.equal(rules[1].hits,1);
  assert.equal(matcher.feed('',rules).length,0);
});
test('trigger configuration change and reset never reuse old fragments', () => {
  const matcher = new TriggerMatcher(); const rules=[{id:'a',enabled:true,matchType:'contains',matchPattern:'OK',hits:0,mode:'continuous'}];
  matcher.feed('O',rules); matcher.reset(); assert.equal(matcher.feed('K',rules).length,0);
  rules[0].matchType='regex'; rules[0].matchPattern='.*?'; assert.throws(()=>matcher.feed('data',rules));
});
test('continuous no-newline display stays bounded and reports truncation', () => {
  let logs=[]; for(let i=0;i<500;i++) logs=appendBoundedLog(logs,{id:i,text:'X'.repeat(8000),type:'rx',timestamp:'t'});
  assert.ok(logs.reduce((n,x)=>n+x.text.length*2+128,0)<=1024*1024);
  logs=appendBoundedLog(logs,{id:999,text:'Z'.repeat(100000),type:'rx',timestamp:'t'});
  assert.ok(logs.at(-1).text.includes('截断'));
});
test('filter/highlight preserves raw text and rejects invalid regex', () => {
  const logs=[{id:1,text:'ERROR <script>alert(1)</script>',type:'rx'},{id:2,text:'normal',type:'rx'}];
  assert.equal(filterLogs(logs,'error','',false).length,1);
  assert.throws(()=>filterLogs([],'[','',true));
  assert.equal(highlightParts(logs[0].text,'ERROR').map(x=>x.text).join(''),logs[0].text);
});
test('reconnect uses unique USB identity and refuses duplicate/no serial IDs', () => {
  const a={port_name:'COM3',vid:1,pid:2,serial_number:'SN'};
  assert.equal(reconnectCandidate(deviceKey(a),[{...a,port_name:'COM9'}]).port_name,'COM9');
  assert.equal(reconnectCandidate(deviceKey(a),[a,{...a,port_name:'COM9'}]),null);
  assert.equal(deviceKey({...a,serial_number:null}),null);
});
test('timestamp CSV preserves sparse channels and quoted names', () => {
  const samples=[{t:1,channel:'temp,"A"',value:2,session:'one'},{t:4,channel:'B',value:7,session:'one'}];
  const parsed=parseSamplesCsv(samplesCsv(samples)); assert.equal(parsed[0].channel,samples[0].channel); assert.equal(parsed[1].t,4); assert.equal(parsed.length,2);
  assert.throws(()=>parseSamplesCsv('SampleIndex,CH0\n0,1'));
  assert.throws(()=>parseSamplesCsv('timestamp_ms,channel,value\n1,A,'));
});
test('statistics use original samples, population standard deviation and interval', () => {
  const samples=[1,2,3,4].map((value,t)=>({t,channel:'x',value}));
  const all=statistics(samples,0,3)[0]; assert.equal(all.mean,2.5); assert.equal(all.stddev,Math.sqrt(1.25)); assert.equal(all.peakToPeak,3);
  assert.equal(statistics(samples,1,2)[0].count,2); assert.throws(()=>statistics(samples,2,1));
});
test('display decimation preserves narrow spikes', () => {
  const points=Array.from({length:1000},(_,t)=>({t,channel:'x',value:t===501?100:0}));
  assert.ok(extremaDecimation(points,20).some(p=>p.value===100));
  assert.ok(Math.abs(statistics(points,0,999)[0].mean - .1) < 1e-12);
});
test('run comparison aligns anchors without fabricating missing channels', () => {
  const a=[{t:10,channel:'x',value:1},{t:20,channel:'x',value:3}];
  const b=[{t:110,channel:'x',value:2},{t:120,channel:'x',value:4}];
  assert.equal(compareRuns(a,b,0,10,10,110)[0].meanDelta,1);
});
test('HIL export freezes the protocol and keeps command parameters', () => {
  const p=JSON.parse(JSON.stringify(exampleProtocol)); const doc=protocolHilDocument('COM3',115200,p,{seq:1,value:0,status:0},{seq:1},500);
  p.name='edited'; assert.notEqual(doc.steps[0].params.protocol.name,p.name); assert.equal(doc.steps[0].action,'protocol_request'); assert.equal(doc.steps[0].timeout_ms,500);
});
test('actual serial worker preserves HEX byte boundaries across RX chunks', () => {
  const messages = [];
  const worker = { postMessage: message => messages.push(message) };
  const code = ts.transpileModule(fs.readFileSync(path.join(root, 'src/workers/serialParser.worker.ts'), 'utf8'), {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(code, { self: worker, TextDecoder, Uint8Array });
  for (const rawBytes of [new Uint8Array([0x0A]), new Uint8Array([0xBC, 0xDE])]) {
    worker.onmessage({ data: { rawBytes, mode: 'hex', timestamp: 't' } });
  }
  let logs = [];
  for (const [id, message] of messages.entries()) logs = appendBoundedLog(logs, { id, text: message.text, type: 'rx', timestamp: 't' });
  assert.equal(logs.map(row => row.text).join(''), '0A BC DE ');
});
console.log(`${count} ABC frontend regression checks passed; no hardware accessed.`);
