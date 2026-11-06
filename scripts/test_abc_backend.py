import json
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src-tauri/daemon'))
from hil.codec import Codec
from hil.config import load_plan
from hil.worker import Worker
from hil.stream import Journal
from hil.plugins import analyze

SPEC = {'schema_version':1,'name':'golden','header':[170,85],'fixed_length':7,'endian':'little',
        'checksum':{'algorithm':'sum8','offset':6},'fields':[{'name':'seq','offset':2,'type':'uint8'},
        {'name':'value','offset':3,'type':'int16'},{'name':'status','offset':5,'type':'uint8'}]}
VALUES = {'seq':1,'value':-2,'status':0}

class ABCTests(unittest.TestCase):
    def test_native_encoding_matches_independent_golden(self):
        with Codec(SPEC) as codec:
            data=codec.encode(VALUES)
            self.assertEqual(data, bytes([170,85,1,254,255,0,253]))
            self.assertEqual(codec.feed(data[:3],0),[])
            frames=codec.feed(data[3:]+data,1)
            self.assertEqual(len(frames),2); self.assertEqual(frames[0]['fields']['value'],-2)

    def test_instant_response_before_send_returns_is_captured(self):
        doc={'schema_version':2,'steps':[{'action':'protocol_request','params':{'port_name':'COM_STUB','protocol':SPEC,'values':VALUES,'expected':{'seq':1,'status':0}}}]}
        plan=load_plan(doc)
        with tempfile.TemporaryDirectory() as folder:
            serial=Mock(); worker=Worker(plan,folder,{'serial':serial,'pyocd':Mock()})
            journal=Journal(); worker.journals['COM_STUB']=journal
            def send(*_,**__):
                journal.append(bytes([170,85,1,254,255,0,253]))
                return {'sent':7}
            serial.send_data.side_effect=send
            result=worker.action(plan['steps'][0],time.monotonic()+3)
            self.assertTrue(result['valid']); self.assertEqual(result['fields']['value'],-2)
            with self.assertRaisesRegex(RuntimeError,'already used'): worker.action(plan['steps'][0],time.monotonic()+3)
            self.assertEqual(serial.send_data.call_count,1)
            worker.events.close(); worker.log.close()

    def test_wrong_sequence_times_out_and_next_request_is_blocked(self):
        plan=load_plan({'steps':[{'action':'protocol_request','params':{'port_name':'COM_STUB','protocol':SPEC,'values':VALUES,'expected':{'seq':2}}}]})
        with tempfile.TemporaryDirectory() as folder:
            serial=Mock(); worker=Worker(plan,folder,{'serial':serial,'pyocd':Mock()}); journal=Journal(); worker.journals['COM_STUB']=journal
            serial.send_data.side_effect=lambda *_,**__: journal.append(bytes([170,85,1,254,255,0,253]))
            with self.assertRaises(TimeoutError): worker.action(plan['steps'][0],time.monotonic()+.2)
            with self.assertRaisesRegex(RuntimeError,'Previous request'): worker.action(plan['steps'][0],time.monotonic()+1)
            self.assertEqual(serial.send_data.call_count,1); worker.events.close(); worker.log.close()

    def test_replay_result_does_not_depend_on_playback_speed(self):
        events=[{'session_id':'A','direction':'RX','seq':1,'elapsed_ms':1,'data':'aa5501'},
                {'session_id':'A','direction':'RX','seq':2,'elapsed_ms':5,'data':'feff00fd'}]
        with Codec(SPEC) as codec:
            results=[codec.call('replay',protocol=SPEC,events=events) for _speed in (.5,1,10)]
            self.assertEqual(results[0],results[1]);self.assertEqual(results[1],results[2]);self.assertFalse(results[0]['hardware_verified'])

    def test_plugin_success_crash_timeout_and_bad_result(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'plugin.py'
            path.write_text('def decode(payload):\n return {"samples":[{"t":1,"channel":"A","value":2}]}\n',encoding='utf-8')
            result=analyze(path,{},5000);self.assertEqual(result['samples'][0]['value'],2);self.assertFalse(result['hardware_verified'])
            path.write_text('def decode(payload):\n raise RuntimeError("decoder failed")\n',encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError,'decoder failed'): analyze(path,{},5000)
            path.write_text('def decode(payload):\n while True: pass\n',encoding='utf-8')
            with self.assertRaises(TimeoutError): analyze(path,{},1000)
            path.write_text('def decode(payload):\n return {"samples":[{"t":0,"channel":"A","value":float("nan")}]}\n',encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError,'finite'): analyze(path,{},5000)

if __name__=='__main__': unittest.main()
