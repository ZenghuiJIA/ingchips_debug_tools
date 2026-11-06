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

export type HardwareIntent =
  | { action: 'probes' | 'fault' | 'reset' | 'boot' }
  | { action: 'read'; address: string }
  | { action: 'write'; address: string; value: string }
  | { action: 'list_serial_ports' }
  | { action: 'read_serial_data'; port?: string }
  | { action: 'send_serial_data'; data: string; port?: string }
  | { action: 'read_core_registers' }
  | { action: 'reset_target_swd' };

// Only complete commands are executable. Questions, negations and partial commands do not match.
export function parseHardwareIntent(prompt: string): HardwareIntent | null {
  const text = prompt.trim();
  if (/^(检测当前连接的硬件调试探针|列出探针|list probes)$/i.test(text)) return { action: 'probes' };
  if (/^(分析当前单片机 HardFault 崩溃原因|分析当前单片机 HardFault 故障原因|诊断 HardFault|diagnose hardfault)$/i.test(text)) return { action: 'fault' };
  if (/^(复位单片机并重启|复位单片机|reset target)$/i.test(text)) return { action: 'reset' };
  if (/^(切换至 ISP Bootloader 引导模式|进入 BOOT|enter bootloader)$/i.test(text)) return { action: 'boot' };

  if (/^(扫描可用串口|扫描串口|列出可用串口|列出串口|list serial ports|scan serial ports)$/i.test(text)) {
    return { action: 'list_serial_ports' };
  }
  if (/^(读取串口最新数据|读取串口数据|获取串口数据|read serial data)$/i.test(text)) {
    return { action: 'read_serial_data' };
  }
  const sendSerial = /^(?:发送串口数据|send serial data)\s+(.+)$/i.exec(text);
  if (sendSerial) {
    return { action: 'send_serial_data', data: sendSerial[1].trim() };
  }
  if (/^(读取 CPU 核心寄存器|读取核心寄存器|查看核心寄存器|read core registers)$/i.test(text)) {
    return { action: 'read_core_registers' };
  }
  if (/^(SWD 目标复位|SWD 复位目标|SWD 硬件复位|reset target swd)$/i.test(text)) {
    return { action: 'reset_target_swd' };
  }

  const read = /^(?:读取(?: RAM)? 内存|read memory)\s+(0x[\da-f]{1,8})$/i.exec(text);
  if (read) return { action: 'read', address: read[1] };
  const write = /^(?:写入(?: RAM)? 内存|write memory)\s+(0x[\da-f]{1,8})\s+(0x[\da-f]{1,8})$/i.exec(text);
  if (write) {
    if (parseHexUint(write[1]) % 4) throw new Error('32 位写入地址必须按 4 字节对齐');
    return { action: 'write', address: write[1], value: write[2] };
  }
  return null;
}
