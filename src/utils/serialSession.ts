import { safeInvoke, isTauri } from './ipc';
export interface CaptureStatus { session_id: string; recording: boolean; directory: string | null; error: string | null; latest_seq: number; first_seq: number }
export interface RawEvent { schema_version: number; session_id: string; seq: number; port: string; direction: string; elapsed_ms: number; wall_time_ms: number; data: string; message?: string }
export interface CapturePage { events: RawEvent[]; cursor: number; gap: boolean; status: CaptureStatus }

export type NetworkTabMode = 'tcp_client' | 'tcp_server' | 'udp_socket';
export interface NetworkTabDescriptor { mode: NetworkTabMode; host: string; port: number }
export interface NetworkStreamState { name: string; mode: string; host?: string; port?: number; is_connected?: boolean }

/** Parse the stable tab name used by the network manager without touching hardware. */
export function parseNetworkTabName(name: string): NetworkTabDescriptor | null {
  const match = /^(TCP-Client|TCP-Server|UDP):(.*):(\d+)$/.exec(name);
  if (!match) return null;
  const port = Number(match[3]);
  if (!Number.isInteger(port) || port < 0 || port > 65535) return null;
  return {
    mode: match[1] === 'TCP-Client' ? 'tcp_client' : match[1] === 'TCP-Server' ? 'tcp_server' : 'udp_socket',
    host: match[2],
    port,
  };
}

export function networkModeMatches(mode: string, expected: NetworkTabMode): boolean {
  const normalized = mode.toLowerCase().replace(/[-_]/g, '');
  return normalized === expected.replace(/[-_]/g, '') ||
    (expected === 'tcp_client' && normalized === 'tcpclient') ||
    (expected === 'tcp_server' && normalized === 'tcpserver') ||
    (expected === 'udp_socket' && (normalized === 'udp' || normalized === 'udpsocket'));
}

export function networkStateForTab(name: string, streams: NetworkStreamState[]): { isConnected: boolean; isListening: boolean } | null {
  const descriptor = parseNetworkTabName(name);
  if (!descriptor) return null;
  const stream = streams.find(item => item.name === name);
  if (!stream) return { isConnected: false, isListening: false };
  return {
    isConnected: Boolean(stream.is_connected),
    isListening: networkModeMatches(stream.mode, 'tcp_server') && !Boolean(stream.is_connected),
  };
}
export async function serialIdentity(port: string): Promise<string | null> {
  if (!isTauri()) throw new Error('浏览器预览不能执行硬件操作');
  if (/^(TCP|UDP)/.test(port)) return null;
  const page = await safeInvoke<CapturePage>('serial_capture_read', { portName: port, after: 0, limit: 1 });
  return page.status.session_id;
}
export async function guardedSend(port: string, sessionId: string | null, data: number[]): Promise<number> {
  if (!isTauri()) throw new Error('浏览器预览不能执行硬件操作');
  if (sessionId) return safeInvoke('serial_send_guarded', { portName: port, sessionId, data });
  return safeInvoke('send_serial_data', { portName: port, data });
}
