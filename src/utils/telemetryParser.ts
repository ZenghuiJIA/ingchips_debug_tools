/**
 * High-performance telemetry parser for serial data streams.
 * Automatically parses CSV, Key-Value pairs, and JSON data.
 */

export function parseTelemetryLine(rawLine: string): Record<string, number> | null {
  const line = rawLine.trim();
  if (!line || line.length < 1) return null;

  // 1. Try JSON if it looks like a JSON object
  if (line.startsWith('{') && line.endsWith('}')) {
    try {
      const obj = JSON.parse(line);
      const result: Record<string, number> = {};
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
    } catch {
      // Not valid JSON, fall through
    }
  }

  // 2. Try Key-Value pairs: key:value or key=value
  // Example: roll:12.3, pitch:45.6, yaw:-7.8 or temp=24.5 humi=60.1
  const kvRegex = /([a-zA-Z0-9_\u4e00-\u9fa5]+)\s*[:=]\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)/g;
  let match: RegExpExecArray | null;
  const kvResults: Record<string, number> = {};
  let kvCount = 0;

  while ((match = kvRegex.exec(line)) !== null) {
    const key = match[1];
    const val = Number(match[2]);
    if (!isNaN(val)) {
      kvResults[key] = val;
      kvCount++;
    }
  }

  if (kvCount > 0) {
    return kvResults;
  }

  // 3. Try CSV / Delimited floats: "12.3, 45.6, -7.8" or "12.3\t45.6\t-7.8"
  // Strip trailing/leading brackets if present: [12.3, 45.6]
  let cleaned = line;
  if (cleaned.startsWith('[') && cleaned.endsWith(']')) {
    cleaned = cleaned.slice(1, -1).trim();
  }

  const delimiter = cleaned.includes(',') ? ',' : (cleaned.includes('\t') ? '\t' : ' ');
  const tokens = cleaned.split(delimiter).map(t => t.trim()).filter(t => t.length > 0);

  if (tokens.length >= 1) {
    const numbers: number[] = [];
    for (const tok of tokens) {
      // Must look like a number
      if (!/^[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?$/.test(tok)) {
        return null;
      }
      const n = Number(tok);
      if (isNaN(n)) return null;
      numbers.push(n);
    }

    if (numbers.length > 0) {
      const res: Record<string, number> = {};
      numbers.forEach((val, idx) => {
        res[`CH${idx}`] = val;
      });
      return res;
    }
  }

  return null;
}

export const PRESET_CHANNEL_COLORS = [
  '#10b981', // emerald
  '#06b6d4', // cyan
  '#8b5cf6', // violet
  '#f59e0b', // amber
  '#f43f5e', // rose
  '#3b82f6', // blue
  '#84cc16', // lime
  '#ec4899', // pink
];
