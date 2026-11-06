import json
import sys
import tempfile
import unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src-tauri/daemon'))
from instruments.power import analyze_power_capture
from instruments.contracts import describe_registry
from debug_service import capabilities
class PowerDebugTests(unittest.TestCase):
 def test_time_weighted_charge_energy_and_gaps(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'power.jsonl';rows=[{'capture_id':'c','channel_id':'i','clock_id':'clk','seq':str(n),'timestamp_ns':str(n*1_000_000_000),'current_a':1 if n<2 else 3,'voltage_v':2,'voltage_synchronous':True,'quality_flags':[],'source_kind':'imported_measurement'} for n in range(3)];path.write_text('\n'.join(map(json.dumps,rows)),encoding='utf-8');result=analyze_power_capture(path,'0','2000000000');channel=result['channels'][0];self.assertEqual(channel['charge_c'],'3');self.assertEqual(channel['energy_j'],'6');self.assertEqual(channel['analysis_status'],'PASS')
 def test_gap_and_missing_voltage_are_inconclusive(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'power.jsonl';rows=[{'capture_id':'c','channel_id':'i','clock_id':'clk','seq':'0','timestamp_ns':'0','current_a':1,'voltage_v':None,'quality_flags':[],'source_kind':'hardware_capture'},{'capture_id':'c','channel_id':'i','clock_id':'clk','seq':'2','timestamp_ns':'5000000000','current_a':1,'voltage_v':None,'quality_flags':[],'source_kind':'hardware_capture'}];path.write_text('\n'.join(map(json.dumps,rows)),encoding='utf-8');channel=analyze_power_capture(path,'0','5000000000')['channels'][0];self.assertEqual(channel['analysis_status'],'INCONCLUSIVE');self.assertIsNone(channel['energy_j'])
 def test_registry_has_no_production_drivers(self):self.assertFalse(describe_registry()['production_drivers_installed']);self.assertFalse(capabilities()['production_instruments']['power_supply'])
if __name__=='__main__':unittest.main()
