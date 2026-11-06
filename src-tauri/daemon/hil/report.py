import html
import json
import os
import time
import xml.etree.ElementTree as ET
from pathlib import Path


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    for attempt in range(20):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(.01)


def report_files(folder, report):
    atomic_json(folder / 'report.json', report)
    rows = report.get('results', [])
    cases = rows or [{'step_name': 'run', 'status': report['state'].lower(), 'message': report.get('error', '')}]
    suite = ET.Element('testsuite', name=report.get('pipeline_name', 'HIL'), tests=str(len(cases)),
                       failures=str(sum(r['status'] == 'fail' for r in cases)),
                       errors=str(sum(r['status'] in ('error', 'interrupted', 'cancelled') for r in cases)))
    for row in cases:
        case = ET.SubElement(suite, 'testcase', name=row.get('step_name', 'run'),
                             classname=str(row.get('iteration', 'run')), time=str(row.get('duration_ms', 0) / 1000))
        if row['status'] != 'pass':
            tag = 'skipped' if row['status'] == 'skipped' else ('failure' if row['status'] == 'fail' else 'error')
            ET.SubElement(case, tag, message=str(row.get('message', row['status']))).text = str(row.get('actual_output', ''))
    if report['state'] != 'PASS' and all(r['status'] in ('pass', 'skipped') for r in cases):
        case = ET.SubElement(suite, 'testcase', name='run completion')
        ET.SubElement(case, 'error', message=report.get('error') or report['state'])
        suite.set('tests', str(len(cases) + 1))
        suite.set('errors', str(int(suite.get('errors', '0')) + 1))
    ET.ElementTree(suite).write(folder / 'junit.xml', encoding='utf-8', xml_declaration=True)
    escaped = html.escape(json.dumps(report, ensure_ascii=False, indent=2))
    (folder / 'report.html').write_text('<!doctype html><meta charset="utf-8"><title>HIL report</title>'
        '<style>body{font:14px monospace;max-width:1100px;margin:30px auto}pre{white-space:pre-wrap}</style>'
        f'<h1>{html.escape(report["state"])}</h1><pre>{escaped}</pre>', encoding='utf-8')
