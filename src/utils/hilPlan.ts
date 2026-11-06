import type { HilTestPipeline, HilTestStep } from '../types';

function object(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${label} 必须是对象`);
  return value as Record<string, unknown>;
}

/** UI preparation only. The Rust validator remains authoritative; never drop unknown fields,
 * inject action defaults into imports, or reinterpret a legacy document as schema v2. */
export function normalizePipeline(input: unknown): HilTestPipeline {
  const source = object(input, '工程');
  const doc = JSON.parse(JSON.stringify(source)) as Record<string, unknown>;
  if (!Array.isArray(doc.steps)) throw new Error('工程 steps 必须是数组');
  if (typeof doc.bench === 'string') throw new Error('桌面 JSON 编辑器需要内嵌 bench 对象；工位文件请使用 CLI，避免相对路径指向错误目录');
  if (doc.bench !== undefined) object(doc.bench, 'bench');
  const ids = new Set<string>();
  function prepare(raw: unknown, path: string, depth: number): HilTestStep {
    if (depth > 8) throw new Error('循环嵌套不能超过 8 层');
    const step = object(raw, `步骤 ${path}`);
    // Missing IDs only: malformed values are rejected rather than silently replaced.
    if (step.id === undefined) step.id = `step_${path}`;
    if (typeof step.id !== 'string' || !step.id.trim()) throw new Error(`步骤 ${path} 缺少有效 ID`);
    if (ids.has(step.id)) throw new Error(`重复步骤 ID: ${step.id}`);
    ids.add(step.id);
    if (typeof step.action !== 'string' || !step.action) throw new Error(`步骤 ${path} 缺少 action`);
    if (step.name === undefined) step.name = step.id;
    if (step.enabled === undefined) step.enabled = true;
    if (step.params === undefined) step.params = {};
    object(step.params, `步骤 ${path} params`);
    if (step.steps !== undefined) {
      if (!Array.isArray(step.steps)) throw new Error(`步骤 ${path} steps 必须是数组`);
      step.steps = step.steps.map((child, i) => prepare(child, `${path}_${i + 1}`, depth + 1));
    }
    return step as unknown as HilTestStep;
  }
  doc.steps = doc.steps.map((s, i) => prepare(s, String(i + 1), 0));
  doc.bench ??= {};
  doc.name ??= 'HIL_Pipeline';
  doc.version ??= '2';
  doc.loop_count ??= 1;
  doc.stop_on_error ??= true;
  return doc as unknown as HilTestPipeline;
}

export function pipelineSnapshot(input: HilTestPipeline, selectedId?: string): HilTestPipeline {
  const snapshot = normalizePipeline(input);
  if (selectedId !== undefined) {
    const step = snapshot.steps.find(s => s.id === selectedId);
    if (!step) throw new Error('选中步骤已不存在');
    step.enabled = true;
    snapshot.steps = [step];
    snapshot.loop_count = 1;
    snapshot.name += ' · 单步';
  }
  return snapshot;
}

/** Immutable identity token prevents late polls from updating a newer run. */
export class HilRunGeneration {
  private generation = 0;
  next(): number { return ++this.generation; }
  current(token: number): boolean { return token === this.generation; }
}
