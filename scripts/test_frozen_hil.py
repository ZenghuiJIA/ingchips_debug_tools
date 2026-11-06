"""Exercise the actual frozen HIL CLI, MCP task lifecycle, and artifact contract."""
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

exe = Path(sys.argv[1]).resolve()
root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as temporary:
    folder = Path(temporary)
    fixture = root / 'examples/hil/smoke.hiltest.json'
    completed = subprocess.run([str(exe), '--mode', 'hiltest', '--file', str(fixture), '--report-dir', str(folder / 'cli')],
                               capture_output=True, text=True, encoding='utf-8', timeout=90)
    assert completed.returncode == 0, completed.stderr + completed.stdout
    final = json.loads(completed.stdout.splitlines()[-1])
    assert final['state'] == 'PASS' and final['done'], final
    directory = Path(final['report_dir'])
    for name in ('plan.json', 'report.json', 'status.json', 'events.jsonl', 'serial.log', 'junit.xml', 'report.html'):
        assert (directory / name).is_file(), name
    yaml_fixture = folder / 'smoke.yaml'
    yaml_fixture.write_text('schema_version: 2\nsteps:\n  - action: delay\n    params:\n      delay_ms: 10\n', encoding='utf-8')
    validated = subprocess.run([str(exe), '--validate', '--file', str(yaml_fixture)],
                              capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert validated.returncode == 0, validated.stderr + validated.stdout
    assert json.loads(validated.stdout)['valid'] is True
    replay_plan = folder / 'observe.json'
    replay_plan.write_text(json.dumps({'steps': [{'action': 'hil_observe', 'params': {'port_name': 'COM_STUB'}}]}), encoding='utf-8')
    replay_events = folder / 'events.jsonl'
    wire = b'HILv1 BOOT boot=1\nHILv1 DONE total=1 pass=1 fail=0 fault=0\n'
    replay_events.write_text(json.dumps({'kind': 'serial', 'port': 'COM_STUB', 'time': 100, 'data': wire.hex()}) + '\n', encoding='utf-8')
    replayed = subprocess.run([str(exe), '--file', str(replay_plan), '--replay-events', str(replay_events), '--report-dir', str(folder / 'replay')],
                             capture_output=True, text=True, encoding='utf-8', timeout=60)
    assert replayed.returncode == 0, replayed.stderr + replayed.stdout
    assert json.loads(replayed.stdout)['hardware_verified'] is False
    with (folder / 'mcp-stderr.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
            text=True, encoding='utf-8', env={**os.environ, 'HIL_REPORT_DIR': str(folder / 'mcp')})
        responses = queue.Queue()
        def reader():
            for line in process.stdout:
                try: responses.put(json.loads(line))
                except ValueError: continue
        threading.Thread(target=reader, daemon=True).start()
        sequence = 0
        def rpc(name, args):
            global sequence
            sequence += 1
            request = {'jsonrpc': '2.0', 'id': sequence, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}}
            process.stdin.write(json.dumps(request) + '\n'); process.stdin.flush()
            response = responses.get(timeout=60)
            assert response['id'] == sequence, response
            assert not response.get('error'), response
            return response['result']
        try:
            invalid = rpc('validate_hiltest', {'document': {'steps': [{'action': 'missing'}]}})
            assert invalid['isError'] is True, invalid
            response = rpc('run_hiltest', {'document': {'steps': [{'id': 'wait', 'action': 'delay', 'timeout_ms': 30000, 'params': {'delay_ms': 20000}}]}})
            assert response['isError'] is False, response
            state = json.loads(response['content'][0]['text']); run_id = state['run_id']
            response = rpc('stop_hiltest', {'run_id': run_id})
            assert response['isError'] is False, response
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                response = rpc('get_hiltest_status', {'run_id': run_id})
                state = json.loads(response['content'][0]['text'])
                if state['done']: break
                time.sleep(.2)
            assert state['done'] and state['state'] == 'CANCELLED', state
            report = rpc('get_hiltest_report', {'run_id': run_id})
            assert report['isError'] is False, report
            response = rpc('get_hiltest_events', {'run_id': run_id, 'after': 0})
            assert response['isError'] is False, response
        finally:
            process.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': 9999, 'method': 'shutdown'}) + '\n')
            process.stdin.flush()
            process.wait(timeout=15)
            process.stdin.close(); process.stdout.close()
print('PASS frozen HIL: CLI, reports, validation, nonblocking MCP start/status/stop/events/report')
