import type { PortInfo } from '../types';
export function deviceKey(port: PortInfo): string | null {
  return port.serial_number && port.vid != null && port.pid != null ? `${port.vid}:${port.pid}:${port.serial_number}` : null;
}
export function reconnectCandidate(key: string, ports: PortInfo[]): PortInfo | null {
  const matches = ports.filter(p => deviceKey(p) === key);
  return matches.length === 1 ? matches[0]! : null;
}
