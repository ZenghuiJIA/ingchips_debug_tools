import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path
from .stream import Journal, HilObserver
from .report import atomic_json, report_files


class Cancelled(Exception):
    pass


def flatten(steps):
    for step in steps:
        yield step
        if step['action'] == 'loop_block' and step.get('enabled', True):
            yield from flatten(step['steps'])


def compare(actual, expected, op):
    passed = {'==': actual == expected, '!=': actual != expected, '>': actual > expected,
              '<': actual < expected, '>=': actual >= expected, '<=': actual <= expected,
              'mask': actual & expected == expected}[op]
    if not passed:
        raise AssertionError(f'Actual {actual:#x} does not satisfy {op} {expected:#x}')


class Worker:
    def __init__(self, plan, folder, controllers):
        import psutil
        self.plan, self.folder, self.c = plan, Path(folder), controllers
        self.started = time.time(); self.started_mono = time.monotonic()
        self.seq = 0; self.lock = threading.RLock()
        self.journals, self.cursors, self.serial_files = {}, {}, {}
        self.mark_times = {}
        self.uncertain_ports = set()
        self.used_requests = set()
        self.results, self.leases = [], []
        self.state = {'run_id': self.folder.name, 'state': 'RUNNING', 'phase': 'prepare', 'done': False,
            'worker_pid': os.getpid(), 'worker_created': psutil.Process().create_time(),
            'report_dir': str(self.folder), 'current_step': None, 'loop': 0,
            'deadline': time.time() + 60, 'deadline_mono': time.monotonic() + 60, 'error': None, 'event_seq': 0}
        self.events = (self.folder / 'events.jsonl').open('a', encoding='utf-8', buffering=1)
        self.log = (self.folder / 'serial.log').open('ab', buffering=0)
        self.log_bytes = 0; self.last_evidence = None

    def publish(self, **changes):
        with self.lock:
            if 'deadline' in changes:
                changes['deadline_mono'] = time.monotonic() + max(0, changes['deadline'] - time.time()) if changes['deadline'] else None
            self.state.update(changes); self.state['event_seq'] = self.seq
            atomic_json(self.folder / 'status.json', self.state)

    def emit(self, kind, **payload):
        with self.lock:
            self.seq += 1
            self.events.write(json.dumps({'seq': self.seq, 'time': time.time(), 'elapsed_ms': (time.monotonic() - self.started_mono) * 1000, 'kind': kind, **payload}, ensure_ascii=False) + '\n')

    def check(self, deadline=None):
        if (self.folder / 'cancel').exists():
            raise Cancelled('Cancellation requested')
        if time.monotonic() - self.started_mono > self.plan['timeout_ms'] / 1000:
            raise TimeoutError('Run deadline exceeded')
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError('Step deadline exceeded')
        for journal in self.journals.values():
            if journal.error:
                raise IOError(journal.error)

    def receive(self, port, data):
        with self.lock:
            self.log_bytes += len(data)
            if self.log_bytes > 512 * 1024 * 1024:
                raise IOError('Run serial log limit (512 MiB) exceeded')
            self.serial_files[port].write(data); self.log.write(data)
            for offset in range(0, len(data), 4096):
                self.emit('serial', schema_version=1, session_id=self.folder.name + ':' + port, direction='RX', wall_time_ms=int(time.time()*1000), port=port, data=data[offset:offset + 4096].hex(), encoding='hex')

    def prepare(self):
        from probe_lease import ProbeLease
        serial = self.c['serial']
        for probe in self.plan['_resources']['probes']:
            self.check()
            available = self.c['pyocd'].list_probes()
            if not any(p['unique_id'] == probe for p in available):
                raise ValueError(f'Probe must match a complete connected unique ID: {probe}')
            self.leases.append(ProbeLease(probe, allow_nested=True))
        for index, (port, baud) in enumerate(self.plan['_resources']['ports'].items()):
            self.check()
            self.leases.append(ProbeLease('serial:' + port))
            self.serial_files[port] = (self.folder / f'serial-{index}.bin').open('ab', buffering=0)
            journal = Journal(sink=lambda data, p=port: self.receive(p, data))
            self.journals[port] = journal; serial._journals[port] = journal
            serial.open_port(port, baud)
            self.cursors[port] = journal.mark()
            self.mark_times[port] = time.monotonic()
        self.emit('capture.ready', ports=list(self.journals))

    def mark(self):
        for port, journal in self.journals.items():
            self.cursors[port] = journal.mark()
            self.mark_times[port] = time.monotonic()
        self.emit('observation.mark')

    def probe_args(self, p):
        return {'probe_id': p.get('probe_id'), 'target_override': p.get('target_device'), 'frequency': p.get('frequency'), 'pack_path': p.get('pack_path')}

    def action(self, step, deadline):
        action, p = step['action'], step['params']; pyocd = self.c['pyocd']
        if action == 'delay':
            end = time.monotonic() + p.get('delay_ms', 500) / 1000
            while time.monotonic() < end:
                self.check(deadline); time.sleep(.02)
            return {}
        if action == 'serial_open':
            return {'port': p['port_name'], 'capturing': True}
        if action == 'flash_firmware':
            self.mark()
            self.emit('firmware', path=p['file_path'], sha256=hashlib.sha256(Path(p['file_path']).read_bytes()).hexdigest())
            return pyocd.flash_firmware(p['file_path'], p['target_device'], p['probe_id'],
                p.get('pack_path'), p['frequency'], p.get('after_flash', 'halt'))
        if action == 'reset_target':
            self.mark()
            return pyocd.reset_target(False, p['probe_id'], p['target_device'], frequency=p['frequency'], pack_path=p.get('pack_path'))
        if action == 'serial_send':
            port = p['port_name']; self.cursors[port] = self.journals[port].mark()
            self.mark_times[port] = time.monotonic()
            raw = bytes.fromhex(p.get('send_data', '')) if p.get('send_format') == 'hex' else p.get('send_data', '').encode('utf-8')
            raw += {'none': b'', 'lf': b'\n', 'crlf': b'\r\n'}[p.get('send_ending', 'none')]
            result = self.c['serial'].send_data(raw.hex(), port_name=port, is_hex=True)
            self.emit('serial', schema_version=1, session_id=self.folder.name + ':' + port, direction='TX', wall_time_ms=int(time.time()*1000), port=port, data=raw.hex(), encoding='hex')
            return result
        if action == 'protocol_request':
            from .codec import Codec
            port = p['port_name']
            if port in self.uncertain_ports:
                raise RuntimeError('Previous request timed out; a new run/connection is required')
            fingerprint = (port, json.dumps({'protocol': p['protocol'], 'expected': p['expected']}, sort_keys=True))
            if fingerprint in self.used_requests:
                raise RuntimeError('Response identity already used; select a new sequence to avoid delayed duplicates')
            if len(self.used_requests) >= 1024:
                raise RuntimeError('Request identity limit reached')
            with Codec(p['protocol']) as codec:
                raw = codec.encode(p['values'])
                self.check(deadline)
                self.used_requests.add(fingerprint)
                self.uncertain_ports.add(port)
                cursor = self.journals[port].mark()
                self.c['serial'].send_data(raw.hex(), port_name=port, is_hex=True)
                self.emit('serial', schema_version=1, session_id=self.folder.name + ':' + port, direction='TX', port=port, data=raw.hex(), encoding='hex')
                try:
                    while True:
                        self.check(deadline)
                        chunks, cursor = self.journals[port].read_timed(cursor)
                        for data, stamp in chunks:
                            for frame in codec.feed(data, (stamp-self.started_mono)*1000):
                                self.emit('protocol.frame', port=port, frame=frame)
                                if frame['valid'] and all(frame['fields'].get(key) == value for key, value in p['expected'].items()):
                                    self.uncertain_ports.discard(port)
                                    return frame
                        time.sleep(.01)
                except (TimeoutError, Cancelled):
                    self.uncertain_ports.add(port)
                    raise
        if action in ('serial_wait_match', 'hil_observe'):
            return self.observe(step, deadline)
        if action in ('swd_read_assert', 'swd_read_block'):
            address = p.get('memory_addr')
            if p.get('symbol'):
                from elftools.elf.elffile import ELFFile
                with open(p['axf_path'], 'rb') as source:
                    symtab = ELFFile(source).get_section_by_name('.symtab')
                    matches = symtab.get_symbol_by_name(p['symbol']) if symtab else []
                    if not matches or len(matches) != 1:
                        raise ValueError('Symbol must resolve to exactly one address')
                    address = int(matches[0]['st_value'])
            count = p['count'] if action == 'swd_read_block' else p['read_width'] // 8
            value = pyocd.read_memory(address, count, **self.probe_args(p))
            if len(value['bytes']) != count: raise IOError('Incomplete memory read')
            if action == 'swd_read_block':
                self.emit('memory', **value); return value
            actual = int.from_bytes(bytes(value['bytes']), 'little')
            compare(actual, p['expected_value'], p.get('operator', '=='))
            return {'actual': actual, 'expected': p['expected_value']}
        if action == 'svd_check_reg':
            from svd_manager import SvdManager
            regs = SvdManager.get_registers(p['target_device'], p['peripheral'])
            reg = next((r for r in regs if r['name'] == p['register']), None)
            if not reg or reg.get('access') == 'write-only' or reg.get('read_action'):
                raise ValueError('SVD register missing or unsafe to read')
            addr = reg['address']
            addr = int(addr, 0) if isinstance(addr, str) else addr
            width = reg.get('size', 32)
            if width not in (8, 16, 32) or addr % (width // 8):
                raise ValueError('Unsupported SVD register size/alignment')
            with pyocd._create_session(p['probe_id'], p['target_device'], frequency=p['frequency'], pack=p.get('pack_path')) as session:
                actual = session.board.target.read_memory(addr, transfer_size=width)
            if not isinstance(actual, int):
                raise IOError('Invalid register value')
            if p.get('field_name'):
                field = next((f for f in reg['fields'] if f['name'] == p['field_name']), None)
                if field is None: raise ValueError('SVD field missing')
                actual = (actual >> field['bit_offset']) & ((1 << field['bit_width']) - 1)
            compare(actual, p['expected_reg_val'], p.get('operator', '=='))
            return {'actual': actual}
        raise ValueError(f'Unsupported action {action}')

    def observe(self, step, deadline):
        p = step['params']; port = p['port_name']; journal = self.journals[port]
        cursor = self.cursors[port]; base = cursor
        monitor = HilObserver(p, now=self.mark_times.get(port, time.monotonic())) if step['action'] == 'hil_observe' else None
        buffer = bytearray(); last_data = time.monotonic()
        regex = re.compile(p['pattern'].encode('utf-8')) if p.get('match_type') == 'regex' else None
        while True:
            self.check(deadline)
            data, end = journal.read(cursor)
            if data:
                last_data = time.monotonic()
                if monitor:
                    chunks, end = journal.read_timed(cursor)
                    for chunk, stamp in chunks:
                        monitor.check_time(now=stamp)
                        for event in monitor.feed(chunk, now=stamp): self.emit('hil', **event)
                    self.publish(last_heartbeat=monitor.last_hb, boot_count=monitor.boots)
                    if monitor.done is not None:
                        self.cursors[port] = end
                        if monitor.failures: raise AssertionError('; '.join(monitor.failures))
                        return {'done': monitor.done, 'boot_count': monitor.boots}
                else:
                    buffer.extend(data)
                    match = regex.search(buffer) if regex else None
                    pattern = p['pattern'].encode('utf-8')
                    pos = buffer.find(pattern) if regex is None else -1
                    if match or pos >= 0:
                        finish = match.end() if match else pos + len(pattern)
                        if finish == 0: raise ValueError('Zero-length matches are not permitted')
                        self.cursors[port] = base + finish
                        return {'matched': (match.group(0) if match else pattern).decode('utf-8', errors='replace'),
                            'captures': {k: v.decode('utf-8', errors='replace') if v else None for k, v in match.groupdict().items()} if match else {}}
                    if len(buffer) > 1024 * 1024: raise IOError('Match window exceeded 1 MiB')
                cursor = end
            if monitor: monitor.check_time()
            elif p.get('idle_timeout_ms') and (time.monotonic() - last_data) * 1000 >= p['idle_timeout_ms']:
                raise TimeoutError('Serial idle timeout')
            time.sleep(.02)

    def evidence(self, error, p):
        settings = self.plan['evidence']
        self.publish(phase='evidence', deadline=time.time() + settings['timeout_ms'] / 1000)
        result = {'reason': str(error), 'errors': []}
        with open(self.folder / 'serial.log', 'rb') as log:
            log.seek(max(0, log.seek(0, 2) - 8192))
            (self.folder / 'serial-tail.bin').write_bytes(log.read())
        path = self.folder / f'evidence-{len(self.results)}.json'
        atomic_json(path, result)
        if settings.get('enabled', True) and p.get('probe_id'):
            try:
                with self.c['pyocd']._create_session(p['probe_id'], p.get('target_device'), frequency=p.get('frequency'), pack=p.get('pack_path')) as session:
                    target = session.board.target
                    target.halt()
                    for name in ('pc', 'lr', 'sp', 'xpsr', 'msp', 'psp'):
                        try: result.setdefault('core', {})[name] = target.read_core_register(name)
                        except Exception as exc: result['errors'].append(f'{name}: {exc}')
                    for name, addr in [('CFSR', 0xE000ED28), ('HFSR', 0xE000ED2c), ('MMFAR', 0xE000ED34), ('BFAR', 0xE000ED38)]:
                        try: result.setdefault('fault', {})[name] = target.read32(addr)
                        except Exception as exc: result['errors'].append(f'{name}: {exc}')
                    atomic_json(path, result)
                    if 'memory_addr' in settings:
                        raw = bytes(target.read_memory_block8(settings['memory_addr'], settings['count']))
                        (self.folder / f'crash-{len(self.results)}.bin').write_bytes(raw)
                        result['memory'] = {'address': settings['memory_addr'], 'bytes': raw.hex()}
            except Exception as exc:
                result['errors'].append(str(exc))
        atomic_json(path, result); self.last_evidence = str(path)
        self.emit('evidence', path=path.name, errors=result['errors'])

    def execute(self, steps, iteration):
        for step in steps:
            if not step['enabled']:
                self.results.append({'step_id': step['id'], 'step_name': step['name'], 'status': 'skipped', 'iteration': iteration})
                continue
            self.check()
            if step['action'] == 'loop_block':
                for n in range(step['params']['count']): self.execute(step['steps'], f'{iteration}.{n + 1}')
                continue
            attempts = 1 + (step['retry_count'] if step['on_failure'] == 'retry' else 0)
            for attempt in range(attempts):
                start = time.monotonic()
                budget = min(step['timeout_ms'] / 1000, self.plan['timeout_ms'] / 1000 - (start - self.started_mono))
                self.publish(current_step=step['id'], phase='step', deadline=time.time() + budget)
                self.emit('step.started', step_id=step['id'], iteration=iteration, attempt=attempt + 1)
                row = {'step_id': step['id'], 'step_name': step['name'], 'iteration': iteration, 'attempt': attempt + 1,
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%S'), 'status': 'pass'}
                error = None
                try:
                    row['actual_output'] = json.dumps(self.action(step, start + budget), ensure_ascii=False)
                    self.check(start + budget)
                except Cancelled:
                    row.update(status='cancelled', message='Cancellation requested'); raise
                except (AssertionError, TimeoutError) as exc:
                    error = exc; row.update(status='fail', message=str(exc))
                except Exception as exc:
                    error = exc; row.update(status='error', message=str(exc))
                finally:
                    row['duration_ms'] = int((time.monotonic() - start) * 1000)
                    self.results.append(row); self.emit('step.finished', result=row)
                if error is None: break
                if attempt + 1 < attempts: continue
                p = step['params']
                if not p.get('probe_id'):
                    p = next((s['params'] for s in flatten(self.plan['steps']) if s['params'].get('probe_id')), p)
                self.evidence(error, p)
                if step['on_failure'] != 'continue': raise error

    def run(self):
        outcome, error = 'PASS', None
        try:
            self.publish(); self.check(); self.prepare()
            for loop in range(self.plan['loop_count']):
                self.publish(loop=loop + 1); self.execute(self.plan['steps'], str(loop + 1))
            if any(r['status'] == 'error' for r in self.results): outcome = 'ERROR'
            elif any(r['status'] == 'fail' for r in self.results): outcome = 'FAIL'
        except Cancelled as exc: outcome, error = 'CANCELLED', str(exc)
        except (AssertionError, TimeoutError) as exc: outcome, error = 'FAIL', str(exc)
        except BaseException as exc: outcome, error = 'ERROR', str(exc)
        finally:
            self.publish(phase='cleanup', deadline=time.time() + 10)
            for port in self.journals:
                try:
                    reader = self.c['serial']._rx_threads.get(port)
                    if port in self.c['serial']._ports: self.c['serial'].close_port(port)
                    if reader:
                        reader.join(timeout=2)
                        if reader.is_alive():
                            raise RuntimeError(f'Serial reader did not stop: {port}')
                except Exception as exc: outcome, error = 'ERROR', f'Cleanup failed: {exc}'
            for lease in reversed(self.leases): lease.close()
            with self.lock:
                for file in self.serial_files.values(): file.close()
                self.log.close()
            visited = {(r['step_id'], r.get('iteration')) for r in self.results}
            def remaining(steps, iteration):
                for item in steps:
                    if item['action'] == 'loop_block' and item['enabled']:
                        for n in range(item['params']['count']):
                            yield from remaining(item['steps'], f'{iteration}.{n + 1}')
                    elif (item['id'], iteration) not in visited:
                        yield {'step_id': item['id'], 'step_name': item['name'], 'iteration': iteration,
                               'status': 'skipped', 'message': 'Not executed', 'duration_ms': 0}
            for loop in range(self.plan['loop_count']):
                self.results.extend(remaining(self.plan['steps'], str(loop + 1)))
            report = {**self.state, 'state': outcome, 'error': error, 'pipeline_name': self.plan['name'],
                'start_time': self.started, 'end_time': time.time(), 'duration_ms': int((time.monotonic()-self.started_mono)*1000),
                'results': self.results, 'total_loops': self.plan['loop_count'], 'total_steps': len(self.results),
                'pass_count': sum(r['status'] == 'pass' for r in self.results),
                'fail_count': sum(r['status'] in ('fail', 'error') for r in self.results), 'done': True, 'evidence': self.last_evidence}
            report_files(self.folder, report); self.emit('run.finished', state=outcome)
            self.publish(state=outcome, done=True, error=error, phase='complete', deadline=None)
            self.events.close()
        return outcome


def watch_supervisor(folder, pid):
    """If the owning service disappears, request cancellation then bound orphan lifetime."""
    import psutil
    try:
        parent = psutil.Process(pid)
        identity = parent.create_time()
    except psutil.Error:
        identity = None
    while True:
        try:
            alive = identity is not None and parent.is_running() and parent.create_time() == identity
        except psutil.Error:
            alive = False
        if not alive:
            (folder / 'cancel').touch()
            time.sleep(10)
            state_path = folder / 'status.json'
            try:
                state = json.loads(state_path.read_text(encoding='utf-8'))
                if not state.get('done'):
                    state.update(state='INTERRUPTED', done=True, error='Owning HIL service exited; hardware outcome may be unknown')
                    report_files(folder, state)
                    atomic_json(state_path, state)
            finally:
                os._exit(2)
        time.sleep(.5)
