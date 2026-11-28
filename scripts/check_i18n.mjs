#!/usr/bin/env node
/**
 * Pre-build i18n guard for src/utils/i18n.ts and src/ components.
 * Blocks build when:
 *  1. Any locale ('zh', 'zh-TW', 'en') has duplicate keys.
 *  2. Any key is missing in 'zh', 'zh-TW', or 'en'.
 *  3. {placeholder} variables differ across locales for the same key.
 *  4. Any static t('key') call in src/ references an undefined key.
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const I18N_PATH = path.join(ROOT, 'src', 'utils', 'i18n.ts');

function extractBlock(src, startPattern, endPattern) {
  const startIdx = src.search(startPattern);
  if (startIdx === -1) return null;
  const sub = src.slice(startIdx);
  const endIdx = sub.search(endPattern);
  if (endIdx === -1) return null;
  return sub.slice(0, endIdx);
}

function parseLocaleEntries(blockText) {
  const entries = new Map();
  const duplicates = [];
  const lineRe = /^\s*([a-zA-Z0-9_]+)\s*:\s*'((?:\\'|[^'])*)'\s*,?/gm;
  let m;
  while ((m = lineRe.exec(blockText)) !== null) {
    const [, key, value] = m;
    if (entries.has(key)) {
      duplicates.push(key);
    } else {
      entries.set(key, value);
    }
  }
  return { entries, duplicates };
}

function extractPlaceholders(value) {
  const matches = value.match(/\{[a-zA-Z0-9_]+\}/g) || [];
  return [...new Set(matches)].sort();
}

function walkFiles(dir, exts, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkFiles(full, exts, out);
    } else if (exts.some((ext) => entry.name.endsWith(ext))) {
      out.push(full);
    }
  }
  return out;
}

function main() {
  const src = fs.readFileSync(I18N_PATH, 'utf8');
  const zhBlock = extractBlock(src, /^  zh:\s*\{/m, /\n  \},\s*\n  'zh-TW':/m);
  const twBlock = extractBlock(src, /^  'zh-TW':\s*\{/m, /\n  \},\s*\n  en:/m);
  const enBlock = extractBlock(src, /^  en:\s*\{/m, /\n  \}\s*\n\};/m);

  if (!zhBlock || !twBlock || !enBlock) {
    console.error('[i18n-check] Failed to locate zh / zh-TW / en blocks in src/utils/i18n.ts');
    process.exit(1);
  }

  const locales = {
    zh: parseLocaleEntries(zhBlock),
    'zh-TW': parseLocaleEntries(twBlock),
    en: parseLocaleEntries(enBlock),
  };

  let hasError = false;

  for (const [name, parsed] of Object.entries(locales)) {
    if (parsed.duplicates.length > 0) {
      console.error(`[i18n-check] Duplicate keys in '${name}': ${parsed.duplicates.join(', ')}`);
      hasError = true;
    }
  }

  const allKeys = new Set([
    ...locales.zh.entries.keys(),
    ...locales['zh-TW'].entries.keys(),
    ...locales.en.entries.keys(),
  ]);

  for (const [name, parsed] of Object.entries(locales)) {
    const missing = [...allKeys].filter((k) => !parsed.entries.has(k));
    if (missing.length > 0) {
      console.error(`[i18n-check] Missing ${missing.length} key(s) in '${name}': ${missing.slice(0, 15).join(', ')}${missing.length > 15 ? ' ...' : ''}`);
      if (name === 'zh-TW') {
        console.error(`  Hint: run 'python3 scripts/sync_i18n_tw.py' to auto-sync zh-TW from zh.`);
      }
      hasError = true;
    }
  }

  for (const key of locales.zh.entries.keys()) {
    const basePh = extractPlaceholders(locales.zh.entries.get(key));
    for (const name of ['zh-TW', 'en']) {
      const val = locales[name].entries.get(key);
      if (val === undefined) continue;
      const ph = extractPlaceholders(val);
      if (JSON.stringify(basePh) !== JSON.stringify(ph)) {
        console.error(
          `[i18n-check] Placeholder mismatch for '${key}' in '${name}': expected [${basePh.join(', ')}], got [${ph.join(', ')}]`
        );
        hasError = true;
      }
    }
  }

  // Verify static t('key') references in src/
  const srcFiles = walkFiles(path.join(ROOT, 'src'), ['.vue', '.ts']);
  const callRe = /\bt\(\s*'([a-zA-Z0-9_]+)'/g;
  const dangling = [];
  for (const file of srcFiles) {
    if (file === I18N_PATH) continue;
    const text = fs.readFileSync(file, 'utf8');
    let m;
    while ((m = callRe.exec(text)) !== null) {
      const key = m[1];
      if (!locales.zh.entries.has(key)) {
        dangling.push(`${path.relative(ROOT, file)}: ${key}`);
      }
    }
  }
  if (dangling.length > 0) {
    console.error(`[i18n-check] Undefined t('key') references found:\n  ${dangling.join('\n  ')}`);
    hasError = true;
  }

  if (hasError) {
    process.exit(1);
  }
  console.log(`[i18n-check] OK (${allKeys.size} keys across zh, zh-TW, en)`);
}

main();
