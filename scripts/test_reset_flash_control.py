"""Flash cancellation uses the production hooks with simulated target I/O only."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src-tauri/daemon'))
from flash_control import FlashControl, FlashCancelled, acknowledge_recovery, marker_path, require_recovered
from pyocd.core.target import Target

class ResetFlashTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'HIL_FLASH_STATE_DIR':str(self.root/'markers')});self.env.start()
        self.session=MagicMock();self.target=self.session.board.target;self.flash=MagicMock()
        self.target.memory_map=[MagicMock(flash=self.flash)]
        self.target.get_state.return_value=Target.State.HALTED
        self.flash._call_function=MagicMock();self.flash.wait_for_completion=MagicMock(return_value=0)
    def tearDown(self):self.env.stop();self.temp.cleanup()
    def guard(self):return FlashControl(self.session,'probe-test',self.root/'cancel',self.root/'state.json','run-test')
    def test_cancel_during_algorithm_waits_and_prevents_next_write(self):
        original=self.flash._call_function
        with self.guard() as guard:
            self.flash._call_function(123)
            (self.root/'cancel').touch()
            with self.assertRaises(FlashCancelled):self.flash._call_function(456)
            with self.assertRaises(FlashCancelled):self.flash.wait_for_completion()
            result=guard.stop_confirmed()
            self.assertEqual(result['state'],'CANCELLED');self.assertTrue(result['erase_program_stopped'])
            self.assertTrue(result['target_halted']);self.assertFalse(result['firmware_complete'])
        original.assert_called_once_with(123);self.target.reset.assert_not_called()
        require_recovered('probe-test')
    def test_cancel_before_first_write_never_starts_algorithm(self):
        (self.root/'cancel').touch();original=self.flash._call_function
        with self.guard() as guard:
            with self.assertRaises(FlashCancelled):self.flash._call_function(123)
            guard.stop_confirmed()
        original.assert_not_called()
    def test_algorithm_failure_leaves_persistent_unknown_marker(self):
        self.flash.wait_for_completion.return_value=-1
        with self.assertRaises(RuntimeError):
            with self.guard() as guard:
                self.flash._call_function(123);self.flash.wait_for_completion()
                guard.stop_confirmed()
        with self.assertRaisesRegex(RuntimeError,'FLASH_STATE_UNKNOWN'):require_recovered('probe-test')
    def test_halt_not_confirmed_is_never_cancelled(self):
        self.target.get_state.return_value=Target.State.RUNNING
        with self.assertRaisesRegex(RuntimeError,'halt'):
            with self.guard() as guard:guard.stop_confirmed()
        self.assertEqual(json.loads((self.root/'state.json').read_text())['state'],'UNKNOWN')
    def test_unknown_recovery_requires_explicit_ack_and_no_live_owner(self):
        path=marker_path('probe-x');path.parent.mkdir(parents=True);path.write_text(json.dumps({'state':'UNKNOWN','owner_pid':0}))
        with self.assertRaisesRegex(RuntimeError,'UNKNOWN'):require_recovered('probe-x')
        with self.assertRaises(ValueError):acknowledge_recovery('probe-x','yes')
        self.assertEqual(acknowledge_recovery('probe-x','board_recovery_verified')['state'],'RECOVERY_ACKNOWLEDGED')
    def test_controller_passes_cancellation_and_skips_reset(self):
        import daemon_entry as daemon
        cancel=self.root/'cancel'
        def program(_):
            self.flash._call_function(123);cancel.touch();self.flash.wait_for_completion()
        with patch.object(daemon.PyOCDController,'_create_session',return_value=self.session),patch.object(daemon,'FileProgrammer') as factory:
            factory.return_value.program.side_effect=program
            result=daemon.PyOCDController.flash_firmware('app.hex','chip','probe-test',after_flash='reset',control={'run_id':'run','run_dir':str(self.root)})
        self.assertEqual(result['state'],'CANCELLED');self.target.reset.assert_not_called()
if __name__=='__main__':unittest.main()
