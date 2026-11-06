"""No-hardware native runtime contract regression; process-tree checks are real."""
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
ROOT=Path(__file__).resolve().parents[1]
EXE=Path(sys.argv[1]).resolve() if len(sys.argv)>1 and not sys.argv[1].startswith('-') else ROOT/'src-tauri/target/debug/hil-native.exe'
if len(sys.argv)>1 and not sys.argv[1].startswith('-'): del sys.argv[1]

class Client:
    def __init__(self, root):
        self.process=subprocess.Popen([str(EXE)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',env={**os.environ,'HIL_REPORT_DIR':str(root)})
        self.queue=queue.Queue();self.seq=0
        def read():
            for line in self.process.stdout:
                self.queue.put(json.loads(line))
        threading.Thread(target=read,daemon=True).start()
    def call(self,method,args=None):
        self.seq+=1;self.process.stdin.write(json.dumps({'jsonrpc':'2.0','id':self.seq,'method':method,'params':args or {}})+'\n');self.process.stdin.flush()
        response=self.queue.get(timeout=20)
        if 'error' in response:raise RuntimeError(response['error']['message'])
        return response['result']
    def close(self):
        self.call('shutdown');self.process.wait(timeout=10);self.process.stdin.close();self.process.stdout.close()

class NativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.client=Client(self.root)
    def tearDown(self):self.client.close();self.temp.cleanup()
    def plan(self,steps,**options):return {'document':{'schema_version':2,'name':'native test','steps':steps,**options}}
    def wait(self,state):
        deadline=time.monotonic()+15
        while not state['done'] and time.monotonic()<deadline:
            time.sleep(.03);state=self.client.call('get_hiltest_status',{'run_id':state['run_id']})
        self.assertTrue(state['done'],state);return state
    def test_delay_loop_reports_without_python(self):
        state=self.client.call('run_hiltest',self.plan([{'action':'loop_block','params':{'count':2},'steps':[{'action':'delay','params':{'delay_ms':10}}]}],loop_count=2))
        children=psutil.Process(self.client.process.pid).children(recursive=True)
        self.assertFalse(any('python' in p.name().lower() for p in children))
        state=self.wait(state);self.assertEqual(state['state'],'PASS')
        report=self.client.call('get_hiltest_report',{'run_id':state['run_id']});self.assertEqual(report['pass_count'],4)
        for name in ('plan.json','events.jsonl','serial.log','report.json','junit.xml','report.html'):self.assertTrue((Path(state['report_dir'])/name).is_file())
    def test_cancel_and_not_executed_are_not_pass(self):
        state=self.client.call('run_hiltest',self.plan([{'id':'long','action':'delay','timeout_ms':20000,'params':{'delay_ms':15000}},{'id':'later','action':'delay','params':{'delay_ms':1}}]))
        self.client.call('stop_hiltest',{'run_id':state['run_id']});state=self.wait(state);self.assertEqual(state['state'],'CANCELLED')
        report=self.client.call('get_hiltest_report',{'run_id':state['run_id']});self.assertEqual(report['pass_count'],0);self.assertTrue(any(r['step_id']=='later' and r['status']=='skipped' for r in report['results']))
    def test_parameters_aliases_and_legacy(self):
        value=self.client.call('validate_hiltest',self.plan([{'action':'serial.expect','params':{'port_name':'COM_STUB','pattern':'OK','timeout_ms':'${wait}'}}],parameters={'wait':'2s'}))
        self.assertEqual(value['plan']['steps'][0]['timeout_ms'],2000)
        legacy={'document':{'steps':[{'action':'swd_read_assert','params':{'probe_id':'p','target_device':'t','memory_addr':'0x20000000','expected_value':'55'}}]}}
        self.assertEqual(self.client.call('validate_hiltest',legacy)['plan']['steps'][0]['params']['expected_value'],85)
    def test_ing_and_stop_contract_preflight(self):
        (self.root/'app.bin').write_bytes(b'AB')
        ini=self.root/'download.ini'
        ini.write_text('[main]\nfamily=ing916\n[bin-0]\nchecked=1\nfilename=app.bin\naddress=0x02004000\n',encoding='utf-8')
        document=self.plan([{'action':'flash_firmware','params':{'flash_type':'ing_ini','file_path':str(ini),'port_name':'COM_STUB'}}],bench={'port_name':'COM_STUB'},stop={'send_data':'STOP','send_ending':'crlf','ack_pattern':'HILv1 STOPPED','timeout_ms':'5s'})
        plan=self.client.call('validate_hiltest',document)['plan']
        self.assertEqual(plan['_resources']['probes'],[])
        self.assertEqual(plan['stop']['port_name'],'COM_STUB')
        self.assertEqual(plan['stop']['timeout_ms'],5000)
        for invalid in ({'match_type':'regex','ack_pattern':'.*'}, {'send_data':''}, {'match_type':'invalid'}, {'baud_rate':9600}):
            broken=json.loads(json.dumps(document));broken['document']['stop'].update(invalid)
            with self.assertRaises(RuntimeError): self.client.call('validate_hiltest',broken)
    def test_reject_invalid_before_hardware(self):
        for steps in [[{'action':'missing'}],[{'action':'serial_open'}],[{'action':'delay','on_failure':'retry'}],[{'action':'serial_wait_match','params':{'port_name':'COM_STUB','pattern':'(?<=X)Y','match_type':'regex'}}]]:
            with self.assertRaises(RuntimeError):self.client.call('validate_hiltest',self.plan(steps))
    def test_events_cursors_are_independent(self):
        state=self.wait(self.client.call('run_hiltest',self.plan([{'action':'delay','params':{'delay_ms':1}}])))
        first=self.client.call('get_hiltest_events',{'run_id':state['run_id'],'after':0});again=self.client.call('get_hiltest_events',{'run_id':state['run_id'],'after':0});self.assertEqual(first,again)
        self.assertEqual(self.client.call('get_hiltest_events',{'run_id':state['run_id'],'after':first['cursor']})['events'],[])
    def test_image_merge_overlap_and_sparse(self):
        a=self.root/'a.bin';b=self.root/'b.bin';a.write_bytes(b'AB');b.write_bytes(b'CD');out=self.root/'out.hex'
        args={'files':[{'file_path':str(a),'offset':'0x02004000'},{'file_path':str(b),'offset':'0x02004004'}],'output_path':str(out),'output_format':'hex'}
        result=self.client.call('merge_bin_files',args);self.assertEqual(result['data_bytes'],4)
        self.assertEqual(self.client.call('read_memory_image',{'file_path':str(out),'address':'0x02004000','count':6}),[65,66,255,255,67,68])
        args['files'][1]['offset']='0x02004001'
        with self.assertRaisesRegex(RuntimeError,'overlap'):self.client.call('merge_bin_files',args)
    def test_pixels_short_read_rejected(self):
        result=self.client.call('render_framebuffer',{'width':1,'height':1,'pixel_format':'rgb565','data':'00f8'})
        self.assertTrue(result['image_base64'].startswith('data:image/bmp'))
        with self.assertRaises(RuntimeError):self.client.call('render_framebuffer',{'width':2,'height':1,'data':'00f8'})
    def test_mcp_error_and_no_hardware_process(self):
        result=self.client.call('tools/call',{'name':'validate_hiltest','arguments':self.plan([{'action':'missing'}])});self.assertTrue(result['isError'])
        self.assertFalse(psutil.Process(self.client.process.pid).children())

if __name__=='__main__':unittest.main()
