// Bluetooth Core, legacy two-wire DTM: command[15:14], channel[13:8], length[7:2], payload[1:0].
export function buildDtmCommand(mode: 'tx' | 'rx', channel: number, length: number, payload: string, phy: string): number[] {
  if (phy !== '1M') throw new Error('当前两线 DTM 支持 1M PHY；扩展 PHY 尚未接入');
  if (!Number.isInteger(channel) || channel < 0 || channel > 39) throw new Error('DTM 频点必须为 0~39');
  if (!Number.isInteger(length) || length < 0 || length > 63) throw new Error('当前 DTM 长度范围为 0~63 字节');
  const payloads: Record<string, number> = { prbs9: 0, '1111': 1, '1010': 2 };
  if (!(payload in payloads)) throw new Error('单载波属于厂商扩展，当前未接入');
  const word = ((mode === 'tx' ? 2 : 1) << 14) | (channel << 8) | (mode === 'tx' ? (length << 2) | payloads[payload] : 0);
  return [word >>> 8, word & 255];
}

export const DTM_TEST_END = [0xc0, 0x00];

export class H4Decoder {
  private buffer: number[] = [];
  reset() { this.buffer = []; }
  push(chunk: Uint8Array): Uint8Array[] {
    this.buffer.push(...chunk);
    const frames: Uint8Array[] = [];
    while (this.buffer.length) {
      const type = this.buffer[0];
      const header = type === 1 ? 4 : type === 2 || type === 5 ? 5 : type === 3 ? 4 : type === 4 ? 3 : 0;
      if (!header) { this.buffer.shift(); continue; }
      if (this.buffer.length < header) break;
      const length = type === 2 || type === 5
        ? this.buffer[3] | ((this.buffer[4] & (type === 5 ? 0x3f : 0xff)) << 8)
        : this.buffer[header - 1];
      if (this.buffer.length < header + length) break;
      frames.push(Uint8Array.from(this.buffer.splice(0, header + length)));
    }
    return frames;
  }
}
