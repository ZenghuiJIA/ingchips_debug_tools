"""Hardware-free regression tests exercising production runner and stream code."""
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src-tauri' / 'daemon'))
from hil.config import load_plan
from hil.stream import Journal, HilObserver
from hil.worker import Worker
from hil.runner import HilRunner
from probe_lease import ProbeLease

GOOD = b'HILv1 BOOT boot=7\nHILv1 PLAN total=1\nHILv1 RESULT id=1 status=PASS\nHILv1 DONE total=1 pass=1 fail=0 fault=0\n'


class StreamTests(unittest.TestCase):
    def test_all_split_boundaries_and_coalesced_boot_done(self):
        for n in range(len(GOOD) + 1):
            monitor = HilObserver({}, now=0)
            monitor.feed(GOOD[:n], now=.1)
            monitor.feed(GOOD[n:], now=.2)
            self.assertEqual(monitor.boots, 1)
            self.assertEqual(monitor.done['fail'], '0')

    def test_noise_is_not_heartbeat(self):
        monitor = HilObserver({'idle_timeout_ms': 1000}, now=0)
        monitor.feed(b'HILv1 BOOT boot=1\n', now=0)
        monitor.feed(b'very busy log\n', now=2)
        with self.assertRaisesRegex(TimeoutError, 'HB'): monitor.check_time(now=2)

    def test_crash_cannot_be_overwritten_by_pass(self):
        monitor = HilObserver({}, now=0)
        monitor.feed(GOOD.replace(b'HILv1 PLAN', b'HILv1 CRASH id=1\nHILv1 PLAN'), now=.1)
        self.assertTrue(monitor.failures)

    def test_extra_boot_and_bad_counts_fail(self):
        for data in [GOOD.replace(b'HILv1 PLAN', b'HILv1 BOOT boot=8\nHILv1 PLAN'),
                     GOOD.replace(b'pass=1', b'pass=0'), GOOD.replace(b'fail=0', b'fail=no')]:
            with self.assertRaises(AssertionError): HilObserver({}).feed(data)

    def test_independent_cursors_and_overflow(self):
        journal = Journal(capacity=8)
        journal.append(b'BOOTDONE')
        self.assertEqual(journal.read(4)[0], b'DONE')
        self.assertEqual(journal.read(0)[0], b'BOOTDONE')
        journal.append(b'!')
        with self.assertRaises(IOError): journal.read(0)
        journal.fail('unplugged')
        with self.assertRaisesRegex(IOError, 'unplugged'): journal.read(8)

    def test_journal_keeps_arrival_time_for_late_observer(self):
        journal = Journal()
        journal.append(b'HILv1 BOOT boot=1\n', timestamp=1)
        journal.append(b'HILv1 HB id=1\n', timestamp=20)
        monitor = HilObserver({'idle_timeout_ms': 1000}, now=0)
        chunks, _ = journal.read_timed(0)
        monitor.feed(chunks[0][0], now=chunks[0][1])
        with self.assertRaisesRegex(TimeoutError, 'HB'):
            monitor.check_time(now=chunks[1][1])


class ConfigTests(unittest.TestCase):
    def test_invalid_target_and_backend_rejected_before_start(self):
        for p in ({}, {'probe_id': 'x', 'target_device': 'chip', 'flash_type': 'ing_ini'}):
            with self.assertRaises(ValueError): load_plan({'steps': [{'action': 'flash_firmware', 'params': p}]})

    def test_unknown_fields_and_unsafe_retry(self):
        with self.assertRaises(ValueError): load_plan({'stpes': []})
        with self.assertRaises(ValueError): load_plan({'steps': [{'action': 'delay', 'on_failure': 'retry'}]})

    def test_bench_defaults_and_parameters(self):
        plan = load_plan({'bench': {'port_name': 'COM4'}, 'parameters': {'wait': '2s'},
            'steps': [{'action': 'serial_wait_match', 'params': {'port_name': '', 'pattern': 'DONE', 'timeout_ms': '${wait}'}}]})
        self.assertEqual(plan['steps'][0]['params']['port_name'], 'COM4')
        self.assertEqual(plan['steps'][0]['timeout_ms'], 2000)

    def test_legacy_hex_values_preserve_old_semantics(self):
        doc = {'steps': [{'action': 'swd_read_assert', 'params': {'probe_id': 'p', 'target_device': 't',
            'memory_addr': '0x20000000', 'expected_value': '55'}}]}
        self.assertEqual(load_plan(doc)['steps'][0]['params']['expected_value'], 0x55)
        doc['schema_version'] = 2
        self.assertEqual(load_plan(doc)['steps'][0]['params']['expected_value'], 55)


class WorkerTests(unittest.TestCase):
    def test_cancel_before_prepare_never_opens_hardware(self):
        plan = load_plan({'steps': [{'action': 'serial_open', 'params': {'port_name': 'COM_STUB'}}]})
        serial = Mock(); serial._ports = {}; serial._journals = {}; serial._rx_threads = {}
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'cancel').touch()
            worker = Worker(plan, folder, {'serial': serial, 'pyocd': Mock()})
            self.assertEqual(worker.run(), 'CANCELLED')
            serial.open_port.assert_not_called()

    def test_match_preserves_future_reply_and_stale_text_is_not_reused(self):
        plan = load_plan({'steps': [{'action': 'serial_wait_match', 'params': {'port_name': 'COM_STUB', 'pattern': 'BOOT'}}]})
        with tempfile.TemporaryDirectory() as folder:
            worker = Worker(plan, folder, {})
            journal = Journal(); worker.journals['COM_STUB'] = journal; worker.cursors['COM_STUB'] = 0
            journal.append(b'BOOT\nDONE\n')
            worker.observe(plan['steps'][0], time.monotonic() + 1)
            self.assertEqual(worker.cursors['COM_STUB'], 4)
            step = plan['steps'][0]; step['params']['pattern'] = 'DONE'
            worker.observe(step, time.monotonic() + 1)
            with self.assertRaises(TimeoutError): worker.observe(step, time.monotonic() + .03)
            worker.events.close(); worker.log.close()

    def test_failure_continue_never_becomes_pass_and_loops_execute(self):
        plan = load_plan({'loop_count': 2, 'steps': [{'action': 'swd_read_assert', 'on_failure': 'continue',
            'params': {'probe_id': 'test-probe', 'target_device': 'test-chip', 'memory_addr': 0x20000000, 'expected_value': 1}}],
            'evidence': {'enabled': False}})
        serial = Mock(); serial._ports = {}; serial._journals = {}; serial._rx_threads = {}
        pyocd = Mock(); pyocd.read_memory.return_value = {'bytes': [0, 0, 0, 0]}
        pyocd.list_probes.return_value = [{'unique_id': 'test-probe'}]
        with tempfile.TemporaryDirectory() as folder:
            worker = Worker(plan, folder, {'serial': serial, 'pyocd': pyocd})
            self.assertEqual(worker.run(), 'FAIL')
            self.assertEqual(pyocd.read_memory.call_count, 2)
            report = json.loads((Path(folder) / 'report.json').read_text(encoding='utf-8'))
            self.assertEqual(report['fail_count'], 2)
            self.assertTrue((Path(folder) / 'junit.xml').exists())

    def test_lease_reentrant_but_other_thread_rejected(self):
        import threading
        one = ProbeLease('regression-reentrant', allow_nested=True)
        two = ProbeLease('regression-reentrant'); two.close()
        errors = []
        def other():
            try: ProbeLease('regression-reentrant')
            except RuntimeError: errors.append(True)
        thread = threading.Thread(target=other); thread.start(); thread.join()
        one.close()
        self.assertEqual(errors, [True])
        ProbeLease('regression-reentrant').close()


class ProcessTests(unittest.TestCase):
    def test_worker_reports_and_cancel(self):
        with tempfile.TemporaryDirectory() as folder:
            runner = HilRunner(report_root=folder)
            state = runner.start(document={'steps': [{'action': 'delay', 'params': {'delay_ms': 30}}]})
            deadline = time.monotonic() + 30
            while not state['done'] and time.monotonic() < deadline:
                time.sleep(.1); state = runner.get(state['run_id'])
            self.assertTrue(state['done'], state)
            self.assertEqual(state['state'], 'PASS', state)
            self.assertEqual(runner.report(state['run_id'])['pass_count'], 1)
            self.assertTrue(runner.events(state['run_id'])['events'])
            state = runner.start(document={'steps': [{'action': 'delay', 'timeout_ms': 30000, 'params': {'delay_ms': 20000}}]})
            runner.stop(state['run_id'])
            deadline = time.monotonic() + 30
            while not state['done'] and time.monotonic() < deadline:
                time.sleep(.1); state = runner.get(state['run_id'])
            self.assertEqual(state['state'], 'CANCELLED', state)

    def test_cli_validation_and_reports_without_hardware(self):
        entry = ROOT / 'src-tauri/daemon/daemon_entry.py'
        fixture = ROOT / 'examples/hil/smoke.hiltest.json'
        with tempfile.TemporaryDirectory() as folder:
            process = subprocess.run([sys.executable, str(entry), '--mode', 'hiltest', '--file', str(fixture), '--report-dir', folder],
                                     capture_output=True, text=True, encoding='utf-8', timeout=30)
            self.assertEqual(process.returncode, 0, process.stderr + process.stdout)
            final = json.loads(process.stdout.splitlines()[-1])
            self.assertEqual(final['state'], 'PASS')
            self.assertTrue((Path(final['report_dir']) / 'junit.xml').exists())

    def test_replay_is_labelled_and_rejects_missing_done(self):
        from hil.replay import replay
        plan = load_plan({'steps': [{'action': 'hil_observe', 'params': {'port_name': 'COM_STUB'}}]})
        with tempfile.TemporaryDirectory() as folder:
            events = Path(folder) / 'input.jsonl'
            events.write_text(json.dumps({'kind': 'serial', 'port': 'COM_STUB', 'time': 100, 'data': GOOD.hex()}) + '\n', encoding='utf-8')
            report = replay(plan, events, Path(folder) / 'replay')
            self.assertEqual(report['state'], 'PASS')
            self.assertFalse(report['hardware_verified'])
            events.write_text('', encoding='utf-8')
            report = replay(plan, events, Path(folder) / 'empty')
            self.assertEqual(report['state'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
