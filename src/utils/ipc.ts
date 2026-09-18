import { invoke as tauriInvoke } from '@tauri-apps/api/core';

export const isTauri = (): boolean => {
  return typeof window !== 'undefined' && '__TAURI_INTERNALS__' in window;
};

export async function safeInvoke<T = any>(cmd: string, args: Record<string, any> = {}): Promise<T> {
  if (isTauri()) {
    return tauriInvoke<T>(cmd, args);
  }

  // Web Browser Mock Fallback (Allows testing UI in browser)
  console.warn(`[Browser Preview] Tauri backend not detected. Mocking IPC command: ${cmd}`, args);

  if (cmd === 'list_serial_ports') {
    return [
      {
        port_name: 'COM10',
        description: 'INGCHIPS CMSIS-DAP',
        vid: 0x0D28,
        pid: 0x0204,
        manufacturer: 'INGCHIPS',
        product: 'CMSIS-DAP',
        serial_number: '6E197F26',
        is_daplink: true,
        device_type: 'daplink'
      },
      {
        port_name: 'COM5',
        description: 'J-Link CDC UART Port',
        vid: 0x1366,
        pid: 0x1051,
        manufacturer: 'SEGGER',
        product: 'J-Link',
        serial_number: '000123456',
        is_daplink: false,
        device_type: 'jlink'
      },
      {
        port_name: 'COM3',
        description: 'USB-SERIAL CH340',
        vid: 0x1A86,
        pid: 0x7523,
        manufacturer: 'wch.cn',
        product: 'CH340',
        serial_number: null,
        is_daplink: false,
        device_type: 'generic'
      }
    ] as any;
  }

  if (cmd === 'get_system_metrics') {
    return {
      tauri_rss_mb: 22.3,
      daemon_rss_mb: 0.0,
      total_rss_mb: 22.3,
      memory_budget_mb: 100.0,
      is_under_budget: true,
      os_name: 'windows',
      target_arch: 'x86_64'
    } as any;
  }

  if (cmd === 'get_serial_status') {
    return [false, null, false, true, false] as any;
  }

  if (cmd === 'open_serial_port') {
    return true as any;
  }

  if (cmd === 'close_serial_port') {
    return true as any;
  }

  if (cmd === 'send_serial_data') {
    return (args.data?.length || 0) as any;
  }

  if (cmd === 'set_dtr' || cmd === 'set_rts' || cmd === 'execute_reset_sequence') {
    return true as any;
  }

  if (cmd === 'pyocd_list_probes') {
    return [
      {
        unique_id: '6E197F26',
        description: 'INGCHIPS CMSIS-DAP',
        vendor_name: 'INGCHIPS',
        product_name: 'CMSIS-DAP',
        probe_type: 'daplink',
        type_label: 'CMSIS-DAP'
      },
      {
        unique_id: '000123456',
        description: 'SEGGER J-Link V11',
        vendor_name: 'SEGGER',
        product_name: 'J-Link',
        probe_type: 'jlink',
        type_label: 'J-Link'
      }
    ] as any;
  }

  if (cmd === 'pyocd_diagnose_hardfault') {
    return {
      summary: '=== Cortex-M HardFault 智能分析诊断报告 (浏览器模拟预览) ===\n崩溃发生程序计数器 (PC): 0x08001234\n返回链接寄存器 (LR): 0xFFFFFFF9\n主栈指针 (MSP): 0x20004FB0\n• 触发状态标志: PRECISERR, BFARVALID\n  - 精确数据总线故障，故障地址为 0x4002101C。',
      recommendations: [
        '检查对地址 0x4002101C 的读写操作：确认对应外设时钟是否已开启。',
        '检查函数指针跳转：ARM Cortex-M 仅支持 Thumb 模式。'
      ],
      raw_dump: {
        target: 'STM32F407VG',
        core_registers: {
          R0: '0x00000000', R1: '0x20000100', R2: '0x00000004', R12: '0x00000000',
          SP: '0x20004FB0', LR: '0xFFFFFFF9', PC: '0x08001234', xPSR: '0x61000000',
          MSP: '0x20004FB0', PSP: '0x20000000'
        },
        fault_registers: {
          CFSR: '0x00008200', HFSR: '0x40000000', MMFAR: '0x00000000', BFAR: '0x4002101C'
        },
        cfsr_decoded: {
          raw_cfsr: '0x00008200', mmfsr: '0x00', bfsr: '0x82', ufsr: '0x0000',
          flags: ['PRECISERR', 'BFARVALID (Address: 0x4002101C)'],
          explanations: [
            'Precise data access bus fault. Fault address is known: 0x4002101C.',
            'BFAR holds valid bus fault address: 0x4002101C.'
          ]
        },
        hfsr_decoded: {
          raw_hfsr: '0x40000000',
          flags: ['FORCED'],
          explanations: ['Forced HardFault: a configurable fault escalated to HardFault.']
        }
      }
    } as any;
  }

  if (cmd === 'pyocd_read_memory') {
    return {
      address: args.address || '0x20000000',
      count: args.count || 64,
      bytes: Array.from({ length: args.count || 64 }, (_, i) => (i * 7) % 256),
      hex_dump: '00 07 0E 15 1C 23 2A 31 38 3F 46 4D 54 5B 62 69'
    } as any;
  }

  return {} as any;
}
