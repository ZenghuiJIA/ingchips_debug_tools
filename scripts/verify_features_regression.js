// Keep the documented entry point; test production code instead of copied implementations.
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
for (const test of ['./test_logic_regression.cjs', './test_abc_logic.cjs', './test_serial_appearance.cjs', './test_hil_frontend.cjs', './test_flash_frontend.cjs']) {
  const result = spawnSync(process.execPath, [fileURLToPath(new URL(test, import.meta.url))], { stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) { process.exitCode = result.status ?? 1; break; }
}
