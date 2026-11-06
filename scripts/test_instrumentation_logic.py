import struct,sys,unittest,json,tempfile,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src-tauri/daemon'))
from instrumentation.analysis import analyze_instrumentation,analyze_task_snapshots
from hil.crash import analyze_bundle,MemorySource

def event(typ,seq,tick,payload,boot='7'):
    return {'event_type':typ,'boot_id':boot,'sequence':seq,'ticks':str(tick),'payload_hex':payload.hex()}
def prefix():
    return [event(1,0,0,b'B'*16+struct.pack('<II',1,0)),event(2,1,0,struct.pack('<IIIBBH',1,0,1_000_000,64,4,0))]
class InstrumentationTests(unittest.TestCase):
    def test_valid_ticks_over_js_limit_and_budget(self):
        events=prefix()+[event(4,2,2**53+1,struct.pack('<III',1,1,42)),event(5,3,2**53+11,struct.pack('<III',1,1,42))]
        result=analyze_instrumentation(events,{'42':{'metric':'elapsed','threshold':5,'unit':'us','min_samples':1}})
        self.assertEqual(result['status'],'FAIL');self.assertEqual(result['metrics'][0]['max_ns'],'10000')
    def test_zero_gap_missing_and_clock_change_never_pass(self):
        self.assertEqual(analyze_instrumentation(prefix())['status'],'INCONCLUSIVE')
        begin=event(4,2,10,struct.pack('<III',1,1,42));end=event(5,4,20,struct.pack('<III',1,1,42))
        self.assertEqual(analyze_instrumentation(prefix()+[begin,end])['status'],'INCONCLUSIVE')
        clock=event(2,3,15,struct.pack('<IIIBBH',1,1,2_000_000,64,4,0))
        self.assertEqual(analyze_instrumentation(prefix()+[begin,clock,end])['status'],'INCONCLUSIVE')
    def test_modular_sequence_wrap_and_boot_repetition(self):
        events=prefix();events[1]['sequence']=0xffffffff;events[0]['sequence']=0xfffffffe
        events+=[event(4,0,10,struct.pack('<III',1,1,42)),event(5,1,20,struct.pack('<III',1,1,42))]
        self.assertEqual(analyze_instrumentation(events)['status'],'PASS')
        self.assertEqual(analyze_instrumentation(events+[event(1,0,0,b'B'*16+struct.pack('<II',1,0))])['status'],'INCONCLUSIVE')
    def test_task_generation_and_unknown_cpu(self):
        result=analyze_task_snapshots([{'complete':False,'consistent':True,'tasks':[{'instance_id':'1','generation':2,'name':'T','stack_remaining_bytes':4}]}])
        self.assertEqual(result['status'],'INCONCLUSIVE');self.assertIsNone(result['tasks'][0]['cpu_percent'])
    def test_crash_verified_files_missing_memory_and_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'memory.bin').write_bytes(b'ABCD');(root/'registers.json').write_text('{"exception_frame":{"pc":1}}');regions=[{'address':0x20000000,'length':4,'file':'memory.bin'}];(root/'regions.json').write_text(json.dumps(regions))
            files={p.name:{'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in root.iterdir()}
            (root/'manifest.json').write_text(json.dumps({'schema_version':1,'completeness':'complete','record_id':'1','files':files}))
            result=analyze_bundle(root);self.assertEqual(result['completeness'],'complete');self.assertFalse(result['elf_matched'])
            memory=MemorySource(root,regions);self.assertEqual(memory.read(0x20000001,2),b'BC')
            with self.assertRaises(ValueError):memory.read(0x20000003,2)
            (root/'memory.bin').write_bytes(b'BAD!')
            with self.assertRaisesRegex(ValueError,'mismatch'):analyze_bundle(root)
            manifest={'schema_version':1,'files':{'../escape':{'size':0,'sha256':''}}};(root/'manifest.json').write_text(json.dumps(manifest))
            with self.assertRaisesRegex(ValueError,'escapes'):analyze_bundle(root)
if __name__=='__main__':unittest.main()
