const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const { parse, compileTemplate } = require('vue/compiler-sfc');

const updaterSrc = fs.readFileSync(path.resolve(__dirname, '../src/utils/updater.ts'), 'utf8');
const transpiled = ts.transpileModule(updaterSrc, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

const storage = new Map();
globalThis.localStorage = {
  getItem: (k) => (storage.has(k) ? storage.get(k) : null),
  setItem: (k, v) => storage.set(k, String(v)),
};

const mod = { exports: {} };
new Function('exports', 'module', transpiled)(mod.exports, mod);
const {
  UPDATER_AUTO_CHECK_KEY,
  UPDATER_AUTO_DOWNLOAD_KEY,
  readUpdaterPref,
  saveUpdaterPref,
  formatBytesMiB,
  formatUpdateError,
} = mod.exports;

assert.equal(readUpdaterPref(UPDATER_AUTO_CHECK_KEY, true), true);
assert.equal(readUpdaterPref(UPDATER_AUTO_DOWNLOAD_KEY, false), false);
saveUpdaterPref(UPDATER_AUTO_CHECK_KEY, false);
saveUpdaterPref(UPDATER_AUTO_DOWNLOAD_KEY, true);
assert.equal(readUpdaterPref(UPDATER_AUTO_CHECK_KEY, true), false);
assert.equal(readUpdaterPref(UPDATER_AUTO_DOWNLOAD_KEY, false), true);
assert.equal(formatBytesMiB(1048576 * 2.5), '2.5 MiB');
assert.equal(formatBytesMiB(-1), '0.0 MiB');
assert.match(formatUpdateError('404 release not found'), /latest\.json/);
assert.match(formatUpdateError('signature verification failed'), /签名校验失败/);
assert.match(formatUpdateError('request timed out'), /超时/);

const sfc = fs.readFileSync(path.resolve(__dirname, '../src/components/UpdateManager.vue'), 'utf8');
const { descriptor, errors } = parse(sfc);
assert.deepEqual(errors, []);
const compiled = compileTemplate({
  source: descriptor.template.content,
  filename: 'UpdateManager.vue',
  id: 'updater-test',
});
assert.deepEqual(compiled.errors, []);

console.log('PASS production updater helpers & UpdateManager SFC compiled cleanly');
