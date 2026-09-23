import type { CommandItem, CommandGroup } from '../types';

const STORAGE_KEY = 'ai_hil_command_groups_v1';

export const DEFAULT_COMMAND_GROUPS: CommandGroup[] = [
  {
    id: 'grp_at_default',
    name: '常用 AT 指令组',
    description: '标准蜂窝/蓝牙/WiFi模组初始化与状态排查',
    loop: false,
    loopIntervalMs: 1000,
    commands: [
      {
        id: 'cmd_1',
        label: 'AT 握手',
        payload: 'AT',
        format: 'string',
        lineEnding: 'crlf',
        delayAfterMs: 150,
        enabled: true,
      },
      {
        id: 'cmd_2',
        label: '关闭回显 (ATE0)',
        payload: 'ATE0',
        format: 'string',
        lineEnding: 'crlf',
        delayAfterMs: 100,
        enabled: true,
      },
      {
        id: 'cmd_3',
        label: '查询固件版本',
        payload: 'AT+GMR',
        format: 'string',
        lineEnding: 'crlf',
        delayAfterMs: 200,
        enabled: true,
      },
      {
        id: 'cmd_4',
        label: '查询 SIM 卡状态',
        payload: 'AT+CPIN?',
        format: 'string',
        lineEnding: 'crlf',
        delayAfterMs: 200,
        enabled: true,
      },
      {
        id: 'cmd_5',
        label: '查询信号强度',
        payload: 'AT+CSQ',
        format: 'string',
        lineEnding: 'crlf',
        delayAfterMs: 150,
        enabled: true,
      },
    ],
  },
  {
    id: 'grp_esp32_init',
    name: 'ESP32 / WiFi 模组一键初始化',
    description: '适用于 ESP-AT 固件的开机一键入网与网络状态自检',
    loop: false,
    loopIntervalMs: 1000,
    commands: [
      {
        id: 'cmd_esp_1',
        label: '1. 测试响应',
        payload: 'AT',
        format: 'string',
        lineEnding: 'crlf',
        delayAfterMs: 200,
        enabled: true,
      },
      {
        id: 'cmd_esp_2',
        label: '2. 关闭回显',
        payload: 'ATE0',
        format: 'string',
        lineEnding: 'crlf',
        delayAfterMs: 150,
        enabled: true,
      },
      {
        id: 'cmd_esp_3',
        label: '3. 设置为 Station 模式',
        payload: 'AT+CWMODE=1',
        format: 'string',
        lineEnding: 'crlf',
        delayAfterMs: 300,
        enabled: true,
      },
      {
        id: 'cmd_esp_4',
        label: '4. 查询附近 AP 列表',
        payload: 'AT+CWLAP',
        format: 'string',
        lineEnding: 'crlf',
        delayAfterMs: 1500,
        enabled: true,
      },
      {
        id: 'cmd_esp_5',
        label: '5. 查询当前连接与 IP',
        payload: 'AT+CIFSR',
        format: 'string',
        lineEnding: 'crlf',
        delayAfterMs: 200,
        enabled: true,
      },
    ],
  },
  {
    id: 'grp_mixed_protocol',
    name: '混合协议与HEX控制组',
    description: '演示不带换行、单字符换行以及 Modbus HEX 数据帧',
    loop: false,
    loopIntervalMs: 1000,
    commands: [
      {
        id: 'cmd_m1',
        label: '硬件唤醒字 (RAW无换行)',
        payload: 'WAKEUP_DEVICE',
        format: 'string',
        lineEnding: 'none',
        delayAfterMs: 300,
        enabled: true,
      },
      {
        id: 'cmd_m2',
        label: 'Modbus 读保持寄存器 (HEX)',
        payload: '01 03 00 00 00 02 C4 0B',
        format: 'hex',
        lineEnding: 'none',
        delayAfterMs: 200,
        enabled: true,
      },
      {
        id: 'cmd_m3',
        label: 'Shell 命令 (+LF)',
        payload: 'uname -a',
        format: 'string',
        lineEnding: 'lf',
        delayAfterMs: 150,
        enabled: true,
      },
      {
        id: 'cmd_m4',
        label: '复位重启指令 (+CRLF)',
        payload: 'AT+RESET',
        format: 'string',
        lineEnding: 'crlf',
        delayAfterMs: 500,
        enabled: true,
      },
    ],
  },
];

/**
 * Encodes a CommandItem into a byte array for raw serial transmission.
 */
export function encodeCommand(cmd: CommandItem): { bytes: number[]; textDisplay: string } {
  if (cmd.format === 'hex') {
    const cleanHex = cmd.payload.replace(/\s+/g, '');
    if (!/^[0-9a-fA-F]*$/.test(cleanHex) || cleanHex.length % 2 !== 0) {
      throw new Error(`HEX 数据格式无效: "${cmd.payload}" (必须为偶数个16进制字符)`);
    }
    const bytes: number[] = [];
    for (let i = 0; i < cleanHex.length; i += 2) {
      bytes.push(parseInt(cleanHex.substring(i, i + 2), 16));
    }
    return {
      bytes,
      textDisplay: `[HEX] ${cmd.payload} (${cmd.label || 'HEX'})`,
    };
  }

  let fullText = cmd.payload;
  let endingLabel = '';
  switch (cmd.lineEnding) {
    case 'crlf':
      fullText += '\r\n';
      endingLabel = '\\r\\n';
      break;
    case 'lf':
      fullText += '\n';
      endingLabel = '\\n';
      break;
    case 'cr':
      fullText += '\r';
      endingLabel = '\\r';
      break;
    case 'none':
    default:
      endingLabel = 'RAW';
      break;
  }

  const bytes = Array.from(new TextEncoder().encode(fullText));
  return {
    bytes,
    textDisplay: `${cmd.payload}${endingLabel ? ` [${endingLabel}]` : ''} (${cmd.label || 'Cmd'})`,
  };
}

/**
 * Load command groups from localStorage with fallback to default presets.
 */
export function loadCommandGroups(): CommandGroup[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        return parsed;
      }
    }
  } catch (e) {
    console.warn('[CommandEncoder] Failed to load saved command groups:', e);
  }
  return JSON.parse(JSON.stringify(DEFAULT_COMMAND_GROUPS));
}

/**
 * Save command groups to localStorage.
 */
export function saveCommandGroups(groups: CommandGroup[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(groups));
  } catch (e) {
    console.error('[CommandEncoder] Failed to save command groups:', e);
  }
}
