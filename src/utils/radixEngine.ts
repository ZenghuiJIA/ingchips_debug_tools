// Radix and Bitwise Engine using BigInt for 64-bit precision

export type BitWidth = 8 | 16 | 32 | 64;

export const WIDTH_MASKS: Record<BitWidth, bigint> = {
  8: 0xFFn,
  16: 0xFFFFn,
  32: 0xFFFFFFFFn,
  64: 0xFFFFFFFFFFFFFFFFn,
};

export const WIDTH_SIGN_BITS: Record<BitWidth, bigint> = {
  8: 0x80n,
  16: 0x8000n,
  32: 0x80000000n,
  64: 0x8000000000000000n,
};

// Normalize and mask a bigint to current bit width
export function maskValue(val: bigint, width: BitWidth): bigint {
  const mask = WIDTH_MASKS[width];
  return ((val % (mask + 1n)) + (mask + 1n)) % (mask + 1n) & mask;
}

// Format to Hex string without 0x prefix
export function toHexString(val: bigint, width: BitWidth): string {
  const masked = maskValue(val, width);
  const hexChars = width / 4;
  return masked.toString(16).toUpperCase().padStart(hexChars, '0');
}

// Format to Binary string without 0b prefix, optionally grouped by 4 bits
export function toBinString(val: bigint, width: BitWidth, grouped: boolean = true): string {
  const masked = maskValue(val, width);
  const rawBin = masked.toString(2).padStart(width, '0');
  if (!grouped) return rawBin;
  const groups: string[] = [];
  for (let i = 0; i < rawBin.length; i += 4) {
    groups.push(rawBin.slice(i, i + 4));
  }
  return groups.join(' ');
}

// Format to Octal string
export function toOctString(val: bigint, width: BitWidth): string {
  const masked = maskValue(val, width);
  return masked.toString(8);
}

// Format to Unsigned Decimal string
export function toDecString(val: bigint, width: BitWidth): string {
  const masked = maskValue(val, width);
  return masked.toString(10);
}

// Format to Signed Decimal string (two's complement)
export function toSignedDecString(val: bigint, width: BitWidth): string {
  const masked = maskValue(val, width);
  const signBit = WIDTH_SIGN_BITS[width];
  if ((masked & signBit) !== 0n) {
    const total = 1n << BigInt(width);
    const signedVal = masked - total;
    return signedVal.toString(10);
  }
  return masked.toString(10);
}

// Parse string from various radices safely
export function parseInputToBigInt(text: string, radix: 2 | 8 | 10 | 16): bigint | null {
  const clean = text.trim().replace(/\s+/g, '').replace(/_/g, '');
  if (!clean) return 0n;

  try {
    if (radix === 16) {
      const hex = clean.toLowerCase().startsWith('0x') ? clean.slice(2) : clean;
      if (!/^[0-9a-fA-F]+$/.test(hex)) return null;
      return BigInt('0x' + hex);
    } else if (radix === 2) {
      const bin = clean.toLowerCase().startsWith('0b') ? clean.slice(2) : clean;
      if (!/^[01]+$/.test(bin)) return null;
      return BigInt('0b' + bin);
    } else if (radix === 8) {
      const oct = clean.toLowerCase().startsWith('0o') ? clean.slice(2) : clean;
      if (!/^[0-7]+$/.test(oct)) return null;
      return BigInt('0o' + oct);
    } else {
      // Base 10
      if (!/^-?[0-9]+$/.test(clean)) return null;
      return BigInt(clean);
    }
  } catch (_) {
    return null;
  }
}

// Toggle a specific bit index (0 ~ width-1)
export function toggleBit(val: bigint, bitIndex: number, width: BitWidth): bigint {
  if (bitIndex < 0 || bitIndex >= width) return val;
  const bitMask = 1n << BigInt(bitIndex);
  return maskValue(val ^ bitMask, width);
}

// Set a specific bit to 1
export function setBit(val: bigint, bitIndex: number, width: BitWidth): bigint {
  if (bitIndex < 0 || bitIndex >= width) return val;
  const bitMask = 1n << BigInt(bitIndex);
  return maskValue(val | bitMask, width);
}

// Clear a specific bit to 0
export function clearBit(val: bigint, bitIndex: number, width: BitWidth): bigint {
  if (bitIndex < 0 || bitIndex >= width) return val;
  const bitMask = 1n << BigInt(bitIndex);
  return maskValue(val & ~bitMask, width);
}

// Check if a bit is 1
export function testBit(val: bigint, bitIndex: number): boolean {
  return ((val >> BigInt(bitIndex)) & 1n) === 1n;
}

// Count set bits (popcount)
export function countSetBits(val: bigint, width: BitWidth): number {
  const masked = maskValue(val, width);
  let count = 0;
  for (let i = 0; i < width; i++) {
    if (((masked >> BigInt(i)) & 1n) === 1n) count++;
  }
  return count;
}

// Count leading zeros
export function countLeadingZeros(val: bigint, width: BitWidth): number {
  const masked = maskValue(val, width);
  let count = 0;
  for (let i = width - 1; i >= 0; i--) {
    if (((masked >> BigInt(i)) & 1n) === 0n) {
      count++;
    } else {
      break;
    }
  }
  return count;
}

// Count trailing zeros
export function countTrailingZeros(val: bigint, width: BitWidth): number {
  const masked = maskValue(val, width);
  if (masked === 0n) return width;
  let count = 0;
  for (let i = 0; i < width; i++) {
    if (((masked >> BigInt(i)) & 1n) === 0n) {
      count++;
    } else {
      break;
    }
  }
  return count;
}

// Shift operations
export function shiftLeft(val: bigint, n: number, width: BitWidth): bigint {
  return maskValue(val << BigInt(n), width);
}

export function shiftRightLogical(val: bigint, n: number, width: BitWidth): bigint {
  const masked = maskValue(val, width);
  return masked >> BigInt(n);
}

export function shiftRightArithmetic(val: bigint, n: number, width: BitWidth): bigint {
  const masked = maskValue(val, width);
  const signBit = WIDTH_SIGN_BITS[width];
  const isNegative = (masked & signBit) !== 0n;
  const shifted = masked >> BigInt(n);
  if (isNegative) {
    // Fill high bits with 1s
    const fillMask = (WIDTH_MASKS[width] << BigInt(width - n)) & WIDTH_MASKS[width];
    return maskValue(shifted | fillMask, width);
  }
  return shifted;
}

export function rotateLeft(val: bigint, n: number, width: BitWidth): bigint {
  const shift = BigInt(n % width);
  if (shift === 0n) return maskValue(val, width);
  const masked = maskValue(val, width);
  const left = (masked << shift) & WIDTH_MASKS[width];
  const right = masked >> BigInt(width - Number(shift));
  return left | right;
}

export function rotateRight(val: bigint, n: number, width: BitWidth): bigint {
  const shift = BigInt(n % width);
  if (shift === 0n) return maskValue(val, width);
  const masked = maskValue(val, width);
  const right = masked >> shift;
  const left = (masked << BigInt(width - Number(shift))) & WIDTH_MASKS[width];
  return left | right;
}

// Endianness Swap
export function swapEndian(val: bigint, width: BitWidth): bigint {
  const masked = maskValue(val, width);
  const byteCount = width / 8;
  let res = 0n;
  for (let i = 0; i < byteCount; i++) {
    const byte = (masked >> BigInt(i * 8)) & 0xFFn;
    res = (res << 8n) | byte;
  }
  return res;
}

// Extract bytes as number array
export function getBytes(val: bigint, width: BitWidth, littleEndian: boolean = false): number[] {
  const masked = maskValue(val, width);
  const byteCount = width / 8;
  const bytes: number[] = [];
  for (let i = 0; i < byteCount; i++) {
    const b = Number((masked >> BigInt(i * 8)) & 0xFFn);
    bytes.push(b);
  }
  return littleEndian ? bytes : bytes.reverse();
}

// Interpret as float32
export function toFloat32(val: bigint): number {
  const u32 = Number(val & 0xFFFFFFFFn);
  const buf = new ArrayBuffer(4);
  const view = new DataView(buf);
  view.setUint32(0, u32, true); // little-endian
  return view.getFloat32(0, true);
}

// Interpret as ASCII characters (printable)
export function toAsciiString(val: bigint, width: BitWidth): string {
  const bytes = getBytes(val, width, false);
  return bytes
    .map(b => (b >= 32 && b <= 126 ? String.fromCharCode(b) : '·'))
    .join('');
}

// CRC Calculations
export function calcCrc16Modbus(data: Uint8Array): number {
  let crc = 0xFFFF;
  for (let i = 0; i < data.length; i++) {
    crc ^= data[i];
    for (let j = 0; j < 8; j++) {
      if ((crc & 0x0001) !== 0) {
        crc = (crc >> 1) ^ 0xA001;
      } else {
        crc >>= 1;
      }
    }
  }
  return crc & 0xFFFF;
}

export function calcCrc16Ccitt(data: Uint8Array): number {
  let crc = 0xFFFF;
  for (let i = 0; i < data.length; i++) {
    crc ^= (data[i] << 8);
    for (let j = 0; j < 8; j++) {
      if ((crc & 0x8000) !== 0) {
        crc = ((crc << 1) ^ 0x1021) & 0xFFFF;
      } else {
        crc = (crc << 1) & 0xFFFF;
      }
    }
  }
  return crc;
}

export function calcCrc32(data: Uint8Array): number {
  let crc = 0xFFFFFFFF;
  for (let i = 0; i < data.length; i++) {
    crc ^= data[i];
    for (let j = 0; j < 8; j++) {
      if ((crc & 1) !== 0) {
        crc = (crc >>> 1) ^ 0xEDB88320;
      } else {
        crc >>>= 1;
      }
    }
  }
  return (crc ^ 0xFFFFFFFF) >>> 0;
}

export function calcChecksum8(data: Uint8Array): number {
  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    sum = (sum + data[i]) & 0xFF;
  }
  return sum;
}

export function calcXor8(data: Uint8Array): number {
  let xor = 0;
  for (let i = 0; i < data.length; i++) {
    xor ^= data[i];
  }
  return xor & 0xFF;
}
