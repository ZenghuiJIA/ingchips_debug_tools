export interface Sample { t: number; channel: string; value: number; source?: number; session?: string }
export interface TimelineEvent { seq: number; session: string; t: number; direction: string; data: string; message: string; port: string }
export function normalizeEvent(value: Record<string, unknown>, fallbackSeq: number): TimelineEvent {
  const direction = String(value.direction || (value.kind === 'serial' ? 'RX' : 'INFO')).toUpperCase();
  const t = Number(value.elapsed_ms ?? value.timestamp_ms ?? 0);
  const data = String(value.data || '');
  if (!Number.isFinite(t) || t < 0 || (data && !/^(?:[a-f\d]{2})*$/i.test(data))) throw new Error('记录包含非法时间或 HEX 数据');
  return { seq: Number(value.seq ?? fallbackSeq), session: String(value.session_id || value.port || 'legacy'), t,
    direction, data, message: String(value.message || value.kind || ''), port: String(value.port || '') };
}
export function statistics(samples: Sample[], from: number, to: number) {
  if (!Number.isFinite(from) || !Number.isFinite(to) || from > to) throw new Error('时间范围无效');
  const groups: Record<string, { count: number; mean: number; m2: number; min: number; max: number }> = {};
  for (const p of samples) {
    if (p.t < from || p.t > to || !Number.isFinite(p.value)) continue;
    const key = p.session ? `${p.session}/${p.channel}` : p.channel;
    const g = groups[key] ||= { count: 0, mean: 0, m2: 0, min: p.value, max: p.value };
    g.count++; const delta = p.value - g.mean; g.mean += delta / g.count; g.m2 += delta * (p.value - g.mean);
    g.min = Math.min(g.min, p.value); g.max = Math.max(g.max, p.value);
  }
  return Object.entries(groups).map(([channel, g]) => ({ channel, count: g.count, mean: g.mean, min: g.min, max: g.max, peakToPeak: g.max - g.min, stddev: Math.sqrt(Math.max(0, g.m2 / g.count)) }));
}
export function samplesCsv(samples: Sample[]): string {
  const quote = (text: string) => '"' + text.replace(/"/g, '""') + '"';
  return 'timestamp_ms,channel,value,session,source_seq\n' + samples.map(p => [p.t, quote(p.channel), p.value, quote(p.session || ''), p.source ?? ''].join(',')).join('\n');
}
export function parseSamplesCsv(text: string): Sample[] {
  const rows: string[][] = []; let row: string[] = [], field = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i]!;
    if (c === '"') { if (quoted && text[i + 1] === '"') { field += '"'; i++; } else quoted = !quoted; }
    else if (!quoted && c === ',') { row.push(field); field = ''; }
    else if (!quoted && c === '\n') { row.push(field.replace(/\r$/, '')); rows.push(row); row = []; field = ''; }
    else field += c;
  }
  if (quoted) throw new Error('CSV 引号未闭合');
  if (field || row.length) { row.push(field.replace(/\r$/, '')); rows.push(row); }
  const header = rows.shift() || [];
  const time = header.indexOf('timestamp_ms'), channel = header.indexOf('channel'), value = header.indexOf('value');
  if (time < 0 || channel < 0 || value < 0) throw new Error('需要 timestamp_ms,channel,value 列；无时间戳的旧 CSV 不能推断采样时间');
  const session = header.indexOf('session'), source = header.indexOf('source_seq');
  return rows.filter(r => r.some(Boolean)).map((r, index) => {
    const t = Number(r[time]), v = Number(r[value]);
    if (!r[time]?.trim() || !r[value]?.trim() || !r[channel] || !Number.isFinite(t) || t < 0 || !Number.isFinite(v)) throw new Error(`CSV 第 ${index + 2} 行无效`);
    return { t, channel: r[channel]!, value: v, session: session < 0 ? undefined : r[session], source: source < 0 || !r[source] ? undefined : Number(r[source]) };
  });
}
/** Display decimation only; measurements must use original samples. */
export function extremaDecimation(points: Sample[], buckets: number): Sample[] {
  if (points.length <= buckets * 2 || buckets < 1) return points;
  const output: Sample[] = [];
  for (let i = 0; i < buckets; i++) {
    const start = Math.floor(i * points.length / buckets), end = Math.floor((i + 1) * points.length / buckets);
    let low = start, high = start;
    for (let n = start + 1; n < end; n++) { if (points[n]!.value < points[low]!.value) low = n; if (points[n]!.value > points[high]!.value) high = n; }
    for (const index of [...new Set([low, high])].sort((a,b) => a-b)) output.push(points[index]!);
  }
  return output;
}
export function compareRuns(a: Sample[], b: Sample[], from: number, to: number, anchorA: number, anchorB: number) {
  const normalize = (values: Sample[], anchor: number) => values.map(p => ({ ...p, session: undefined, t: p.t - anchor }));
  const left = statistics(normalize(a, anchorA), from, to), right = statistics(normalize(b, anchorB), from, to);
  return left.map(l => { const r = right.find(x => x.channel === l.channel); return { channel: l.channel, meanA: l.mean, meanB: r?.mean ?? null, meanDelta: r ? r.mean - l.mean : null, countA: l.count, countB: r?.count ?? 0 }; });
}
