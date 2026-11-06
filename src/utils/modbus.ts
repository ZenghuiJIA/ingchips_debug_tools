// Modbus Protocol Helper with Rust Native Backend Acceleration (RTU & ASCII)
import { safeInvoke } from './ipc';
import { jsCalculateModbusCrc } from './crc';

export type ModbusByteOrder = 'AB_CD' | 'CD_AB' | 'BA_DC' | 'DC_BA';

export type ModbusDisplayFormat =
  | 'uint16'
  | 'int16'
  | 'hex'
  | 'binary'
  | 'ascii'
  | 'uint32'
  | 'int32'
  | 'float32';

export interface ModbusRegisterRow {
  address: number;
  raw_hex: string;
  u16_val: number;
  i16_val: number;
  bool_val?: boolean;
}

export interface ModbusResponseResult {
  port: string;
  mode: 'rtu' | 'ascii';
  slave_id: number;
  func_code: number;
  is_exception: boolean;
  exception_code?: number;
  exception_desc?: string;
  description?: string;
  registers: ModbusRegisterRow[];
  raw_hex: string;
  raw_ascii?: string;
  timestamp_ms: number;
}

export interface ModbusSlaveProcessResult {
  response_bytes?: number[];
  updated_holding_registers: Record<number, number>;
  updated_coils: Record<number, boolean>;
  handled_func?: number;
  log_desc?: string;
}

/**
 * Reorders 4 bytes from two 16-bit registers according to Modbus byte order.
 * u0 (Reg 0) -> A (high byte), B (low byte)
 * u1 (Reg 1) -> C (high byte), D (low byte)
 */
export function getOrderedBytes32(u0: number, u1: number, order: ModbusByteOrder): [number, number, number, number] {
  const a = (u0 >> 8) & 0xFF;
  const b = u0 & 0xFF;
  const c = (u1 >> 8) & 0xFF;
  const d = u1 & 0xFF;

  switch (order) {
    case 'CD_AB': // Low word first, high byte first (Mid-Little, standard in many PLCs)
      return [c, d, a, b];
    case 'BA_DC': // High word first, byte swapped (Mid-Big)
      return [b, a, d, c];
    case 'DC_BA': // Pure Little Endian (Intel x86 memory layout)
      return [d, c, b, a];
    case 'AB_CD': // Standard Big Endian (Motorola)
    default:
      return [a, b, c, d];
  }
}

/**
 * Converts two contiguous 16-bit registers into formatted 32-bit values.
 */
export function parseModbus32Bit(
  u0: number,
  u1: number,
  format: 'uint32' | 'int32' | 'float32' | 'hex',
  order: ModbusByteOrder = 'AB_CD'
): string {
  const bytes = getOrderedBytes32(u0, u1, order);
  const buf = new ArrayBuffer(4);
  const view = new DataView(buf);
  for (let i = 0; i < 4; i++) {
    view.setUint8(i, bytes[i]);
  }

  if (format === 'float32') {
    const f = view.getFloat32(0, false);
    if (isNaN(f)) return 'NaN';
    if (!isFinite(f)) return f > 0 ? '+Infinity' : '-Infinity';
    return Math.abs(f) < 0.0001 && f !== 0 ? f.toExponential(4) : f.toFixed(4);
  }

  if (format === 'int32') {
    return view.getInt32(0, false).toString(10);
  }

  if (format === 'uint32') {
    return view.getUint32(0, false).toString(10);
  }

  // hex 32
  return '0x' + Array.from(bytes).map(b => b.toString(16).padStart(2, '0').toUpperCase()).join('');
}

/**
 * Formats a single 16-bit register into representation.
 */
export function formatSingleRegister(u16: number, format: 'uint16' | 'int16' | 'hex' | 'binary' | 'ascii'): string {
  const safeU16 = u16 & 0xFFFF;
  if (format === 'int16') {
    const i16 = safeU16 > 0x7FFF ? safeU16 - 0x10000 : safeU16;
    return i16.toString(10);
  }
  if (format === 'hex') {
    return '0x' + safeU16.toString(16).padStart(4, '0').toUpperCase();
  }
  if (format === 'binary') {
    const binStr = safeU16.toString(2).padStart(16, '0');
    return `${binStr.slice(0, 4)} ${binStr.slice(4, 8)} ${binStr.slice(8, 12)} ${binStr.slice(12, 16)}`;
  }
  if (format === 'ascii') {
    const c1 = String.fromCharCode((safeU16 >> 8) & 0xFF);
    const c2 = String.fromCharCode(safeU16 & 0xFF);
    const clean1 = (safeU16 >> 8) >= 32 && (safeU16 >> 8) <= 126 ? c1 : '.';
    const clean2 = (safeU16 & 0xFF) >= 32 && (safeU16 & 0xFF) <= 126 ? c2 : '.';
    return `"${clean1}${clean2}"`;
  }
  return safeU16.toString(10);
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

/**
 * Handles incoming Modbus frame as a simulated slave.
 */
export async function handleModbusSlaveFrame(
  slaveId: number,
  frameBytes: number[],
  holdingRegisters: Record<number, number>,
  inputRegisters: Record<number, number>,
  coils: Record<number, boolean>,
  discreteInputs: Record<number, boolean>
): Promise<ModbusSlaveProcessResult> {
  return await safeInvoke('modbus_slave_handle_request', {
    slaveId,
    frame: frameBytes,
    holdingRegisters,
    inputRegisters,
    coils,
    discreteInputs
  });
}
