export interface DebugCapabilities {
  schema_version: number;
  hardware_verified: boolean;
  production_instruments: { power_supply: unknown[]; power_measurement: unknown[] };
  offline_analysis: string[];
  limitations: string[];
}
export interface DebugJob { job_id: string; state: 'RUNNING'|'COMPLETED'|'ERROR'|'CANCELLED'; done: boolean; report_dir: string; error?: unknown }
export interface DebugReport {
  schema_version: number; analysis_status: 'PASS'|'FAIL'|'INCONCLUSIVE'|'ERROR'|'CANCELLED';
  source_kind: string; hardware_verified: false; completeness?: string; limitations: string[];
  metrics?: { id: string; unit: string; sample_count: number; min_ns: string|null; max_ns: string|null; mean_ns: string|null; p95_ns: string|null; status: string }[];
  quality?: unknown[]; channels?: unknown[]; registers?: unknown; task_analysis?: unknown;
  [key: string]: unknown;
}
