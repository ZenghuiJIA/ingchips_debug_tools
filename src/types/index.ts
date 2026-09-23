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

export interface DisassemblyLine {
  address: string;
  mnemonic: string;
  op_str: string;
  size: number;
  bytes: string;
  is_target: boolean;
  func_name?: string;
  file?: string;
  line?: number;
}

export interface SourceSnippetLine {
  line: number;
  code: string;
  is_target: boolean;
}

export interface AddressLocation {
  address: string;
  func_name: string;
  func_size: number;
  offset: number;
  offset_str: string;
  file_path: string;
  file_name: string;
  line: number | null;
  column: number | null;
  source_snippet: SourceSnippetLine[];
  disassembly: DisassemblyLine[];
}

export interface StackFrameInfo {
  frame_index: number;
  address: string;
  return_address: string;
  is_exception_return?: boolean;
  is_crash_instruction?: boolean;
  source_info: AddressLocation;
  disassembly: DisassemblyLine[];
}

export interface ExcReturnInfo {
  raw_hex: string;
  is_handler: boolean;
  is_psp: boolean;
  has_fpu_frame: boolean;
  active_sp_name: 'PSP' | 'MSP';
  description: string;
}

export interface ExceptionFrame {
  r0: string;
  r1: string;
  r2: string;
  r3: string;
  r12: string;
  lr: string;
  pc: string;
  xpsr: string;
  pc_val: number;
  lr_val: number;
  stacked_sp: string;
  has_fpu: boolean;
}

export interface HardFaultDeepAnalysis {
  exc_return: ExcReturnInfo;
  active_sp_name: 'PSP' | 'MSP';
  active_sp_val: string;
  exception_frame: ExceptionFrame;
  crash_location: AddressLocation;
  crash_disassembly: DisassemblyLine[];
  handler_pc: string;
  handler_disassembly: DisassemblyLine[];
  psp_call_stack: StackFrameInfo[];
  msp_call_stack: StackFrameInfo[];
  axf_loaded: boolean;
  axf_path: string | null;
  active_stack_desc: string;
  crash_point_desc: string;
  error?: string;
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
  deep_analysis?: HardFaultDeepAnalysis;
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

export interface FirmwareSymbol {
  name: string;
  kind: string;
  address: string;
  raw_address: number;
  size: number;
  size_str: string;
  category: string;
}

export interface FirmwareModule {
  name: string;
  full_path: string;
  code: number;
  ro_data: number;
  rw_data: number;
  zi_data: number;
  rom_total: number;
  ram_total: number;
  code_str: string;
  ro_data_str: string;
  rw_data_str: string;
  zi_data_str: string;
  rom_total_str: string;
  ram_total_str: string;
  rom_percent: number;
  ram_percent: number;
  symbols_count: number;
  symbols: FirmwareSymbol[];
}

export interface FirmwareSection {
  name: string;
  type: string;
  address: string;
  raw_address: number;
  size: number;
  size_str: string;
  flags: string;
  category: string;
  target: string;
}

export interface FirmwareToolchain {
  type: string;
  name: string;
  raw_producer: string;
}

export interface FirmwareSummary {
  code_bytes: number;
  ro_data_bytes: number;
  rw_data_bytes: number;
  zi_data_bytes: number;
  rom_total_bytes: number;
  ram_total_bytes: number;
  code_str: string;
  ro_data_str: string;
  rw_data_str: string;
  zi_data_str: string;
  rom_total_str: string;
  ram_total_str: string;
  rom_code_ratio: number;
  rom_ro_ratio: number;
  rom_rw_ratio: number;
  ram_rw_ratio: number;
  ram_zi_ratio: number;
  chip_flash_size: number | null;
  chip_ram_size: number | null;
  chip_flash_str: string;
  chip_ram_str: string;
  flash_usage_percent: number | null;
  ram_usage_percent: number | null;
  flash_free_bytes: number | null;
  ram_free_bytes: number | null;
  flash_free_str: string;
  ram_free_str: string;
  padding_total?: number;
  padding_total_str?: string;
  parse_status?: {
    warnings: number;
    inferred: number;
    format: string;
  };
}

export interface LinearMemoryBlock {
  name: string;
  start?: string;
  end?: string;
  size: number;
  size_str: string;
  type: string;
  section?: string;
  object?: string;
  percent?: number;
  growth?: 'up' | 'down' | 'none';
  warning?: boolean;
}

export interface LinearMemory {
  flash_base: string;
  flash_end: string;
  flash_blocks: LinearMemoryBlock[];
  ram_base: string;
  ram_end: string;
  ram_blocks: LinearMemoryBlock[];
}

export interface TreemapItem {
  name: string;
  size: number;
  size_str: string;
  type: string;
  object?: string;
  section?: string;
  color?: string;
  percent?: number;
}

export interface TreemapCategory {
  name: string;
  type: string;
  color: string;
  size: number;
  size_str: string;
  percent: number;
  items: TreemapItem[];
}

export interface TreemapData {
  name: string;
  size: number;
  categories: TreemapCategory[];
}

export interface TopMetrics {
  max_function: {
    name: string;
    size: number;
    size_str: string;
    object?: string;
    section?: string;
    address?: string;
  };
  max_object: {
    name: string;
    size: number;
    size_str: string;
    object?: string;
    section?: string;
    address?: string;
  };
  total_padding: {
    size: number;
    size_str: string;
  };
  heap_stack_gap: {
    size: number;
    size_str: string;
    low_margin: boolean;
  };
}

export interface HierarchyNode {
  id: string;
  label: string;
  size: number;
  size_str: string;
  type: string;
  children?: HierarchyNode[];
}

export interface FirmwareResourceAnalysis {
  file_path: string;
  file_name: string;
  file_size: number;
  file_size_str: string;
  toolchain: FirmwareToolchain;
  architecture: string;
  summary: FirmwareSummary;
  sections: FirmwareSection[];
  modules: FirmwareModule[];
  top_metrics?: TopMetrics;
  linear_memory?: LinearMemory;
  treemap?: {
    flash: TreemapData;
    ram: TreemapData;
  };
  hierarchy?: HierarchyNode[];
}

// --- SVD Peripherals & Registers Types ---

export interface SvdDevice {
  name: string;
  vendor: string;
  pack: string;
  pack_path?: string;
  core: string;
  flash_size: number;
  flash_start: string;
  ram_size: number;
  ram_start: string;
}

export interface SvdPeripheral {
  name: string;
  base_address: string;
  raw_base_address: number;
  description: string;
  group_name: string;
}

export interface SvdField {
  name: string;
  description: string;
  bit_offset: number;
  bit_width: number;
  bit_range: string;
  access: string;
  value?: number;
  hex_value?: string;
  bin_value?: string;
}

export interface SvdRegister {
  name: string;
  description: string;
  offset: string;
  raw_offset: number;
  address: string;
  raw_address: number;
  size: number;
  access: string;
  reset_value: string;
  fields: SvdField[];
  current_value?: string;
  current_value_uint?: number;
  current_binary?: string;
  is_expanded?: boolean;
  is_reading?: boolean;
  is_writing?: boolean;
  last_updated?: string;
}

export interface WaveformPointsPayload {
  port: string;
  points: Record<string, number>[];
  timestamp_ms: number;
}

export interface ProtocolChannelDef {
  name: string;
  offset: number;
  type: 'float32' | 'float64' | 'int16' | 'uint16' | 'int32' | 'uint32' | 'int8' | 'uint8' | string;
  scale?: number;
  bias?: number;
}

export interface ProtocolChecksumConfig {
  type: 'none' | 'sum8' | 'xor8' | string;
  offset: number;
}

export interface ProtocolFrameConfig {
  header?: number[];
  tail?: number[];
  fixed_length?: number;
  checksum?: ProtocolChecksumConfig;
}

export interface ProtocolConfig {
  name: string;
  description?: string;
  type: 'binary' | 'firewater' | 'justfloat' | 'raw' | string;
  endian?: 'little' | 'big' | string;
  frame?: ProtocolFrameConfig;
  channels: ProtocolChannelDef[];
}

export interface TerminalSessionTab {
  id: string;
  portName: string;
  baudRate: number;
  isConnected: boolean;
  isDaplink: boolean;
  rxBytesCount: number;
  txBytesCount: number;
}


