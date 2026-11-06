import type { SerialLogItem, TriggerRule } from '../types';

export function appendBoundedLog(logs: SerialLogItem[], item: SerialLogItem, maxBytes = 1024 * 1024): SerialLogItem[] {
  const maxChars = 16384;
  const incoming = item.text.length > maxChars ? '[显示已截断；完整数据请启用后台录制]\n' + item.text.slice(-maxChars) : item.text;
  const next = [...logs];
  const previous = next[next.length - 1];
  if (item.type === 'rx' && previous?.type === 'rx' && !/[\r\n]$/.test(previous.text) && previous.text.length + incoming.length <= maxChars) {
    next[next.length - 1] = { ...previous, text: previous.text + incoming };
  } else next.push({ ...item, text: incoming });
  let bytes = next.reduce((n, row) => n + row.text.length * 2 + 128, 0);
  let remove = 0;
  while ((next.length - remove > 1200 || bytes > maxBytes) && remove < next.length) {
    bytes -= next[remove]!.text.length * 2 + 128; remove++;
  }
  return next.slice(remove);
}
export function filterLogs(logs: SerialLogItem[], include: string, exclude: string, regex: boolean) {
  const match = (query: string) => regex ? (text: string) => new RegExp(query, 'i').test(text) : (text: string) => text.toLowerCase().includes(query.toLowerCase());
  const inc = include ? match(include) : null, exc = exclude ? match(exclude) : null;
  // Compile eagerly so invalid expressions surface even for an empty log.
  if (regex) { if (include) new RegExp(include); if (exclude) new RegExp(exclude); }
  return logs.filter(row => (!inc || inc(row.text)) && (!exc || !exc(row.text)));
}
export function highlightParts(text: string, query: string): { text: string; mark: boolean }[] {
  if (!query) return [{ text, mark: false }];
  const result = []; let at = 0; const lower = text.toLowerCase(), needle = query.toLowerCase();
  for (let n = 0; n < 1000; n++) {
    const pos = lower.indexOf(needle, at);
    if (pos < 0) break;
    if (pos > at) result.push({ text: text.slice(at, pos), mark: false });
    result.push({ text: text.slice(pos, pos + query.length), mark: true }); at = pos + query.length;
  }
  if (at < text.length) result.push({ text: text.slice(at), mark: false });
  return result;
}
/** One cursor per rule. Input is decoded RX, never the formatted HEX view. */
export class TriggerMatcher {
  private states = new Map<string, { key: string; pending: string }>();
  reset() { this.states.clear(); }
  feed(text: string, rules: TriggerRule[]): TriggerRule[] {
    const hits: TriggerRule[] = [];
    const ids = new Set(rules.map(r => r.id));
    for (const id of this.states.keys()) if (!ids.has(id)) this.states.delete(id);
    for (const rule of rules) {
      if (!rule.enabled) { this.states.delete(rule.id); continue; }
      if (!rule.matchPattern) throw new Error('触发规则不能为空');
      const key = rule.matchType + ':' + rule.matchPattern;
      const old = this.states.get(rule.id);
      let pending = (old?.key === key ? old.pending : '') + text;
      if (pending.length > 65536) throw new Error('触发匹配窗口超过 64K 字符，请缩小匹配范围');
      const regex = rule.matchType === 'regex' ? new RegExp(rule.matchPattern) : null;
      for (let n = 0; n < 100; n++) {
        const found = regex?.exec(pending);
        const start = regex ? (found?.index ?? -1) : pending.indexOf(rule.matchPattern);
        if (start < 0) break;
        const length = regex ? found![0].length : rule.matchPattern.length;
        if (!length) throw new Error('触发正则不允许空匹配');
        pending = pending.slice(start + length);
        rule.hits++; rule.lastTriggerTime = new Date().toISOString(); hits.push({ ...rule });
        if (rule.mode === 'once') { rule.enabled = false; break; }
      }
      // Contains patterns only need their possible suffix. Regex retains the bounded window.
      if (!regex) pending = pending.slice(-Math.max(1, rule.matchPattern.length - 1));
      this.states.set(rule.id, { key, pending });
    }
    return hits;
  }
}
