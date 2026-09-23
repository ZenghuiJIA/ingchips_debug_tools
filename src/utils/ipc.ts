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

  if (cmd === 'pick_firmware_file') {
    return 'C:/ming/source/tools/test_tools/exp_ING9188xx.axf' as any;
  }

  if (cmd === 'pyocd_diagnose_hardfault') {
    return {
      summary: '=== Cortex-M HardFault 智能分析诊断报告 (浏览器模拟预览) ===\n当前程序计数器 (PC): 0x02008E12\n返回链接寄存器 (LR/EXC_RETURN): 0xFFFFFFFD\n主栈指针 (MSP): 0x20004FB0\n进程栈指针 (PSP): 0x200021A0\n• 异常压栈指针: 【PSP】 (地址: 0x200021A0)\nEXC_RETURN: 0xFFFFFFFD (返回线程模式使用进程栈 (PSP)，标准整数异常帧 (8 Words))\n• 真实崩溃指令地址 (Stacked PC): 0x02008E12 (HardFault_Test_Crash+0x1A) -> main.c:48\n• 故障类型: 强制硬故障 (Forced HardFault)，由低级故障升级触发。\n• 触发状态标志: PRECISERR, BFARVALID (Address: 0x4002101C)\n  - 精确数据总线故障，故障地址为 0x4002101C。',
      recommendations: [
        '检查对地址 0x4002101C 的读写操作：确认对应外设时钟是否已开启。',
        '检查函数指针跳转：ARM Cortex-M 仅支持 Thumb 模式。'
      ],
      raw_dump: {
        target: 'ING9188xx',
        core_registers: {
          R0: '0x00000000', R1: '0x20000100', R2: '0x00000004', R3: '0x00000000',
          R4: '0x00000000', R5: '0x00000000', R6: '0x00000000', R7: '0x00000000',
          R8: '0x00000000', R9: '0x00000000', R10: '0x00000000', R11: '0x00000000',
          R12: '0x00000000', SP: '0x20004FB0', LR: '0xFFFFFFFD', PC: '0x02008E12',
          xPSR: '0x61000000', MSP: '0x20004FB0', PSP: '0x200021A0'
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
      },
      deep_analysis: {
        exc_return: {
          raw_hex: '0xFFFFFFFD',
          is_handler: false,
          is_psp: true,
          has_fpu_frame: false,
          active_sp_name: 'PSP',
          description: '返回线程模式使用进程栈 (PSP)，标准整数异常帧 (8 Words)'
        },
        active_sp_name: 'PSP',
        active_sp_val: '0x200021A0',
        exception_frame: {
          r0: '0x00000000',
          r1: '0x20000100',
          r2: '0x00000004',
          r3: '0x00000000',
          r12: '0x00000000',
          lr: '0x02008DFC',
          pc: '0x02008E12',
          xpsr: '0x61000000',
          pc_val: 0x02008e12,
          lr_val: 0x02008dfc,
          stacked_sp: '0x200021C0',
          has_fpu: false
        },
        crash_location: {
          address: '0x02008E12',
          func_name: 'HardFault_Test_Crash',
          func_size: 40,
          offset: 26,
          offset_str: '+0x1A',
          file_path: 'C:/projects/firmware/src/main.c',
          file_name: 'main.c',
          line: 48,
          column: 5,
          source_snippet: [
            { line: 45, code: 'void HardFault_Test_Crash(void) {', is_target: false },
            { line: 46, code: '    volatile uint32_t *bad_ptr = (volatile uint32_t *)0x4002101C;', is_target: false },
            { line: 47, code: '    // Attempt unclocked peripheral access to trigger BusFault', is_target: false },
            { line: 48, code: '    *bad_ptr = 0xDEADBEEF;', is_target: true },
            { line: 49, code: '}', is_target: false }
          ],
          disassembly: []
        },
        crash_disassembly: [
          { address: '0x02008E08', mnemonic: 'ldr', op_str: 'r3, [pc, #20]', size: 2, bytes: '4b05', is_target: false, func_name: 'HardFault_Test_Crash' },
          { address: '0x02008E0A', mnemonic: 'ldr', op_str: 'r2, [pc, #20]', size: 2, bytes: '4a05', is_target: false, func_name: 'HardFault_Test_Crash' },
          { address: '0x02008E0C', mnemonic: 'str', op_str: 'r3, [sp, #4]', size: 2, bytes: '9301', is_target: false, func_name: 'HardFault_Test_Crash' },
          { address: '0x02008E0E', mnemonic: 'ldr', op_str: 'r3, [sp, #4]', size: 2, bytes: '9b01', is_target: false, func_name: 'HardFault_Test_Crash' },
          { address: '0x02008E10', mnemonic: 'str', op_str: 'r2, [r3, #0]', size: 2, bytes: '601a', is_target: true, func_name: 'HardFault_Test_Crash', file: 'main.c', line: 48 },
          { address: '0x02008E12', mnemonic: 'nop', op_str: '', size: 2, bytes: 'bf00', is_target: false, func_name: 'HardFault_Test_Crash' },
          { address: '0x02008E14', mnemonic: 'bx', op_str: 'lr', size: 2, bytes: '4770', is_target: false, func_name: 'HardFault_Test_Crash' }
        ],
        handler_pc: '0x02000188',
        handler_disassembly: [
          { address: '0x02000188', mnemonic: 'b', op_str: '0x2000188', size: 2, bytes: 'e7fe', is_target: true, func_name: 'HardFault_Handler' }
        ],
        psp_call_stack: [
          {
            frame_index: 0,
            address: '0x200021B8',
            return_address: '0x02008E12',
            is_crash_instruction: true,
            source_info: {
              address: '0x02008E12',
              func_name: 'HardFault_Test_Crash',
              func_size: 40,
              offset: 26,
              offset_str: '+0x1A',
              file_path: 'C:/projects/firmware/src/main.c',
              file_name: 'main.c',
              line: 48,
              column: 5,
              source_snippet: [
                { line: 46, code: '    volatile uint32_t *bad_ptr = (volatile uint32_t *)0x4002101C;', is_target: false },
                { line: 47, code: '    // Attempt unclocked peripheral access to trigger BusFault', is_target: false },
                { line: 48, code: '    *bad_ptr = 0xDEADBEEF;', is_target: true },
                { line: 49, code: '}', is_target: false }
              ],
              disassembly: []
            },
            disassembly: [
              { address: '0x02008E0E', mnemonic: 'ldr', op_str: 'r3, [sp, #4]', size: 2, bytes: '9b01', is_target: false },
              { address: '0x02008E10', mnemonic: 'str', op_str: 'r2, [r3, #0]', size: 2, bytes: '601a', is_target: true },
              { address: '0x02008E12', mnemonic: 'nop', op_str: '', size: 2, bytes: 'bf00', is_target: false }
            ]
          },
          {
            frame_index: 1,
            address: '0x200021B4',
            return_address: '0x02008DFC',
            is_exception_return: false,
            source_info: {
              address: '0x02008DFC',
              func_name: 'app_task_process',
              func_size: 120,
              offset: 68,
              offset_str: '+0x44',
              file_path: 'C:/projects/firmware/src/app_task.c',
              file_name: 'app_task.c',
              line: 112,
              column: 9,
              source_snippet: [
                { line: 110, code: '    if (event & EVENT_FAULT_TRIGGER) {', is_target: false },
                { line: 111, code: '        printf("Triggering fault test...\\r\\n");', is_target: false },
                { line: 112, code: '        HardFault_Test_Crash();', is_target: true },
                { line: 113, code: '    }', is_target: false }
              ],
              disassembly: []
            },
            disassembly: [
              { address: '0x02008DF6', mnemonic: 'bl', op_str: '0x02008E08', size: 4, bytes: 'f000 f807', is_target: true }
            ]
          },
          {
            frame_index: 2,
            address: '0x20002198',
            return_address: '0x02009240',
            is_exception_return: false,
            source_info: {
              address: '0x02009240',
              func_name: 'os_task_entry',
              func_size: 80,
              offset: 32,
              offset_str: '+0x20',
              file_path: 'C:/projects/firmware/kernel/os_task.c',
              file_name: 'os_task.c',
              line: 65,
              column: 9,
              source_snippet: [
                { line: 64, code: '    while(1) {', is_target: false },
                { line: 65, code: '        task_handler(param);', is_target: true },
                { line: 66, code: '    }', is_target: false }
              ],
              disassembly: []
            },
            disassembly: []
          }
        ],
        msp_call_stack: [
          {
            frame_index: 0,
            address: '0x20004FA8',
            return_address: '0x02000188',
            is_crash_instruction: false,
            source_info: {
              address: '0x02000188',
              func_name: 'HardFault_Handler',
              func_size: 16,
              offset: 4,
              offset_str: '+0x04',
              file_path: 'C:/projects/firmware/arch/startup.s',
              file_name: 'startup.s',
              line: 142,
              column: 1,
              source_snippet: [
                { line: 141, code: 'HardFault_Handler    PROC', is_target: false },
                { line: 142, code: '    B       .', is_target: true },
                { line: 143, code: '    ENDP', is_target: false }
              ],
              disassembly: []
            },
            disassembly: [
              { address: '0x02000188', mnemonic: 'b', op_str: '0x2000188', size: 2, bytes: 'e7fe', is_target: true }
            ]
          }
        ],
        axf_loaded: true,
        axf_path: 'C:/projects/firmware/output/exp_ING9188xx.axf',
        active_stack_desc: '异常压栈指针: 【PSP】 (地址: 0x200021A0)\nEXC_RETURN: 0xFFFFFFFD (返回线程模式使用进程栈 (PSP)，标准整数异常帧 (8 Words))',
        crash_point_desc: '真实崩溃指令地址 (Stacked PC): 0x02008E12 (HardFault_Test_Crash+0x1A) -> main.c:48'
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

  if (cmd === 'analyze_firmware_resources') {
    return {
      file_path: args.file_path || 'C:/projects/firmware/output/app.axf',
      file_name: args.file_path ? args.file_path.split(/[\\/]/).pop() : 'app.axf',
      file_size: 1458920,
      file_size_str: '1.39 MB',
      toolchain: {
        type: 'gcc',
        name: 'GNU Arm GCC (GCC: (Arm GNU Toolchain 15.2.Rel1) 15.2.1)',
        raw_producer: 'GNU C23 15.2.1 20251203 -mthumb -mcpu=cortex-m4'
      },
      architecture: 'ARM Cortex-M',
      summary: {
        code_bytes: 46984,
        ro_data_bytes: 8,
        rw_data_bytes: 252,
        zi_data_bytes: 19128,
        rom_total_bytes: 47244,
        ram_total_bytes: 19380,
        code_str: '45.88 KB',
        ro_data_str: '8 B',
        rw_data_str: '252 B',
        zi_data_str: '18.68 KB',
        rom_total_str: '46.14 KB',
        ram_total_str: '18.93 KB',
        rom_code_ratio: 99.4,
        rom_ro_ratio: 0.1,
        rom_rw_ratio: 0.5,
        ram_rw_ratio: 1.3,
        ram_zi_ratio: 98.7,
        chip_flash_size: args.chip_flash_size || 524288,
        chip_ram_size: args.chip_ram_size || 65536,
        chip_flash_str: '512.00 KB',
        chip_ram_str: '64.00 KB',
        flash_usage_percent: 9.01,
        ram_usage_percent: 29.57,
        flash_free_bytes: 477044,
        ram_free_bytes: 46156,
        flash_free_str: '465.86 KB',
        ram_free_str: '45.07 KB'
      },
      sections: [
        { name: '.text', type: 'SHT_PROGBITS', address: '0x02028000', raw_address: 0x02028000, size: 46984, size_str: '45.88 KB', flags: 'AX', category: 'Code', target: 'ROM' },
        { name: '.ARM.exidx', type: 'SHT_ARM_EXIDX', address: '0x02033788', raw_address: 0x02033788, size: 8, size_str: '8 B', flags: 'A', category: 'RO-Data', target: 'ROM' },
        { name: '.data', type: 'SHT_PROGBITS', address: '0x20000D18', raw_address: 0x20000D18, size: 252, size_str: '252 B', flags: 'WA', category: 'RW-Data', target: 'ROM+RAM' },
        { name: '.bss', type: 'SHT_NOBITS', address: '0x20000E18', raw_address: 0x20000E18, size: 19128, size_str: '18.68 KB', flags: 'WA', category: 'ZI-Data', target: 'RAM' }
      ],
      modules: [
        {
          name: 'reent.c',
          full_path: 'libc/sys/reent.c',
          code: 16039,
          ro_data: 0,
          rw_data: 124,
          zi_data: 1310,
          rom_total: 16163,
          ram_total: 1434,
          code_str: '15.66 KB',
          ro_data_str: '0 B',
          rw_data_str: '124 B',
          zi_data_str: '1.28 KB',
          rom_total_str: '15.78 KB',
          ram_total_str: '1.40 KB',
          rom_percent: 34.21,
          ram_percent: 7.4,
          symbols_count: 32,
          symbols: [
            { name: '__udivmoddi4', kind: 'func', address: '0x02029B10', raw_address: 0x02029B10, size: 800, size_str: '800 B', category: 'Code' }
          ]
        },
        {
          name: 'los_memory.c',
          full_path: 'kernel/base/mem/los_memory.c',
          code: 3845,
          ro_data: 0,
          rw_data: 0,
          zi_data: 17152,
          rom_total: 3845,
          ram_total: 17152,
          code_str: '3.75 KB',
          ro_data_str: '0 B',
          rw_data_str: '0 B',
          zi_data_str: '16.75 KB',
          rom_total_str: '3.75 KB',
          ram_total_str: '16.75 KB',
          rom_percent: 8.14,
          ram_percent: 88.5,
          symbols_count: 14,
          symbols: [
            { name: 'g_memStart', kind: 'object', address: '0x20001000', raw_address: 0x20001000, size: 17152, size_str: '16.75 KB', category: 'ZI-Data' },
            { name: 'OsMemAlloc', kind: 'func', address: '0x0202A120', raw_address: 0x0202A120, size: 1320, size_str: '1.29 KB', category: 'Code' }
          ]
        },
        {
          name: 'los_sched.c',
          full_path: 'kernel/base/core/los_sched.c',
          code: 3265,
          ro_data: 0,
          rw_data: 8,
          zi_data: 290,
          rom_total: 3273,
          ram_total: 298,
          code_str: '3.19 KB',
          ro_data_str: '0 B',
          rw_data_str: '8 B',
          zi_data_str: '290 B',
          rom_total_str: '3.20 KB',
          ram_total_str: '298 B',
          rom_percent: 6.93,
          ram_percent: 1.54,
          symbols_count: 18,
          symbols: [
            { name: 'OsSchedTaskSwitch', kind: 'func', address: '0x0202B200', raw_address: 0x0202B200, size: 696, size_str: '696 B', category: 'Code' }
          ]
        }
      ],
      total_modules_count: 37,
      total_symbols_count: 387,
      top_metrics: {
        max_function: { name: 'printf_float', size: 7987, size_str: '7.80 KB', object: 'printf.o' },
        max_object: { name: 'lookup_table', size: 12697, size_str: '12.40 KB', object: 'table.o' },
        total_padding: { size: 1843, size_str: '1.80 KB' },
        heap_stack_gap: { size: 1024, size_str: '1.00 KB', low_margin: true }
      },
      linear_memory: {
        flash_base: '0x08000000',
        flash_end: '0x08040000',
        flash_blocks: [
          { name: 'Vector Table', start: '0x08000000', size: 4096, size_str: '4.00 KB', type: 'code' },
          { name: '.text (代码)', start: '0x08001000', size: 145510, size_str: '142.10 KB', type: 'code' },
          { name: '.rodata (常量)', start: '0x08024866', size: 37580, size_str: '36.70 KB', type: 'ro_data' },
          { name: '.data_init', start: '0x0802DB12', size: 6963, size_str: '6.80 KB', type: 'rw_data' },
          { name: 'Padding (对齐损耗)', start: '0x0802F645', size: 1843, size_str: '1.80 KB', type: 'pad' }
        ],
        ram_base: '0x20000000',
        ram_end: '0x20010000',
        ram_blocks: [
          { name: '.data (RW)', type: 'rw', size: 3174, size_str: '3.10 KB', growth: 'none' },
          { name: '.bss (ZI)', type: 'zi', size: 30105, size_str: '29.40 KB', growth: 'none' },
          { name: 'Heap (堆空间) (↑)', type: 'heap', size: 12902, size_str: '12.60 KB', growth: 'up' },
          { name: 'Free Gap (⚠️ 低余量 1.0 KB)', type: 'free', size: 1024, size_str: '1.00 KB', warning: true, growth: 'none' },
          { name: 'Stack (栈空间) (↓)', type: 'stack', size: 7680, size_str: '7.50 KB', growth: 'down' }
        ]
      },
      treemap: {
        flash: {
          name: 'FLASH',
          size: 191896,
          categories: [
            {
              name: '.text (Code)',
              type: 'code',
              color: '#3b82f6',
              size: 145510,
              size_str: '142.10 KB',
              percent: 75.9,
              items: [
                { name: 'protocol.o', size: 23244, size_str: '22.70 KB', type: 'code' },
                { name: 'can_driver.o', size: 18739, size_str: '18.30 KB', type: 'code' },
                { name: 'log.o', size: 11878, size_str: '11.60 KB', type: 'code' },
                { name: 'protocol_decode', size: 8908, size_str: '8.70 KB', type: 'code' },
                { name: 'state_machine', size: 6246, size_str: '6.10 KB', type: 'code' },
                { name: 'packet_tx', size: 4403, size_str: '4.30 KB', type: 'code' }
              ]
            },
            {
              name: '.rodata (RO)',
              type: 'ro',
              color: '#a855f7',
              size: 37580,
              size_str: '36.70 KB',
              percent: 19.6,
              items: [
                { name: 'lookup_table', size: 12697, size_str: '12.40 KB', type: 'ro' },
                { name: 'printf_float', size: 7987, size_str: '7.80 KB', type: 'ro' },
                { name: 'boot_info', size: 4710, size_str: '4.60 KB', type: 'ro' },
                { name: 'const_str', size: 4300, size_str: '4.20 KB', type: 'ro' }
              ]
            },
            {
              name: '.data_init (RW)',
              type: 'rw',
              color: '#f97316',
              size: 6963,
              size_str: '6.80 KB',
              percent: 3.6,
              items: [
                { name: 'init_cfg', size: 2662, size_str: '2.60 KB', type: 'rw' },
                { name: 'calib_data', size: 2150, size_str: '2.10 KB', type: 'rw' }
              ]
            },
            {
              name: 'Padding (对齐)',
              type: 'padding',
              color: '#64748b',
              size: 1843,
              size_str: '1.80 KB',
              percent: 0.9,
              items: [{ name: '对齐损耗', size: 1843, size_str: '1.80 KB', type: 'padding' }]
            }
          ]
        },
        ram: {
          name: 'RAM',
          size: 43827,
          categories: [
            {
              name: '.data (RW)',
              type: 'rw',
              color: '#f97316',
              size: 3174,
              size_str: '3.10 KB',
              percent: 7.2,
              items: [{ name: 'g_data_cfg', size: 3174, size_str: '3.10 KB', type: 'rw' }]
            },
            {
              name: '.bss (ZI)',
              type: 'zi',
              color: '#22c55e',
              size: 30105,
              size_str: '29.40 KB',
              percent: 68.7,
              items: [{ name: 'g_memPool', size: 30105, size_str: '29.40 KB', type: 'zi' }]
            },
            {
              name: 'Heap (堆空间)',
              type: 'heap',
              color: '#06b6d4',
              size: 12902,
              size_str: '12.60 KB',
              percent: 29.4,
              items: [{ name: '动态堆池', size: 12902, size_str: '12.60 KB', type: 'heap' }]
            }
          ]
        }
      },
      hierarchy: [
        {
          id: 'flash',
          label: 'FLASH',
          size: 191896,
          size_str: '187.40 KB',
          type: 'region',
          children: [
            { id: 'f1', label: '.text (代码段)', size: 145510, size_str: '142.10 KB', type: 'code' },
            { id: 'f2', label: '.rodata (只读数据)', size: 37580, size_str: '36.70 KB', type: 'ro' },
            { id: 'f3', label: '.data_init (数据初值)', size: 6963, size_str: '6.80 KB', type: 'rw' },
            { id: 'f4', label: 'Padding (对齐填充)', size: 1843, size_str: '1.80 KB', type: 'padding' }
          ]
        },
        {
          id: 'ram',
          label: 'RAM',
          size: 43827,
          size_str: '42.80 KB',
          type: 'region',
          children: [
            { id: 'r1', label: '.data (全局变量)', size: 3174, size_str: '3.10 KB', type: 'rw' },
            { id: 'r2', label: '.bss (未初始化段)', size: 30105, size_str: '29.40 KB', type: 'zi' },
            { id: 'r3', label: 'Heap (动态堆 ↑)', size: 12902, size_str: '12.60 KB', type: 'heap' },
            { id: 'r4', label: 'Stack (调用栈 ↓)', size: 7680, size_str: '7.50 KB', type: 'stack' }
          ]
        },
        {
          id: 'libs',
          label: 'Libraries (库文件)',
          size: 45000,
          size_str: '43.95 KB',
          type: 'libs',
          children: [
            { id: 'l1', label: 'protocol.a', size: 28000, size_str: '27.34 KB', type: 'lib' },
            { id: 'l2', label: 'drivers.a', size: 17000, size_str: '16.60 KB', type: 'lib' }
          ]
        }
      ]
    } as any;
  }

  if (cmd === 'pick_firmware_file') {
    return 'C:/ING918XX_SDK_SOURCE/examples-gcc/peripheral_console_liteos/peripheral_console_liteos.axf' as any;
  }

  if (cmd === 'pick_pack_file') {
    return 'C:/packs/INGChips.INGCHIPS_DeviceFamilyPack.1.0.1.pack' as any;
  }

  if (cmd === 'svd_import_pack') {
    return {
      status: 'success',
      pack: 'INGChips.INGCHIPS_DeviceFamilyPack.1.0.1.pack',
      pack_path: args?.pack_path || 'C:/packs/INGChips.INGCHIPS_DeviceFamilyPack.1.0.1.pack',
      devices: [
        { name: 'ING92600', vendor: 'INGChips', pack: 'INGChips.INGCHIPS_DeviceFamilyPack.1.0.1.pack', core: 'Cortex-M4', flash_size: 2097152, flash_start: '0x02000000', ram_size: 65536, ram_start: '0x20000000' }
      ]
    } as any;
  }

  if (cmd === 'svd_get_devices') {
    return [
      { name: 'ING91800', vendor: 'INGChips', pack: 'INGChips.INGCHIPS_DeviceFamilyPack.1.0.1.pack', core: 'Cortex-M3', flash_size: 524288, flash_start: '0x00004000', ram_size: 65536, ram_start: '0x20000000' },
      { name: 'ING91600', vendor: 'INGChips', pack: 'INGChips.INGCHIPS_DeviceFamilyPack.1.0.1.pack', core: 'Cortex-M4', flash_size: 2097152, flash_start: '0x02000000', ram_size: 32768, ram_start: '0x20000000' },
      { name: 'ING2000', vendor: 'INGChips', pack: 'INGChips.INGCHIPS_DeviceFamilyPack.1.0.1.pack', core: 'Cortex-M3', flash_size: 2097152, flash_start: '0x02002000', ram_size: 32768, ram_start: '0x20000000' },
    ] as any;
  }

  if (cmd === 'svd_get_peripherals') {
    return [
      { name: 'UART0', base_address: '0x40020000', raw_base_address: 0x40020000, description: 'Universal Asynchronous Receiver/Transmitter 0', group_name: 'UART' },
      { name: 'UART1', base_address: '0x40021000', raw_base_address: 0x40021000, description: 'Universal Asynchronous Receiver/Transmitter 1', group_name: 'UART' },
      { name: 'GPIO', base_address: '0x40010000', raw_base_address: 0x40010000, description: 'General Purpose Input/Output', group_name: 'GPIO' },
      { name: 'TIMER0', base_address: '0x40030000', raw_base_address: 0x40030000, description: '16-bit Timer/Counter 0', group_name: 'TIMER' },
      { name: 'RTC', base_address: '0x40050000', raw_base_address: 0x40050000, description: 'Real Time Clock', group_name: 'RTC' },
      { name: 'SYSCTRL', base_address: '0x40000000', raw_base_address: 0x40000000, description: 'System Clock and Power Control', group_name: 'SYS' },
    ] as any;
  }

  if (cmd === 'svd_get_registers') {
    return [
      {
        name: 'UARTDR',
        description: 'Data Register',
        offset: '0x0000',
        raw_offset: 0,
        address: '0x40020000',
        raw_address: 0x40020000,
        size: 32,
        access: 'read-write',
        reset_value: '0x00000000',
        fields: [
          { name: 'DATA', description: 'Transmit/Receive Data Bits', bit_offset: 0, bit_width: 8, bit_range: '[7:0]', access: 'read-write' },
          { name: 'FE', description: 'Framing Error', bit_offset: 8, bit_width: 1, bit_range: '[8]', access: 'read-only' },
          { name: 'PE', description: 'Parity Error', bit_offset: 9, bit_width: 1, bit_range: '[9]', access: 'read-only' },
          { name: 'BE', description: 'Break Error', bit_offset: 10, bit_width: 1, bit_range: '[10]', access: 'read-only' },
          { name: 'OE', description: 'Overrun Error', bit_offset: 11, bit_width: 1, bit_range: '[11]', access: 'read-only' }
        ]
      },
      {
        name: 'UARTCR',
        description: 'Control Register',
        offset: '0x0030',
        raw_offset: 0x30,
        address: '0x40020030',
        raw_address: 0x40020030,
        size: 32,
        access: 'read-write',
        reset_value: '0x00000300',
        fields: [
          { name: 'UARTEN', description: 'UART Enable', bit_offset: 0, bit_width: 1, bit_range: '[0]', access: 'read-write' },
          { name: 'TXE', description: 'Transmit Enable', bit_offset: 8, bit_width: 1, bit_range: '[8]', access: 'read-write' },
          { name: 'RXE', description: 'Receive Enable', bit_offset: 9, bit_width: 1, bit_range: '[9]', access: 'read-write' }
        ]
      }
    ] as any;
  }

  if (cmd === 'svd_read_register') {
    return { address: args.address || '0x40020030', value: '0x00000301', value_uint: 769, binary: '00000000000000000000001100000001', status: 'success' } as any;
  }

  if (cmd === 'svd_read_all_registers') {
    return {
      results: {
        '0x40020000': { value: '0x00000041', value_uint: 65, binary: '00000000000000000000000001000001' },
        '0x40020030': { value: '0x00000301', value_uint: 769, binary: '00000000000000000000001100000001' }
      },
      status: 'success'
    } as any;
  }

  if (cmd === 'svd_write_register') {
    return { address: args.address, value: args.value, status: 'success' } as any;
  }

  if (cmd === 'svd_write_field') {
    return { address: args.address, new_value: '0x00000301', status: 'success' } as any;
  }

  return {} as any;
}
