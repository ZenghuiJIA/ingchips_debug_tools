export function parseHexUint(text: string, bits = 32): number {
  const raw = text.trim().replace(/^0x/i, '');
  if (!/^[\da-f]+$/i.test(raw)) throw new Error('请输入有效的十六进制数');
  const value = Number.parseInt(raw, 16);
  if (!Number.isSafeInteger(value) || value < 0 || value >= 2 ** bits) {
    throw new Error(`数值超出 ${bits} 位范围`);
  }
  return value;
}

export function compareValues(actual: number, expected: number, operator = '=='): boolean {
  switch (operator) {
    case '==': return actual === expected;
    case '!=': return actual !== expected;
    case '>': return actual > expected;
    case '<': return actual < expected;
    case '>=': return actual >= expected;
    case '<=': return actual <= expected;
    default: throw new Error('不支持的比较运算符');
  }
}

export type HardwareIntent = { action: 'probes' | 'fault' | 'reset' | 'boot' | 'read' | 'write'; address?: string; value?: string };

// Only complete commands are executable. Questions, negations and partial commands do not match.
export function parseHardwareIntent(prompt: string): HardwareIntent | null {
  const text = prompt.trim();
  if (/^(检测当前连接的硬件调试探针|列出探针|list probes)$/i.test(text)) return { action: 'probes' };
  if (/^(分析当前单片机 HardFault 崩溃原因|诊断 HardFault|diagnose hardfault)$/i.test(text)) return { action: 'fault' };
  if (/^(复位单片机并重启|复位单片机|reset target)$/i.test(text)) return { action: 'reset' };
  if (/^(切换至 ISP Bootloader 引导模式|进入 BOOT|enter bootloader)$/i.test(text)) return { action: 'boot' };
  const read = /^(?:读取(?: RAM)? 内存|read memory)\s+(0x[\da-f]{1,8})$/i.exec(text);
  if (read) return { action: 'read', address: read[1] };
  const write = /^(?:写入(?: RAM)? 内存|write memory)\s+(0x[\da-f]{1,8})\s+(0x[\da-f]{1,8})$/i.exec(text);
  if (write) {
    if (parseHexUint(write[1]) % 4) throw new Error('32 位写入地址必须按 4 字节对齐');
    return { action: 'write', address: write[1], value: write[2] };
  }
  return null;
}
