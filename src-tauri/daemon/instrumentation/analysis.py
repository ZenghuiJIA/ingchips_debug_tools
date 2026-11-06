"""Offline semantics for HILI dictionary 1. Host timestamps never measure spans."""
import hashlib
import math
import struct
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

VERSION = 'hili-analysis-1'
NAMES = {1: 'BOOT_INFO', 2: 'CLOCK_INFO', 3: 'MARK', 4: 'SPAN_BEGIN', 5: 'SPAN_END',
         6: 'IRQ_ENTER', 7: 'IRQ_EXIT', 8: 'TASK_SNAPSHOT', 9: 'TASK_SWITCH', 10: 'LOSS', 11: 'CRASH_CHUNK'}


def uint(value, bits=64):
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        raise ValueError('uint64 IDs/ticks/counts must be decimal strings')
    number = int(value)
    if not 0 <= number < 1 << bits: raise ValueError('Integer out of range')
    return number


def payload(event):
    raw = bytes.fromhex(event['payload_hex'])
    kind = event['event_type']
    sizes = {1: 24, 2: 16, 3: 8, 4: 12, 5: 12, 6: 8, 7: 8, 9: 16, 10: 4}
    if kind in sizes and len(raw) != sizes[kind]: raise ValueError(f'Invalid payload length for {NAMES[kind]}')
    if kind == 1:
        return {'build_id': raw[:16].hex(), 'dictionary': struct.unpack_from('<I', raw, 16)[0], 'capabilities': struct.unpack_from('<I', raw, 20)[0]}
    if kind == 2:
        clock, epoch, hz, bits, flags, reserved = struct.unpack('<IIIBBH', raw)
        if not hz or not 1 <= bits <= 64 or flags & ~7 or reserved: raise ValueError('Invalid clock payload')
        return {'clock_id': clock, 'clock_epoch': epoch, 'tick_hz': hz, 'counter_bits': bits,
                'stops_in_sleep': bool(flags & 1), 'stops_in_debug': bool(flags & 2), 'reliable_extension': bool(flags & 4)}
    if kind in (4, 5):
        token, context, ident = struct.unpack('<III', raw)
        return {'token': str(token), 'context': str(context), 'id': str(ident)}
    if kind in (6, 7):
        irq, context = struct.unpack('<II', raw); return {'irq': irq, 'context': str(context)}
    if kind == 3:
        ident, value = struct.unpack('<II', raw); return {'id': str(ident), 'value': value}
    if kind == 10: return {'lost': str(struct.unpack('<I', raw)[0])}
    if kind == 8:
        if len(raw) < 36: raise ValueError('Short task snapshot')
        ident, begin, end, total, task_count, flags = struct.unpack_from('<QQQIHH', raw)
        if task_count > 16 or len(raw) != 36 + task_count * 60: raise ValueError('Invalid task snapshot size')
        tasks = []
        for i in range(task_count):
            offset = 36 + i * 60
            instance, generation, priority, state, valid, stack, stack_total, remaining, runtime = struct.unpack_from('<QIHB BIIIQ'.replace(' ', ''), raw, offset)
            tasks.append({'instance_id': str(instance), 'generation': generation, 'priority': priority, 'state': state,
                'name': raw[offset+36:offset+60].split(b'\0')[0].decode('utf-8', errors='replace'),
                'stack_start': stack if valid & 1 else None, 'stack_total_bytes': stack_total if valid & 2 else None,
                'stack_remaining_bytes': remaining if valid & 4 else None, 'run_count': str(runtime) if valid & 8 else None})
        return {'snapshot_id': str(ident), 'begin_ticks': str(begin), 'end_ticks': str(end), 'total_tasks': total,
                'complete': bool(flags & 1), 'consistent': bool(flags & 2), 'runtime_valid': bool(flags & 4), 'tasks': tasks}
    return {'raw_hex': raw.hex()}


def analyze_instrumentation(events, budgets=None, device_id='offline', session_id='import', errors=None, source_kind='imported_recording'):
    if not isinstance(events, list) or len(events) > 200000: raise ValueError('Expected at most 200000 events')
    if source_kind not in ('imported_recording', 'hardware_capture', 'synthetic_test'): raise ValueError('Invalid source_kind')
    budgets = budgets or {}
    if not isinstance(budgets, dict): raise ValueError('budgets must be an object keyed by range ID')
    quality = list(errors or []); epochs = []; current = None; opened = {}; completed = defaultdict(list); snapshots = []
    last_seq = None; last_ticks = None; clock = None; irq_stacks = defaultdict(list); dictionaries = []
    def issue(reason, event=None):
        quality.append({'reason': reason, 'sequence': event.get('sequence') if event else None})
        opened.clear()
    for original in events:
        if not isinstance(original, dict): raise ValueError('Event must be an object')
        event = dict(original); boot = uint(event['boot_id']); tick = uint(event['ticks'])
        seq = event.get('sequence'); typ = event.get('event_type')
        if isinstance(seq, bool) or not isinstance(seq, int) or not 0 <= seq < 2**32: raise ValueError('Invalid sequence')
        if not isinstance(typ, int): raise ValueError('event_type required')
        try: fields = payload(event)
        except (ValueError, KeyError, struct.error) as exc: issue(str(exc), event); continue
        if typ == 1:
            if opened: issue('Unclosed ranges at BOOT', event)
            if any(e['boot_id'] == str(boot) for e in epochs): issue('Firmware boot_id repeated', event)
            current = {'device_id': device_id, 'session_id': session_id, 'host_boot_epoch': len(epochs)+1,
                       'boot_id': str(boot), 'build_id': fields['build_id']}
            epochs.append(current); last_seq = seq; last_ticks = tick; clock = None; irq_stacks.clear()
            dictionaries.append(fields['dictionary'])
            if fields['dictionary'] != 1: issue('Unsupported event dictionary', event)
            continue
        if current is None or str(boot) != current['boot_id']:
            issue('Event lacks matching BOOT identity', event); continue
        if last_seq is not None and seq != (last_seq+1) % 2**32: issue('Sequence gap/duplicate/out-of-order', event)
        last_seq = seq
        if typ == 2:
            if opened: issue('Range crosses clock epoch; complete mapping unavailable', event)
            if clock and fields['clock_id'] == clock['clock_id'] and fields['clock_epoch'] <= clock['clock_epoch']:
                issue('Clock epoch did not advance', event)
            clock = fields; last_ticks = tick; continue
        if last_ticks is not None and tick < last_ticks: issue('Counter reversal/wrap without reliable extension', event)
        last_ticks = tick
        if clock is None or (clock['counter_bits'] < 64 and not clock['reliable_extension']):
            issue('Missing clock or unreliable overflow extension', event); continue
        if typ == 10: issue('Firmware LOSS: ' + fields['lost'], event); continue
        if typ in (4, 5):
            key = (current['host_boot_epoch'], fields['context'], fields['token'])
            if typ == 4:
                if key in opened: issue('Duplicate begin token', event)
                else: opened[key] = (tick, fields['id'], dict(clock))
            else:
                begin = opened.pop(key, None)
                if not begin: issue('End without begin', event); continue
                start, ident, source_clock = begin
                if ident != fields['id'] or tick < start or source_clock != clock: issue('Range identity/clock mismatch', event); continue
                completed[ident].append(Fraction((tick-start)*1000000000, clock['tick_hz']))
        elif typ in (6, 7):
            stack = irq_stacks[fields['context']]
            if typ == 6: stack.append(fields['irq'])
            elif not stack or stack.pop() != fields['irq']: issue('IRQ nesting mismatch', event)
        elif typ == 8:
            snapshots.append({**fields, **current, 'clock': dict(clock)})
            if not fields['complete'] or not fields['consistent']: issue('Incomplete/inconsistent task snapshot', event)
        elif typ not in (3, 11): issue('Unknown or unsupported scheduling event invalidates timing quality', event)
    if opened: issue('Unclosed ranges at end of recording')
    if any(irq_stacks.values()): issue('Unclosed IRQ ranges')
    metrics = []
    for ident in sorted(set(completed) | set(budgets)):
        values = sorted(completed[ident]); budget = budgets.get(ident); minimum = 1; limit = None
        if budget is not None:
            if not isinstance(budget, dict) or set(budget) - {'metric', 'threshold', 'unit', 'min_samples'}: raise ValueError('Invalid timing budget')
            if budget.get('metric') != 'elapsed' or budget.get('unit') not in ('ns', 'us', 'ms'): raise ValueError('Only elapsed ns/us/ms budgets supported')
            limit = Fraction(str(budget['threshold'])) * {'ns': 1, 'us': 1000, 'ms': 1000000}[budget['unit']]
            minimum = budget.get('min_samples', 1)
            if limit < 0 or not isinstance(minimum, int) or minimum < 1: raise ValueError('Invalid timing budget bounds')
        status = 'INCONCLUSIVE' if quality or len(values) < minimum else ('FAIL' if limit is not None and any(v > limit for v in values) else 'PASS')
        metrics.append({'id': ident, 'metric': 'elapsed', 'unit': 'ns', 'sample_count': len(values),
            'min_ns': str(int(values[0])) if values else None, 'max_ns': str(int(values[-1])) if values else None,
            'mean_ns': str(int(sum(values)/len(values))) if values else None,
            'p95_ns': str(int(values[max(0, math.ceil(.95*len(values))-1)])) if values else None,
            'over_budget': sum(v > limit for v in values) if limit is not None else None, 'status': status})
    status = 'INCONCLUSIVE' if not metrics or quality or any(m['status']=='INCONCLUSIVE' for m in metrics) else ('FAIL' if any(m['status']=='FAIL' for m in metrics) else 'PASS')
    return {'schema_version': 1, 'analysis_version': VERSION, 'status': status, 'analysis_status': status,
            'source_kind': source_kind, 'hardware_verified': False, 'completeness': 'partial' if quality else 'complete',
            'epochs': epochs, 'metrics': metrics, 'quality': quality, 'task_snapshots': snapshots,
            'limitations': ['Elapsed counter time includes preemption/waiting; no self CPU time is inferred.',
                            'Sleep/debug counter behavior follows CLOCK_INFO. Values are truncated to integer nanoseconds.']}


def analyze_task_snapshots(snapshots):
    if not snapshots: return {'status': 'INCONCLUSIVE', 'tasks': [], 'reason': 'No task snapshots'}
    tasks = {}; issues = []; previous = None
    for snap in snapshots:
        if not snap.get('complete') or not snap.get('consistent'): issues.append('Snapshot incomplete/inconsistent')
        for task in snap.get('tasks', []):
            ident = (snap.get('boot_id'), task['instance_id'], task.get('generation'))
            remaining = task.get('stack_remaining_bytes'); total = task.get('stack_total_bytes')
            if remaining is not None and (remaining < 0 or total is not None and remaining > total): raise ValueError('Invalid stack bounds')
            tasks[ident] = {**task, 'cpu_percent': None}
        # No percentage without an explicit, consistent total runtime counter.
        if previous and snap.get('runtime_valid') and previous.get('runtime_valid') and snap.get('boot_id') == previous.get('boot_id') and snap.get('clock') == previous.get('clock') and snap.get('complete') and previous.get('complete') and snap.get('consistent') and previous.get('consistent'):
            if 'total_runtime' in snap and 'total_runtime' in previous:
                delta = uint(snap['total_runtime']) - uint(previous['total_runtime'])
                old = {(t['instance_id'], t.get('generation')): t for t in previous['tasks']}
                if delta > 0:
                    for task in snap['tasks']:
                        prior = old.get((task['instance_id'], task.get('generation')))
                        if prior and task.get('run_count') is not None and prior.get('run_count') is not None:
                            used = uint(task['run_count']) - uint(prior['run_count'])
                            if 0 <= used <= delta: tasks[(snap.get('boot_id'),task['instance_id'],task.get('generation'))]['cpu_percent'] = used*100/delta
        previous = snap
    return {'status': 'INCONCLUSIVE' if issues else 'PASS', 'tasks': list(tasks.values()), 'quality': issues}


def analyze_file(file_path, mode='binary', budgets=None, device_id='offline', session_id='import'):
    from hil.codec import Codec
    path = Path(file_path)
    if not path.is_file() or path.stat().st_size > 64*1024*1024: raise ValueError('HILI recording must be <=64 MiB')
    if mode not in ('binary', 'text'): raise ValueError('mode must be binary/text')
    dummy = {'schema_version':1,'name':'transport','fixed_length':1,'fields':[]}
    events=[];errors=[];digest=hashlib.sha256()
    with Codec(dummy) as codec, path.open('rb') as source:
        codec.call('hili_configure', mode=mode, timeout_ms=1000)
        while block := source.read(4096):
            digest.update(block); result=codec.call('hili_feed',data=block.hex(),elapsed_ms=0)
            events.extend(result['events']);errors.extend(result['errors'])
            if len(events)>200000 or len(errors)>10000: raise ValueError('HILI analysis event/error limit exceeded')
        partial=codec.call('hili_finish')['partial']
        if partial: errors.append(partial)
    report=analyze_instrumentation(events,budgets,device_id,session_id,errors)
    report['file_sha256']=digest.hexdigest();report['task_analysis']=analyze_task_snapshots(report['task_snapshots'])
    return report
