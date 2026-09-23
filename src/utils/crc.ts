// Fast CRC and Checksum utilities with Rust acceleration fallback
import { safeInvoke } from './ipc';

export type ChecksumAlgorithm = 'none' | 'modbus_crc16' | 'crc16_ccitt' | 'checksum8' | 'xor8';

/**
 * Calculates Modbus CRC16 in JavaScript (lookup-table equivalent or bitwise)
 * Returns { low: number, high: number, crc: number }
 */
export function jsCalculateModbusCrc(data: number[]): { low: number; high: number; crc: number } {
  let crc = 0xFFFF;
  for (const byte of data) {
    crc ^= (byte & 0xFF);
    for (let i = 0; i < 8; i++) {
      if ((crc & 0x0001) !== 0) {
        crc = (crc >> 1) ^ 0xA001;
      } else {
        crc >>= 1;
      }
    }
  }
  const low = crc & 0xFF;
  const high = (crc >> 8) & 0xFF;
  return { low, high, crc };
}

/**
 * High-performance checksum append, powered by Rust backend with JS fallback.
 */
export async function appendChecksum(data: number[], algo: ChecksumAlgorithm): Promise<number[]> {
  if (algo === 'none' || data.length === 0) return [...data];

  try {
    const result: number[] = await safeInvoke('compute_checksum', {
      data,
      algo
    });
    return result;
  } catch (err) {
    // Fallback to JS computation if running outside Tauri
    const result = [...data];
    if (algo === 'modbus_crc16') {
      const { low, high } = jsCalculateModbusCrc(data);
      result.push(low, high);
    } else if (algo === 'checksum8') {
      let sum = 0;
      for (const b of data) sum = (sum + b) & 0xFF;
      result.push(sum);
    } else if (algo === 'xor8') {
      let xor = 0;
      for (const b of data) xor ^= b;
      result.push(xor);
    }
    return result;
  }
}
