import { safeInvoke } from './ipc';
import type { HilExecutionReport, HilStepResult } from '../types';

export interface HilStatus {
  run_id: string;
  state: 'QUEUED' | 'RUNNING' | 'STOPPING' | 'PASS' | 'FAIL' | 'ERROR' | 'CANCELLED' | 'INTERRUPTED';
  done: boolean;
  report_dir: string;
  current_step?: string;
  loop?: number;
  error?: string;
  cancel_detail?: string;
  stop_confirmed?: boolean;
  target_state?: 'RUNNING'|'STOPPED'|'HALTED'|'ISP_IDLE'|'UNKNOWN';
  stop_detail?: string;
  flash_state?: { state: string; erase_program_stopped?: boolean; target_halted?: boolean; firmware_complete?: boolean; reason?: string };
}
export interface HilEvent {
  seq: number;
  kind: string;
  time: number;
  step_id?: string;
  result?: HilStepResult;
  data?: string;
  port?: string;
  line?: string;
  state?: string;
}
/** Raw backend report. Missing legacy statistics are not inferred from attempt rows. */
export interface HilReport {
  pipeline_name?: string;
  start_time: number;
  end_time: number;
  duration_ms?: number;
  total_loops?: number;
  state: HilStatus['state'];
  report_dir: string;
  error?: string;
  results?: HilStepResult[];
  planned_steps?: number | null;
  executed_steps?: number | null;
  skipped_steps?: number | null;
  attempt_count?: number | null;
  passed_steps?: number | null;
  failed_steps?: number | null;
  cancelled_steps?: number | null;
  hardware_verified?: boolean | null;
}
export function hilCall<T>(operation: string, args: Record<string, unknown>): Promise<T> {
  return safeInvoke<T>('hil_command', { operation, arguments: args });
}
function count(value: unknown): number | null {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : null;
}
/** Only the command layer's pre-dispatch rejection marker proves that no job started. */
export function isHilSubmissionRejected(error: unknown): boolean {
  return typeof error === 'string' && error.startsWith('HIL_NOT_STARTED: ');
}
export function displayReport(report: HilReport): HilExecutionReport {
  const planned = count(report.planned_steps);
  const executed = count(report.executed_steps);
  const skipped = count(report.skipped_steps);
  const attempts = count(report.attempt_count);
  const passed = count(report.passed_steps);
  const failed = count(report.failed_steps);
  const cancelled = count(report.cancelled_steps);
  const complete = planned !== null && executed !== null && skipped !== null && attempts !== null && passed !== null && failed !== null && cancelled !== null;
  // A failed attempt followed by cancellation counts in both failed and cancelled.
  // Passed is disjoint from either, but failed/cancelled are intentionally not summed.
  const consistent = complete && executed + skipped === planned && attempts >= executed
    && passed <= executed && failed <= executed && cancelled <= executed
    && passed + failed <= executed && passed + cancelled <= executed;
  return {
    pipeline_name: `${report.pipeline_name ?? 'HIL'} [${report.state}]`,
    start_time: report.start_time ? new Date(report.start_time * 1000).toLocaleString() : '未知',
    end_time: report.end_time ? new Date(report.end_time * 1000).toLocaleString() : '未知',
    duration_ms: typeof report.duration_ms === 'number' && Number.isFinite(report.duration_ms) && report.duration_ms >= 0 ? report.duration_ms : null,
    total_loops: count(report.total_loops),
    total_steps: planned, pass_count: passed, fail_count: failed,
    planned_steps: planned, executed_steps: executed, skipped_steps: skipped, attempt_count: attempts,
    passed_steps: passed, failed_steps: failed, cancelled_steps: cancelled,
    hardware_verified: typeof report.hardware_verified === 'boolean' ? report.hardware_verified : null,
    success_rate: consistent && planned > 0 ? Math.round(passed / planned * 1000) / 10 : null,
    statistics_note: !complete ? '旧报告或缺失统计：计划范围与完整流程通过率未知'
      : !consistent ? '后端统计不一致：不计算通过率'
      : '按后端逻辑步骤实例统计；全计划通过率 = 通过步骤 / 计划步骤（含未执行）；失败后取消可同时计入失败与取消',
    results: report.results ?? [],
  };
}
