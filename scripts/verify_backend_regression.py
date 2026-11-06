"""Hardware-free production backend regression entry point. No board discovery or writes.

Run after building the native binaries. --native selects the exact executable to test,
so the caller cannot accidentally certify a stale development executable as a release.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TESTS = [
    'test_daemon_logic.py', 'test_flash_contract.py', 'test_reset_flash_control.py',
    'test_hil_runner.py', 'test_abc_backend.py', 'test_instrumentation_logic.py',
    'test_instruments_logic.py', 'test_power_and_debug.py',
]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, help='Freshly built hil-native.exe')
    parser.add_argument('--output', type=Path, default=ROOT / 'build_work' / 'backend-regression.json')
    args = parser.parse_args()
    tests = [(name, []) for name in TESTS]
    if args.native:
        native = args.native.resolve(strict=True)
        tests.append(('test_native_runtime.py', [str(native)]))
        tests.append(('test_native_lifecycle.py', [str(native)]))
    rows = []
    for name, extra in tests:
        print(f'\n=== {name} ===', flush=True)
        started = time.monotonic()
        try:
            result = subprocess.run([sys.executable, str(ROOT / 'scripts' / name), *extra], cwd=ROOT, timeout=120)
            code, error = result.returncode, None
        except (OSError, subprocess.TimeoutExpired) as exc:
            code, error = -1, str(exc)
            print(error, file=sys.stderr, flush=True)
        rows.append({'script': name, 'exit_code': code, 'error': error, 'duration_seconds': round(time.monotonic() - started, 3)})
    report = {'hardware_access': False, 'native_executable': str(args.native.resolve()) if args.native else None,
              'passed': sum(row['exit_code'] == 0 for row in rows), 'total': len(rows), 'results': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'Backend suites: {report["passed"]}/{report["total"]}; evidence: {args.output}', flush=True)
    return 0 if report['passed'] == report['total'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
