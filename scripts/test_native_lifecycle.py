"""No-hardware native lifecycle regression.

Run with: python scripts/test_native_lifecycle.py [path/to/hil-native.exe]
The test kills only the owned RPC service PID; the lifecycle supervisor must
reap its exact worker tree and publish INTERRUPTED before a same-root restart.
"""
from __future__ import annotations
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import psutil

HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
# Override from argv so the copied script can run from repository scripts/.
if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
    EXE = Path(sys.argv[1]).resolve()
    del sys.argv[1]
else:
    EXE = ROOT / "src-tauri/target/debug/hil-native.exe"


class Rpc:
    def __init__(self, root: Path):
        self.proc = subprocess.Popen(
            [str(EXE)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
            env={**os.environ, "HIL_REPORT_DIR": str(root)},
        )
        self.responses: queue.Queue[dict] = queue.Queue()
        self.seq = 0
        def read() -> None:
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                try:
                    self.responses.put(json.loads(line))
                except json.JSONDecodeError:
                    pass
        self.reader = threading.Thread(target=read, daemon=True)
        self.reader.start()

    def call(self, method: str, params: dict | None = None) -> dict:
        self.seq += 1
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.seq,
                                          "method": method, "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        response = self.responses.get(timeout=10)
        if "error" in response:
            raise RuntimeError(response["error"]["message"])
        return response["result"]

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.call("shutdown")
            except (OSError, RuntimeError, queue.Empty):
                pass
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=10)


        if self.proc.stdin is not None:
            self.proc.stdin.close()
        self.reader.join(timeout=2)
        if self.proc.stdout is not None:
            self.proc.stdout.close()


class NativeLifecycleTests(unittest.TestCase):
    def plan(self, delay: int, later: bool = False) -> dict:
        steps = [{"id": "long", "action": "delay", "timeout_ms": 30000,
                  "params": {"delay_ms": delay}}]
        if later:
            steps.append({"id": "must_not_run", "action": "delay", "params": {"delay_ms": 1}})
        return {"document": {"schema_version": 2, "name": "lifecycle", "steps": steps}}

    def wait_report(self, report_dir: Path, timeout: float = 20) -> dict:
        deadline = time.monotonic() + timeout
        report = report_dir / "report.json"
        while time.monotonic() < deadline:
            # Final status is observable before process teardown. Wait for the
            # supervisor's owned-worker cleanup, not an arbitrary fixed sleep.
            if report.is_file() and not (report_dir.parent / "active-run.json").exists():
                try:
                    return json.loads(report.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            time.sleep(.1)
        self.fail(f"report not finalized: {report_dir}")

    def test_service_kill_reaps_worker_and_allows_same_root_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            service = Rpc(root)
            started = service.call("run_hiltest", self.plan(15000, later=True))
            run_dir = Path(started["report_dir"])
            marker = root / "active-run.json"
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and not marker.is_file():
                time.sleep(.05)
            self.assertTrue(marker.is_file(), "worker admission marker was not published")
            worker_pid = json.loads(marker.read_text())["worker_pid"]
            # Simulate a crashed service, not a user stop or a hardware operation.
            psutil.Process(service.proc.pid).kill()
            service.proc.wait(timeout=10)
            service.close()
            report = self.wait_report(run_dir)
            self.assertEqual(report["state"], "INTERRUPTED")
            events = run_dir / "events.jsonl"
            if events.is_file():
                self.assertNotIn('"step_id":"must_not_run"', events.read_text(encoding="utf-8"))
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if not psutil.pid_exists(worker_pid):
                    break
                time.sleep(.1)
            self.assertFalse(psutil.pid_exists(worker_pid), "orphaned worker was not reaped")
            self.assertFalse(marker.exists(), "active marker survived a reaped worker")
            restarted = Rpc(root)
            try:
                done = restarted.call("run_hiltest", self.plan(1))
                report2 = self.wait_report(Path(done["report_dir"]))
                self.assertEqual(report2["state"], "PASS")
            finally:
                restarted.close()


if __name__ == "__main__":
    unittest.main()
