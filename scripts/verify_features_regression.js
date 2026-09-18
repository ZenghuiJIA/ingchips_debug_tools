/**
 * Regression verification suite for:
 * 1. Telemetry Parser (CSV, Key-Value, JSON)
 * 2. Smart Auto-Responder / Triggers Matcher
 * 3. Command Encoder (CRLF, LF, CR, RAW, HEX)
 */

import assert from 'assert';

// --- 1. Test Telemetry Parser Logic ---
function parseTelemetryLine(rawLine) {
  const line = rawLine.trim();
  if (!line || line.length < 1) return null;

  // 1. JSON
  if (line.startsWith('{') && line.endsWith('}')) {
    try {
      const obj = JSON.parse(line);
      const result = {};
      let hasNumber = false;
      for (const [k, v] of Object.entries(obj)) {
        if (typeof v === 'number' && !isNaN(v)) {
          result[k] = v;
          hasNumber = true;
        } else if (typeof v === 'string') {
          const num = Number(v);
          if (!isNaN(num)) {
            result[k] = num;
            hasNumber = true;
          }
        }
      }
      if (hasNumber) return result;
    } catch {}
  }

  // 2. Key-Value pairs
  const kvRegex = /([a-zA-Z0-9_\u4e00-\u9fa5]+)\s*[:=]\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)/g;
  let match;
  const kvResults = {};
  let kvCount = 0;

  while ((match = kvRegex.exec(line)) !== null) {
    const val = Number(match[2]);
    if (!isNaN(val)) {
      kvResults[match[1]] = val;
      kvCount++;
    }
  }
  if (kvCount > 0) return kvResults;

  // 3. CSV floats
  let cleaned = line;
  if (cleaned.startsWith('[') && cleaned.endsWith(']')) {
    cleaned = cleaned.slice(1, -1).trim();
  }

  const delimiter = cleaned.includes(',') ? ',' : (cleaned.includes('\t') ? '\t' : ' ');
  const tokens = cleaned.split(delimiter).map(t => t.trim()).filter(t => t.length > 0);

  if (tokens.length >= 1) {
    const numbers = [];
    for (const tok of tokens) {
      if (!/^[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?$/.test(tok)) {
        return null;
      }
      const n = Number(tok);
      if (isNaN(n)) return null;
      numbers.push(n);
    }

    if (numbers.length > 0) {
      const res = {};
      numbers.forEach((val, idx) => {
        res[`CH${idx}`] = val;
      });
      return res;
    }
  }

  return null;
}

// --- 2. Test Smart Trigger Matcher Logic ---
function matchTriggers(rules, rxText) {
  const matched = [];
  for (const rule of rules) {
    if (!rule.enabled) continue;
    let isMatch = false;
    if (rule.matchType === 'contains') {
      isMatch = rxText.includes(rule.matchPattern);
    } else if (rule.matchType === 'regex') {
      try {
        const re = new RegExp(rule.matchPattern);
        isMatch = re.test(rxText);
      } catch {}
    }

    if (isMatch) {
      rule.hits = (rule.hits || 0) + 1;
      if (rule.mode === 'once') {
        rule.enabled = false;
      }
      matched.push(rule);
    }
  }
  return matched;
}

// --- 3. Test Command Encoder Logic ---
function encodeCommand(cmd) {
  if (cmd.format === 'hex') {
    const cleanHex = cmd.payload.replace(/\s+/g, '');
    if (!/^[0-9a-fA-F]*$/.test(cleanHex) || cleanHex.length % 2 !== 0) {
      throw new Error('Invalid HEX');
    }
    const bytes = [];
    for (let i = 0; i < cleanHex.length; i += 2) {
      bytes.push(parseInt(cleanHex.substring(i, i + 2), 16));
    }
    return { bytes, textDisplay: `[HEX] ${cmd.payload}` };
  }

  let fullText = cmd.payload;
  if (cmd.lineEnding === 'crlf') fullText += '\r\n';
  else if (cmd.lineEnding === 'lf') fullText += '\n';
  else if (cmd.lineEnding === 'cr') fullText += '\r';

  const bytes = Array.from(Buffer.from(fullText, 'utf-8'));
  return { bytes, textDisplay: `${cmd.payload}` };
}

// ==========================================
// RUN REGRESSION TESTS
// ==========================================
console.log('>>> [1/3] Testing Telemetry Parser...');
// CSV tests
const csv1 = parseTelemetryLine('12.5, 45.2, -7.8');
assert.deepStrictEqual(csv1, { CH0: 12.5, CH1: 45.2, CH2: -7.8 }, 'CSV parsing failed');
const csv2 = parseTelemetryLine('  100.2  ');
assert.deepStrictEqual(csv2, { CH0: 100.2 }, 'Single float parsing failed');

// Key-Value tests
const kv1 = parseTelemetryLine('roll:12.3, pitch:-45.6, yaw:88.0');
assert.deepStrictEqual(kv1, { roll: 12.3, pitch: -45.6, yaw: 88.0 }, 'Key-Value parsing failed');
const kv2 = parseTelemetryLine('temp=25.4 humi=60.1');
assert.deepStrictEqual(kv2, { temp: 25.4, humi: 60.1 }, 'Key-Value with equal sign failed');

// JSON tests
const json1 = parseTelemetryLine('{"voltage": 3.3, "current": 0.15}');
assert.deepStrictEqual(json1, { voltage: 3.3, current: 0.15 }, 'JSON telemetry failed');

// Ignore regular debug log tests
const log1 = parseTelemetryLine('[INFO] Application started successfully at 115200');
assert.strictEqual(log1, null, 'Should not parse normal text log');
console.log('    ✓ Telemetry Parser passed (CSV, Key-Value, JSON, Normal log rejection)');

console.log('>>> [2/3] Testing Smart Auto-Responder / Triggers Matcher...');
const testRules = [
  { id: '1', name: 'Handshake', enabled: true, matchType: 'contains', matchPattern: 'READY', responsePayload: 'AT+START', mode: 'continuous' },
  { id: '2', name: 'Panic Guard', enabled: true, matchType: 'regex', matchPattern: 'AssertFailed:0x[0-9A-Fa-f]+', responsePayload: 'RESET', mode: 'once' }
];

const res1 = matchTriggers(testRules, 'MCU booted. Status: READY for command.');
assert.strictEqual(res1.length, 1, 'Expected 1 matched rule');
assert.strictEqual(res1[0].name, 'Handshake');
assert.strictEqual(res1[0].hits, 1);

const res2 = matchTriggers(testRules, 'CRITICAL AssertFailed:0x8001004 in main.c');
assert.strictEqual(res2.length, 1, 'Regex match failed');
assert.strictEqual(res2[0].name, 'Panic Guard');
assert.strictEqual(res2[0].hits, 1);
assert.strictEqual(res2[0].enabled, false, 'Once mode should auto-disable');

const res3 = matchTriggers(testRules, 'CRITICAL AssertFailed:0x8001004 second time');
assert.strictEqual(res3.length, 0, 'Disabled rule should not trigger');
console.log('    ✓ Smart Auto-Responder / Triggers Matcher passed');

console.log('>>> [3/3] Testing Command Encoder...');
const encCrlf = encodeCommand({ payload: 'AT', format: 'string', lineEnding: 'crlf' });
assert.deepStrictEqual(encCrlf.bytes, [65, 84, 13, 10]);

const encHex = encodeCommand({ payload: '01 03 00 00 00 02 C4 0B', format: 'hex', lineEnding: 'none' });
assert.deepStrictEqual(encHex.bytes, [1, 3, 0, 0, 0, 2, 196, 11]);

console.log('    ✓ Command Encoder passed (String + CRLF and HEX)');

console.log('\n======================================================');
console.log(' ALL REGRESSION TESTS PASSED CLEANLY (100% OK)');
console.log('======================================================');
