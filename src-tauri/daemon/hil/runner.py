"""Supervised HIL jobs. RPC requests never wait for hardware."""
import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from .config import load_plan
from .report import atomic_json, report_files


class HilRunner:
    def __init__(self, controllers=None, report_root=None):
        self.root = Path(report_root or Path.cwd() / 'reports').resolve()
        self.runs = {}
        self.lock = threading.RLock()

    def start(self, document=None, file=None, parameters=None):
        plan = load_plan(document, file, parameters)
        with self.lock:
            if any(not info['done'] for info in self.runs.values()):
                raise RuntimeError('A HIL run is active in this service')
            if len(self.runs) >= 100:
                self.runs.pop(next(iter(self.runs)))
            run_id = time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:12]
            folder = self.root / run_id
            folder.mkdir(parents=True)
            atomic_json(folder / 'plan.json', plan)
            atomic_json(folder / 'status.json', {'run_id': run_id, 'state': 'QUEUED', 'done': False,
                'report_dir': str(folder), 'deadline': time.time() + 60, 'deadline_mono': time.monotonic() + 60})
            command = [sys.executable]
            if not getattr(sys, 'frozen', False):
                command.append(str(Path(__file__).resolve().parents[1] / 'daemon_entry.py'))
            command.extend(['--hil-worker', str(folder), '--hil-supervisor', str(os.getpid())])
            with (folder / 'worker.log').open('ab') as log:
                child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    env={**os.environ, 'PYINSTALLER_RESET_ENVIRONMENT': '1'},
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            self.runs[run_id] = {'process': child, 'folder': folder, 'done': False, 'cancel_at': None, 'event_offsets': {0: 0}}
            threading.Thread(target=self._watch, args=(run_id,), daemon=True).start()
        return self.get(run_id)

    def _watch(self, run_id):
        info = self.runs[run_id]; child = info['process']; folder = info['folder']; reason = None
        while child.poll() is None:
            try:
                state = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
                if state.get('deadline_mono') and time.monotonic() > state['deadline_mono'] + 2:
                    reason = 'Worker deadline exceeded; hardware outcome may be unknown'
                if info['cancel_at'] and time.monotonic() - info['cancel_at'] > 10:
                    reason = 'Cancellation grace expired; hardware outcome may be unknown'
                if reason:
                    terminate_worker(child)
                    break
            except (OSError, ValueError):
                pass
            time.sleep(.1)
        try:
            state = json.loads((folder / 'status.json').read_text(encoding='utf-8'))
            if not state.get('done') or child.returncode not in (0, 1, 2, 3):
                results = []
                events = folder / 'events.jsonl'
                if events.exists():
                    with events.open(encoding='utf-8') as source:
                        for line in source:
                            try:
                                event = json.loads(line)
                                if event['kind'] == 'step.finished': results.append(event['result'])
                            except ValueError:
                                break
                serial = folder / 'serial.log'
                if serial.exists():
                    with serial.open('rb') as source:
                        source.seek(max(0, source.seek(0, 2) - 8192))
                        (folder / 'serial-tail.bin').write_bytes(source.read())
                state.update(state='INTERRUPTED', done=True, error=reason or f'Worker exited unexpectedly ({child.returncode})', results=results)
                report_files(folder, state)
                atomic_json(folder / 'status.json', state)
        except Exception as exc:
            info['fallback'] = {'run_id': run_id, 'state': 'ERROR', 'done': True,
                'report_dir': str(folder), 'error': f'Unable to finalize report: {exc}', 'results': []}
        finally:
            info['done'] = True

    def _info(self, run_id):
        if not isinstance(run_id, str) or not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{12}', run_id):
            raise ValueError('Invalid run_id')
        with self.lock:
            info = self.runs.get(run_id)
        if info:
            return info
        folder = self.root / run_id
        if not (folder / 'report.json').exists():
            status_file = folder / 'status.json'
            if not status_file.exists():
                raise ValueError('Unknown run_id in this service')
            previous = json.loads(status_file.read_text(encoding='utf-8'))
            import psutil
            try:
                process = psutil.Process(previous.get('worker_pid', -1))
                alive = process.is_running() and process.create_time() == previous.get('worker_created')
            except (psutil.Error, ValueError):
                alive = False
            if alive:
                raise ValueError('This run still belongs to another live service; do not restart it')
            previous.update(state='INTERRUPTED', done=True, error='Previous service/worker exited before finalizing the report')
            report_files(folder, previous)
            atomic_json(status_file, previous)
        return {'folder': folder, 'done': True}

    def get(self, run_id):
        info = self._info(run_id)
        if info.get('fallback'):
            return dict(info['fallback'])
        state = json.loads((info['folder'] / 'status.json').read_text(encoding='utf-8'))
        state['done'] = info['done'] and state.get('done', False)
        if info.get('cancel_at') and not state['done']:
            state['state'] = 'STOPPING'
        return state

    def stop(self, run_id):
        info = self._info(run_id)
        if not info['done']:
            (info['folder'] / 'cancel').touch()
            info['cancel_at'] = info.get('cancel_at') or time.monotonic()
        return self.get(run_id)

    def events(self, run_id, after=0, limit=200):
        info = self._info(run_id)
        if not isinstance(after, int) or after < 0 or not 1 <= limit <= 1000:
            raise ValueError('Invalid event cursor/limit')
        path = info['folder'] / 'events.jsonl'; rows = []
        offsets = info.setdefault('event_offsets', {0: 0})
        if path.exists():
            with path.open('rb') as source:
                source.seek(offsets.get(after, 0))
                for line in source:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        break
                    if row['seq'] > after:
                        rows.append(row)
                        if len(rows) >= limit: break
                if rows:
                    if len(offsets) >= 128:
                        offsets.clear(); offsets[0] = 0
                    offsets[rows[-1]['seq']] = source.tell()
        return {'events': rows, 'cursor': rows[-1]['seq'] if rows else after}

    def report(self, run_id):
        info = self._info(run_id)
        if info.get('fallback'):
            return dict(info['fallback'])
        if not info['done']:
            raise ValueError('Run has not finished')
        return json.loads((info['folder'] / 'report.json').read_text(encoding='utf-8'))


def terminate_worker(child):
    """Kill only descendants of this owned Popen, including frozen bootloader children."""
    import psutil
    try:
        descendants = psutil.Process(child.pid).children(recursive=True)
    except psutil.NoSuchProcess:
        descendants = []
    for process in reversed(descendants):
        try: process.kill()
        except psutil.NoSuchProcess: pass
    if child.poll() is None:
        child.kill()
    child.wait(timeout=10)
    _, alive = psutil.wait_procs(descendants, timeout=10)
    if alive:
        raise RuntimeError('Worker descendants still running; resources are not released')
