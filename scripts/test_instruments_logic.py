"""Test-only instrument adapters never enter the production registry."""
import sys,tempfile,time,unittest,json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src-tauri/daemon'))
from instruments.contracts import SupplyController,MeasurementController,open_production,Unsupported
class Supply:
    def __init__(self):self.writes=[];self.actual={'output':'ON','voltage_v':3.3,'current_limit_a':.1};self.fail=False
    def describe(self):return {'channels':[1],'output_readback':True,'restore_supported':True,'voltage_min':0,'voltage_max':12,'voltage_resolution':.1,'current_min':0,'current_max':1,'current_resolution':.01}
    def open(self,binding,end):return {'device_id':binding['device_id']}
    def query_state(self,end):
        if self.fail:raise TimeoutError('readback timeout')
        return dict(self.actual)
    def apply_setpoint(self,op,settings,end):self.writes.append(('set',op));self.actual.update(settings)
    def set_output(self,op,enabled,end):self.writes.append(('output',enabled));self.actual['output']='ON' if enabled else 'OFF'
    def close(self,end):pass
class InstrumentTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'journal.json';self.adapter=Supply();self.binding={'device_id':'fixture','board_id':'b','channel':1};self.board={'voltage_min':3,'voltage_max':3.6,'current_min':.01,'current_max':.2};self.policy={'on_success':'leave_as_is','on_failure':'leave_as_is','on_cancel':'output_off'}
    def tearDown(self):self.temp.cleanup()
    def controller(self):return SupplyController(self.adapter,self.binding,self.board,self.path)
    def test_no_driver_and_bad_channel_do_not_write(self):
        with self.assertRaises(Unsupported):open_production(self.binding)
        self.binding['channel']=2
        with self.assertRaises(Unsupported):self.controller().apply('op',{'voltage_v':3.3,'current_limit_a':.1},self.policy,time.monotonic()+2)
        self.assertFalse(self.adapter.writes)
    def test_board_limits_and_resolution_are_not_rounded(self):
        for voltage in (4,3.31):
            with self.assertRaises(ValueError):self.controller().apply('op',{'voltage_v':voltage,'current_limit_a':.1},self.policy,time.monotonic()+2)
        self.assertFalse(self.adapter.writes)
    def test_cancel_before_write_runs_explicit_exit_policy(self):
        result=self.controller().apply('op',{'voltage_v':3.5,'current_limit_a':.1},self.policy,time.monotonic()+2,cancelled=lambda:True)
        self.assertEqual(result['operation_state'],'CANCELLED');self.assertEqual(result['output_state'],'OFF');self.assertEqual(self.adapter.writes,[('output',False)])
    def test_uncertain_readback_persists_and_blocks_next_operation(self):
        original=self.adapter.apply_setpoint
        def write(op,settings,end):original(op,settings,end);self.adapter.fail=True
        self.adapter.apply_setpoint=write
        result=self.controller().apply('op',{'voltage_v':3.5,'current_limit_a':.1},self.policy,time.monotonic()+2)
        self.assertEqual(result['operation_state'],'UNKNOWN');self.assertEqual(json.loads(self.path.read_text())['state'],'UNKNOWN')
        with self.assertRaisesRegex(RuntimeError,'Recovery'):self.controller().apply('next',{'voltage_v':3.3,'current_limit_a':.1},self.policy,time.monotonic()+2)
    def test_exit_policy_failure_cannot_report_completed(self):
        self.policy['on_success']='output_off'
        self.adapter.set_output=lambda *args:None
        result=self.controller().apply('op',{'voltage_v':3.5,'current_limit_a':.1},self.policy,time.monotonic()+2)
        self.assertEqual(result['operation_state'],'UNKNOWN');self.assertTrue(result['cleanup_error'])
if __name__=='__main__':unittest.main()
