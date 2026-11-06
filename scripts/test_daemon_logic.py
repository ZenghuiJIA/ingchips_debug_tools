"""Regression tests against production daemon code. All probe access is mocked."""
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src-tauri' / 'daemon'))
import daemon_entry as daemon
from svd_manager import SvdManager
from probe_lease import ProbeLease, LeasedSession


class DaemonLogicTests(unittest.TestCase):
    def test_probe_lease_excludes_other_operations_and_releases_on_error(self):
        lease = ProbeLease('unit-test-probe-20261023')
        try:
            with self.assertRaisesRegex(RuntimeError, 'occupied'):
                ProbeLease('unit-test-probe-20261023')
        finally:
            lease.close()
        session = MagicMock()
        session.open.side_effect = RuntimeError('open failed')
        with self.assertRaisesRegex(RuntimeError, 'open failed'):
            LeasedSession(session, 'unit-test-probe-20261023').open()
        ProbeLease('unit-test-probe-20261023').close()

    def test_frequency_forwarded(self):
        for name in ('read_memory', 'write_memory', 'write_memory_byte'):
            with self.subTest(name=name), patch.object(daemon.PyOCDController, name) as method:
                daemon.dispatch_tool(name, {'address': '0x20000000', 'value': 1, 'count': 4, 'frequency': 1000000})
                self.assertEqual(method.call_args.kwargs['frequency'], 1000000)

    def test_flash_halt_has_no_implicit_reset_or_chip_erase(self):
        session = MagicMock()
        target = session.board.target
        with patch.object(daemon.PyOCDController, '_create_session', return_value=session), patch.object(daemon, 'FileProgrammer') as programmer:
            daemon.PyOCDController.flash_firmware('test.hex', 'chip', 'probe', after_flash='halt')
            programmer.assert_called_once_with(session, progress=ANY, chip_erase='sector', keep_unwritten=True, no_reset=True)
            self.assertTrue(callable(programmer.call_args.kwargs['progress']))
            target.halt.assert_called_once()
            target.reset_and_halt.assert_called_once()
            target.reset.assert_not_called()

    def test_jscope_repeated_start_rejected_before_lock_recursion(self):
        with patch.object(daemon.JScopeController, '_running', True):
            with self.assertRaisesRegex(RuntimeError, 'already active'):
                daemon.JScopeController.start_sampling([{'name': 'x'}])

    def test_background_probe_ownership(self):
        with patch.object(daemon.RTTController, '_running', True), patch.object(daemon.PyOCDController, 'write_memory') as write:
            with self.assertRaisesRegex(RuntimeError, 'occupied'):
                daemon.dispatch_tool('write_memory', {'address': '0x20000000', 'value': 1})
            write.assert_not_called()

    def test_read_never_silently_truncates(self):
        with patch.object(daemon.PyOCDController, '_create_session') as create:
            for count in (0, -1, 4097, 65536):
                with self.assertRaises(ValueError):
                    daemon.PyOCDController.read_memory(0x20000000, count)
            create.assert_not_called()

    def test_halted_target_resumed_on_fault_read_failure(self):
        session = MagicMock()
        target = session.board.target
        target.is_running.return_value = True
        target.read32.side_effect = RuntimeError('bus fault')
        for name in ('read_core_registers', 'diagnose_hardfault'):
            target.reset_mock()
            with patch.object(daemon.PyOCDController, '_create_session', return_value=session):
                with self.assertRaisesRegex(RuntimeError, 'bus fault'):
                    getattr(daemon.PyOCDController, name)()
            target.halt.assert_called_once()
            target.resume.assert_called_once()

    def test_pc_sampling_uses_live_pcsr_not_core_registers(self):
        session = MagicMock()
        target = session.board.target
        target.is_running.return_value = True
        target.read32.return_value = 0x08000010
        with patch.object(daemon.PyOCDController, '_create_session', return_value=session):
            result = daemon.PyOCDController.sample_pc_trace(2)
        self.assertEqual(result['samples_count'], 2)
        target.read_core_register.assert_not_called()
        target.read32.assert_called_with(0xE000101C)

    def test_svd_access_semantics_and_inheritance(self):
        xml = ET.fromstring('''<device><size>8</size><access>read-write</access><peripherals><peripheral>
          <name>UART</name><baseAddress>0x40000000</baseAddress><registers>
          <register><name>DATA</name><addressOffset>0</addressOffset></register>
          <register><name>STATUS</name><addressOffset>4</addressOffset><modifiedWriteValues>oneToClear</modifiedWriteValues></register>
          <register><name>RX</name><addressOffset>8</addressOffset><readAction>clear</readAction></register>
          </registers></peripheral></peripherals></device>''')
        with patch.object(SvdManager, '_get_device_svd_root', return_value=xml):
            registers = SvdManager.get_registers('test-device', 'UART')
        self.assertEqual(registers[0]['size'], 8)
        self.assertEqual(registers[0]['access'], 'read-write')
        with self.assertRaisesRegex(ValueError, 'special write'):
            SvdManager._policy('test-device', 0x40000004, write=True, field=True)
        with self.assertRaisesRegex(ValueError, 'side effects'):
            SvdManager._policy('test-device', 0x40000008)

    @unittest.skipUnless(daemon.INTELHEX_AVAILABLE, 'intelhex unavailable')
    def test_hex_image_decoded_at_selected_address(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'image.hex'
            image = daemon.IntelHex()
            image[0x20000001] = 0x42
            image.write_hex_file(str(path))
            result = daemon.dispatch_tool('read_memory_image', {'file_path': str(path), 'address': '0x20000000', 'count': 4})
            self.assertEqual(result, [255, 0x42, 255, 255])
            with self.assertRaisesRegex(ValueError, 'no data'):
                daemon.dispatch_tool('read_memory_image', {'file_path': str(path), 'address': '0x10000000', 'count': 4})


if __name__ == '__main__':
    unittest.main(verbosity=2)
