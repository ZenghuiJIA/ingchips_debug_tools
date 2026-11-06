export interface SerialAppearance {
  fontFamily: string;
  fontSize: number;
  foreground: string;
  background: string;
  txColor: string;
  infoColor: string;
  errorColor: string;
}

export const SERIAL_APPEARANCE_KEY = 'ai_hil_serial_appearance_v1';
export const DEFAULT_SERIAL_APPEARANCE: Readonly<SerialAppearance> = Object.freeze({
  fontFamily: 'Consolas, "Fira Code", monospace, "Courier New"',
  fontSize: 12,
  foreground: '#6ee7b7',
  background: '#09090b',
  txColor: '#7dd3fc',
  infoColor: '#fcd34d',
  errorColor: '#fb7185',
});

/** Treat persisted browser data as untrusted; never persist connection/runtime state. */
export function normalizeSerialAppearance(value: unknown): SerialAppearance {
  const source = value && typeof value === 'object' ? value as Record<string, unknown> : {};
  const result = { ...DEFAULT_SERIAL_APPEARANCE };
  if (typeof source.fontFamily === 'string' && source.fontFamily.trim().length > 0 && source.fontFamily.length <= 200 && !/[\x00-\x1f;{}<>]/.test(source.fontFamily)) {
    result.fontFamily = source.fontFamily.trim();
  }
  if (typeof source.fontSize === 'number' && Number.isFinite(source.fontSize) && source.fontSize >= 8 && source.fontSize <= 32) {
    result.fontSize = source.fontSize;
  }
  for (const key of ['foreground', 'background', 'txColor', 'infoColor', 'errorColor'] as const) {
    if (typeof source[key] === 'string' && /^#[0-9a-f]{6}$/i.test(source[key])) result[key] = source[key];
  }
  return result;
}

type PreferenceStorage = Pick<Storage, 'getItem' | 'setItem'>;
export function loadSerialAppearance(storage: () => PreferenceStorage): { appearance: SerialAppearance; error: string } {
  try {
    const raw = storage().getItem(SERIAL_APPEARANCE_KEY);
    return { appearance: normalizeSerialAppearance(raw === null ? null : JSON.parse(raw)), error: '' };
  } catch (error) {
    return { appearance: { ...DEFAULT_SERIAL_APPEARANCE }, error: String(error) };
  }
}

export function saveSerialAppearance(storage: () => PreferenceStorage, value: SerialAppearance): string {
  try {
    storage().setItem(SERIAL_APPEARANCE_KEY, JSON.stringify(normalizeSerialAppearance(value)));
    return '';
  } catch (error) { return String(error); }
}

export function serialLogStyle(value: SerialAppearance) {
  return { fontFamily: value.fontFamily, fontSize: `${value.fontSize}px`, color: value.foreground, backgroundColor: value.background };
}

export function serialLogColor(value: SerialAppearance, type: 'rx' | 'tx' | 'info' | 'error'): string {
  return type === 'tx' ? value.txColor : type === 'info' ? value.infoColor : type === 'error' ? value.errorColor : value.foreground;
}

export function serialXtermOptions(value: SerialAppearance) {
  return {
    fontFamily: value.fontFamily,
    fontSize: value.fontSize,
    theme: { background: value.background, foreground: value.foreground, cursor: value.foreground },
  };
}

interface ScrollableTerminal {
  buffer: { active: { viewportY: number } };
  write(bytes: Uint8Array, callback: () => void): void;
  scrollToBottom(): void;
  scrollToLine(line: number): void;
}

/** Follow output once, after xterm's asynchronous parser finishes; never on a timer. */
export function writeSerialOutput(term: ScrollableTerminal, bytes: Uint8Array, autoScroll: () => boolean, isActive: () => boolean): void {
  if (bytes.length === 0) return;
  const viewport = term.buffer.active.viewportY;
  term.write(bytes, () => {
    if (!isActive()) return;
    if (autoScroll()) term.scrollToBottom();
    else term.scrollToLine(viewport);
  });
}
