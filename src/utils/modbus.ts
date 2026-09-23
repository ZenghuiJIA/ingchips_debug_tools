// Modbus Protocol Helper with Rust Native Backend Acceleration (RTU & ASCII)
import { safeInvoke } from './ipc';
import { jsCalculateModbusCrc } from './crc';

export interface ModbusRegisterRow {
  address: number;
  raw_hex: string;
  u16_val: number;
  i16_val: number;
}

export interface ModbusResponseResult {
  port: string;
  mode: 'rtu' | 'ascii';
  slave_id: number;
  func_code: number;
  is_exception: boolean;
  exception_code?: number;
  exception_desc?: string;
  registers: ModbusRegisterRow[];
  raw_hex: string;
  raw_ascii?: string;
  timestamp_ms: number;
}

/**
 * Builds a Modbus request frame (RTU or ASCII) with automatic checksum appended.
 */
export async function buildModbusRequest(
  slaveId: number,
  funcCode: number,
  startAddr: number,
  countOrVal: number,
  extraValues?: number[],
  mode: 'rtu' | 'ascii' = 'rtu'
): Promise<number[]> {
  if (mode === 'ascii') {
    try {
      const bytes: number[] = await safeInvoke('modbus_build_ascii_request', {
        slaveId,
        funcCode,
        startAddr,
        countOrVal,
        extraValues: extraValues || null
      });
      return bytes;
    } catch (_) {
      // JS fallback ASCII
      const pdu = [slaveId, funcCode, (startAddr >> 8) & 0xFF, startAddr & 0xFF, (countOrVal >> 8) & 0xFF, countOrVal & 0xFF];
      let sum = 0;
      for (const b of pdu) sum = (sum + b) & 0xFF;
      const lrc = ((~sum + 1) & 0xFF);
      let asciiStr = ':';
      for (const b of pdu) asciiStr += b.toString(16).padStart(2, '0').toUpperCase();
      asciiStr += lrc.toString(16).padStart(2, '0').toUpperCase() + '\r\n';
      return Array.from(new TextEncoder().encode(asciiStr));
    }
  }

  try {
    const bytes: number[] = await safeInvoke('modbus_build_request', {
      slaveId,
      funcCode,
      startAddr,
      countOrVal,
      extraValues: extraValues || null
    });
    return bytes;
  } catch (err) {
    // JS Fallback builder
    const frame: number[] = [slaveId, funcCode];
    if (funcCode >= 1 && funcCode <= 4) {
      frame.push((startAddr >> 8) & 0xFF, startAddr & 0xFF);
      frame.push((countOrVal >> 8) & 0xFF, countOrVal & 0xFF);
    } else if (funcCode === 5) {
      frame.push((startAddr >> 8) & 0xFF, startAddr & 0xFF);
      const val = countOrVal !== 0 ? 0xFF00 : 0x0000;
      frame.push((val >> 8) & 0xFF, val & 0xFF);
    } else if (funcCode === 6) {
      frame.push((startAddr >> 8) & 0xFF, startAddr & 0xFF);
      frame.push((countOrVal >> 8) & 0xFF, countOrVal & 0xFF);
    } else {
      frame.push((startAddr >> 8) & 0xFF, startAddr & 0xFF);
      frame.push((countOrVal >> 8) & 0xFF, countOrVal & 0xFF);
    }
    const { low, high } = jsCalculateModbusCrc(frame);
    frame.push(low, high);
    return frame;
  }
}

/**
 * Parses an incoming Modbus RTU or ASCII response frame.
 */
export async function parseModbusResponse(
  port: string,
  startAddr: number,
  frameBytes: number[]
): Promise<ModbusResponseResult> {
  return await safeInvoke('modbus_parse_response', {
    port,
    startAddr,
    frame: frameBytes
  });
}
