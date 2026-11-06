import { safeInvoke, isTauri } from './ipc';
export interface CaptureStatus { session_id: string; recording: boolean; directory: string | null; error: string | null; latest_seq: number; first_seq: number }
export interface RawEvent { schema_version: number; session_id: string; seq: number; port: string; direction: string; elapsed_ms: number; wall_time_ms: number; data: string; message?: string }
export interface CapturePage { events: RawEvent[]; cursor: number; gap: boolean; status: CaptureStatus }
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
