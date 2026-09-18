export interface PortInfo {
  port_name: string;
  description: string;
  vid: number | null;
  pid: number | null;
  manufacturer: string | null;
  product: string | null;
  serial_number: string | null;
  is_daplink: boolean;
  device_type?: 'daplink' | 'jlink' | 'generic' | string;
}

export interface SystemMetrics {
  tauri_rss_mb: number;
  daemon_rss_mb: number;
  total_rss_mb: number;
  memory_budget_mb: number;
  is_under_budget: boolean;
  os_name: string;
  target_arch: string;
}

export interface ProbeInfo {
  unique_id: string;
  description: string;
  vendor_name: string;
  product_name: string;
  probe_type?: 'daplink' | 'jlink' | 'stlink' | 'generic' | string;
  type_label?: string;
}

export interface SerialRxPayload {
  port: string;
  data: number[];
  timestamp_ms: number;
}

export interface SerialLogItem {
  id: number;
  timestamp: string;
  text: string;
  type: 'rx' | 'tx' | 'info' | 'error';
}

export interface CoreRegisters {
  [key: string]: string;
}

export interface FaultRegisters {
  CFSR: string;
  HFSR: string;
  MMFAR: string;
  BFAR: string;
}

export interface CfsrDecoded {
  raw_cfsr: string;
  mmfsr: string;
  bfsr: string;
  ufsr: string;
  flags: string[];
  explanations: string[];
}

export interface HfsrDecoded {
  raw_hfsr: string;
  flags: string[];
  explanations: string[];
}

export interface HardFaultDiagnosis {
  summary: string;
  recommendations: string[];
  raw_dump: {
    target: string;
    core_registers: CoreRegisters;
    fault_registers: FaultRegisters;
    cfsr_decoded: CfsrDecoded;
    hfsr_decoded: HfsrDecoded;
  };
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'tool';
  content: string;
  tool_call?: {
    name: string;
    arguments: any;
    result?: any;
    status: 'running' | 'success' | 'failed';
  };
  timestamp: string;
}

export type CommandEnding = 'crlf' | 'lf' | 'cr' | 'none';
export type CommandFormat = 'string' | 'hex';

export interface CommandItem {
  id: string;
  label: string;
  payload: string;
  format: CommandFormat;
  lineEnding: CommandEnding;
  delayAfterMs: number;
  enabled: boolean;
}

export interface CommandGroup {
  id: string;
  name: string;
  description?: string;
  commands: CommandItem[];
  loop: boolean;
  loopIntervalMs: number;
}

export interface DataPoint {
  t: number;
  v: number;
}

export interface PlotterChannel {
  id: string;
  name: string;
  color: string;
  visible: boolean;
  points: DataPoint[];
  lastValue: number;
  minValue: number;
  maxValue: number;
  avgValue: number;
}

export interface TriggerRule {
  id: string;
  name: string;
  enabled: boolean;
  matchType: 'contains' | 'regex';
  matchPattern: string;
  responsePayload: string;
  responseFormat: CommandFormat;
  responseEnding: CommandEnding;
  delayMs: number;
  mode: 'continuous' | 'once';
  hits: number;
  lastTriggerTime?: string;
}

export interface JScopeSymbol {
  name: string;
  address: string;
  raw_address: number;
  size: number;
  type: string;
  bind?: string;
  selected?: boolean;
}

