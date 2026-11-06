"""Replay recorded UART events; produces a clearly labelled non-hardware result."""
import json
from pathlib import Path
from .stream import HilObserver
from .worker import flatten
from .report import report_files


def replay(plan, events_path, output):
    observers = [s for s in flatten(plan['steps']) if s['enabled'] and s['action'] == 'hil_observe']
    if len(observers) != 1:
        raise ValueError('Replay requires exactly one enabled hil_observe step')
    settings = observers[0]['params']
    monitor = None
    start = None
    error = None
    outcome = 'PASS'
    try:
        with open(events_path, encoding='utf-8') as source:
            for line in source:
                event = json.loads(line)
                stamp = event['elapsed_ms'] / 1000 if 'elapsed_ms' in event else event['time']
                if event.get('kind') == 'observation.mark':
                    start = stamp; monitor = HilObserver(settings, now=0)
                if event.get('kind') != 'serial' or event.get('direction', 'RX') != 'RX' or event.get('port') != settings['port_name']:
                    continue
                if start is None:
                    start = stamp; monitor = HilObserver(settings, now=0)
                elapsed = stamp - start
                if elapsed < 0:
                    raise ValueError('Recorded event timestamps are not monotonic')
                monitor.check_time(now=elapsed)
                if elapsed * 1000 > observers[0]['timeout_ms']:
                    raise TimeoutError('Replay completion timeout')
                monitor.feed(bytes.fromhex(event['data']), now=elapsed)
                if monitor.done:
                    break
        if monitor is None or monitor.done is None:
            raise AssertionError('Replay ended without DONE')
        if monitor.failures:
            raise AssertionError('; '.join(monitor.failures))
    except (ValueError, AssertionError, TimeoutError) as exc:
        outcome, error = 'FAIL', str(exc)
    folder = Path(output).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    report = {'state': outcome, 'mode': 'REPLAY_ONLY', 'hardware_verified': False,
              'pipeline_name': plan['name'] + ' [REPLAY — NO HARDWARE]', 'error': error,
              'source_events': str(Path(events_path).resolve()), 'report_dir': str(folder),
              'done': monitor.done if monitor else None, 'results': []}
    report_files(folder, report)
    return report
