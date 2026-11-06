"""Production flash contract regressions; all device and CLI access is mocked."""
import contextlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src-tauri' / 'daemon'))
import daemon_entry as daemon
from probe_lease import LeasedSession, ProbeLease
from pyocd.core.target import Target


class FlashContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        env = patch.dict(os.environ, {'HIL_FLASH_STATE_DIR': str(self.root / 'markers')})
        env.start()
        self.addCleanup(env.stop)
        self.session = MagicMock()
        self.target = self.session.board.target
        self.target.part_number = 'supported-test-chip'
        self.target.get_state.return_value = Target.State.HALTED
        self.flash = MagicMock()
        self.flash._call_function = MagicMock()
        self.flash.wait_for_completion = MagicMock(return_value=0)
        self.target.memory_map = [MagicMock(flash=self.flash)]
        self.control = {'run_id': 'flash-contract', 'run_dir': str(self.root)}

    def test_ing20_is_rejected_without_cli_or_embedded_fallback(self):
        for name in ('ing20', 'ING2000', ' ing200 ', 'ing-2000', 'ING_200'):
            for after in ('reset', 'halt', 'none'):
                for cli in (None, 'mock-pyocd'):
                    with self.subTest(name=name, after=after, cli=cli), \
                         patch.object(daemon.shutil, 'which', return_value=cli), \
                         patch.object(daemon.subprocess, 'run') as external, \
                         patch.object(daemon.PyOCDController, '_create_session') as create, \
                         patch.object(daemon, 'FileProgrammer') as factory:
                        with self.assertRaisesRegex(RuntimeError, 'ING20 SWD flashing is unsupported'):
                            daemon.PyOCDController.flash_firmware(
                                'app.hex', name, 'probe-contract', pack_path='selected.pack',
                                after_flash=after, control=self.control)
                        create.assert_not_called()
                        external.assert_not_called()
                        factory.assert_not_called()

    def test_autodetected_ing20_is_rejected_before_target_changes(self):
        self.target.part_number = 'ING2000'
        with patch.object(daemon.PyOCDController, '_create_session', return_value=self.session), \
             patch.object(daemon, 'FileProgrammer') as factory:
            with self.assertRaisesRegex(RuntimeError, 'ING20 SWD flashing is unsupported'):
                daemon.PyOCDController.flash_firmware('app.hex', probe_id='probe-contract')
        self.target.halt.assert_not_called()
        self.target.reset.assert_not_called()
        self.target.reset_and_halt.assert_not_called()
        factory.assert_not_called()
        self.session.__exit__.assert_called_once()

    def test_state_modes_preserve_bytes_pack_frequency_and_stdout(self):
        for after in ('reset', 'halt', 'none'):
            with self.subTest(after=after):
                self.target.reset_mock()
                order = []
                self.target.halt.side_effect = lambda: order.append('halt')
                self.target.reset.side_effect = lambda: order.append('reset')
                self.target.reset_and_halt.side_effect = lambda: order.append('reset_and_halt')
                programmer = MagicMock()
                programmer.program.side_effect = lambda _: order.append('program')

                def construct(session, **kwargs):
                    self.assertIs(session, self.session)
                    self.assertEqual(order, ['halt'])
                    self.assertEqual(kwargs['chip_erase'], 'sector')
                    self.assertIs(kwargs['keep_unwritten'], True)
                    self.assertIs(kwargs['no_reset'], True)
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        kwargs['progress'](0.5)
                    self.assertEqual(output.getvalue(), '')
                    return programmer

                with patch.object(daemon.PyOCDController, '_create_session', return_value=self.session) as create, \
                     patch.object(daemon, 'FileProgrammer', side_effect=construct):
                    result = daemon.PyOCDController.flash_firmware(
                        'app.hex', 'chip', 'probe-contract', pack_path='selected.pack',
                        frequency=1000000, after_flash=after)
                create.assert_called_once_with('probe-contract', 'chip', pack='selected.pack', frequency=1000000)
                programmer.program.assert_called_once_with('app.hex')
                self.assertEqual(result['pack_path'], 'selected.pack')
                self.assertEqual(result['after_flash'], after)
                self.assertEqual(order, ['halt', 'program'] + {
                    'reset': ['reset'], 'halt': ['reset_and_halt'], 'none': []}[after])

    def test_invalid_control_is_rejected_before_session_or_target_access(self):
        for control in ({}, [], {'run_id': 'r'}, {'run_id': 'r', 'run_dir': ''},
                        {'run_id': 'r', 'run_dir': str(self.root / 'absent')}):
            with self.subTest(control=control), \
                 patch.object(daemon.PyOCDController, '_create_session') as create:
                with self.assertRaises(ValueError):
                    daemon.PyOCDController.flash_firmware('app.hex', 'chip', 'probe-contract', control=control)
                create.assert_not_called()

    def test_cancel_before_programmer_prevents_constructor_and_reset(self):
        (self.root / 'cancel').touch()
        with patch.object(daemon.PyOCDController, '_create_session', return_value=self.session), \
             patch.object(daemon, 'FileProgrammer') as factory:
            result = daemon.PyOCDController.flash_firmware(
                'app.hex', 'chip', 'probe-contract', control=self.control)
        factory.assert_not_called()
        self.assertEqual(result['state'], 'CANCELLED')
        self.target.reset.assert_not_called()
        self.target.reset_and_halt.assert_not_called()

    def test_cancel_hooks_are_installed_before_programmer_constructor(self):
        original = self.flash._call_function

        def construct(*args, **kwargs):
            self.flash._call_function(123)
            (self.root / 'cancel').touch()
            self.flash.wait_for_completion()
            self.fail('Cancellation must stop constructor at the completed boundary')

        with patch.object(daemon.PyOCDController, '_create_session', return_value=self.session), \
             patch.object(daemon, 'FileProgrammer', side_effect=construct):
            result = daemon.PyOCDController.flash_firmware(
                'app.hex', 'chip', 'probe-contract', control=self.control)
        original.assert_called_once_with(123)
        self.assertEqual(result['state'], 'CANCELLED')
        self.assertTrue(result['erase_program_stopped'])
        self.target.reset.assert_not_called()
        self.target.reset_and_halt.assert_not_called()

    def test_probe_lease_conflict_prevents_open_and_programming(self):
        owner = ProbeLease('probe-contract')
        self.addCleanup(owner.close)
        with patch.object(daemon.PyOCDController, '_create_session',
                          return_value=LeasedSession(self.session, 'probe-contract')), \
             patch.object(daemon, 'FileProgrammer') as factory:
            with self.assertRaisesRegex(RuntimeError, 'occupied'):
                daemon.PyOCDController.flash_firmware('app.hex', 'chip', 'probe-contract')
        self.session.open.assert_not_called()
        self.target.halt.assert_not_called()
        factory.assert_not_called()

    def test_program_failure_never_resets_and_releases_session_lease(self):
        with patch.object(daemon.PyOCDController, '_create_session',
                          return_value=LeasedSession(self.session, 'probe-contract')), \
             patch.object(daemon, 'FileProgrammer') as factory:
            factory.return_value.program.side_effect = RuntimeError('program failed')
            with self.assertRaisesRegex(RuntimeError, 'program failed'):
                daemon.PyOCDController.flash_firmware('app.hex', 'chip', 'probe-contract')
        self.target.reset.assert_not_called()
        self.target.reset_and_halt.assert_not_called()
        self.session.close.assert_called_once()
        ProbeLease('probe-contract').close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
