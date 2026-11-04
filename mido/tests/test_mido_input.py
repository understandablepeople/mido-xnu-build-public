import ctypes
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class Slot(ctypes.Structure):
    _fields_ = [('x', ctypes.c_uint16), ('y', ctypes.c_uint16),
                ('identity', ctypes.c_uint8), ('down', ctypes.c_uint8)]


class State(ctypes.Structure):
    _fields_ = [('slots', Slot * 10), ('home', ctypes.c_uint8)]


class Event(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint) for name in ('kind', 'slot', 'down', 'x', 'y')]


class Mock(ctypes.Structure):
    _fields_ = [('state', State), ('events', Event * 256), ('count', ctypes.c_uint)]


@unittest.skipIf(os.name == 'nt', 'run native C tests in WSL')
class HardwareInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('host C compiler absent')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.root = Path(__file__).resolve().parents[1]
        library = Path(cls.temporary.name) / 'input.so'
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                        '-shared', '-fPIC', '-I', str(cls.root / 'input'),
                        str(cls.root / 'tests/input_host.c'), '-o', str(library)], check=True)
        cls.native = ctypes.CDLL(str(library))
        cls.native.host_qup.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.c_uint,
                                       ctypes.POINTER(ctypes.c_uint8), ctypes.POINTER(ctypes.c_uint8),
                                       ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
                                       ctypes.POINTER(ctypes.c_uint)]
        cls.native.host_state_reset.argtypes = [ctypes.POINTER(Mock)]
        cls.native.host_frame.argtypes = [ctypes.POINTER(Mock), ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]

    def test_patch_embeds_exact_tested_sources(self):
        patch = (self.root.parent / 'xnu/patches/0107-mido-polled-input-battery.patch').read_text()
        for name in ('MidoInput.cpp', 'mido_ft5435.h', 'mido_input_state.h', 'mido_qup_v2.h'):
            section = patch.split('+++ b/iokit/Kernel/arm/' + name + chr(10), 1)[1]
            section = section.split(chr(10) + '--- ', 1)[0]
            embedded = chr(10).join(line[1:] for line in section.splitlines()
                                    if line.startswith('+')) + chr(10)
            self.assertEqual(embedded, (self.root / 'input' / name).read_text())

    def transfer(self, mode=0, length=63, block=16):
        raw = (ctypes.c_uint8 * 289)(*([0x5a] * 289))
        command = (ctypes.c_uint8 * 12)()
        writes, delays, consumed = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        target = ctypes.cast(ctypes.byref(raw, 16), ctypes.POINTER(ctypes.c_uint8))
        status = self.native.host_qup(mode, length, block, target, command,
                                      ctypes.byref(writes), ctypes.byref(delays), ctypes.byref(consumed))
        self.assertEqual(bytes(raw[:16]), b'Z' * 16)
        self.assertEqual(bytes(raw[16 + length:]), b'Z' * (273 - length))
        return status, bytes(raw[16:16 + length]), bytes(command), writes.value, delays.value, consumed.value

    def test_block_receive_strips_tags_and_padding(self):
        for block in (16, 32):
            for length in (1, 2, 14, 15, 16, 30, 31, 32, 63, 64, 255):
                status, data, command, writes, delays, consumed = self.transfer(length=length, block=block)
                self.assertEqual(status, 0)
                self.assertEqual(data, bytes(range(length)))
                self.assertEqual(command[:8], bytes.fromhex('81 70 82 01 00 81 71 87'))
                self.assertEqual(command[8], length)
                self.assertEqual(consumed, length + 2)

    def test_errors_are_bounded_and_preserve_output(self):
        for mode, expected in [(1, -2), (2, -3), (3, -7), (4, -7), (5, -6), (6, -6), (7, -6)]:
            status, data, command, writes, delays, consumed = self.transfer(mode=mode)
            self.assertEqual(status, expected)
            self.assertEqual(data, b'Z' * 63)
            self.assertLessEqual(delays, 110000)
            if mode == 1:
                self.assertEqual(writes, 0)

    def test_transport_and_state_sanitizers(self):
        compiler = shutil.which('gcc') or shutil.which('clang') or shutil.which('cc')
        executable = Path(self.temporary.name) / 'sanitize'
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-O1', '-g', '-fsanitize=address,undefined',
                        '-fno-omit-frame-pointer', '-I', str(self.root / 'input'),
                        str(self.root / 'tests/input_sanitize.c'), '-o', str(executable)],
                       check=True)
        subprocess.run([str(executable)], check=True, timeout=60)

    def setUp(self):
        self.mock = Mock()
        self.native.host_state_reset(ctypes.byref(self.mock))

    def frame(self, contacts=(), valid=True):
        report = bytearray([0, 0, sum(event != 1 for identity, event, xpos, ypos in contacts)] + [255] * 60)
        for index, (identity, event, xpos, ypos) in enumerate(contacts):
            offset = 3 + index * 6
            report[offset:offset + 6] = bytes([(event << 6) | (xpos >> 8), xpos & 255,
                                              (identity << 4) | (ypos >> 8), ypos & 255, 1, 1])
        if not valid:
            report[0] = 0x40
        raw = (ctypes.c_uint8 * 63).from_buffer_copy(report)
        status = self.native.host_frame(ctypes.byref(self.mock), raw, 63)
        events = [(item.kind, item.slot, item.down, item.x, item.y)
                  for item in self.mock.events[:self.mock.count]]
        return status, events

    def test_hardware_identity_maps_to_stable_hid_slot(self):
        self.assertEqual(self.frame([(14, 0, 10, 20)])[1], [(0, 0, 1, 10, 20)])
        self.assertEqual(self.frame([(14, 2, 10, 20)])[1], [])
        self.assertEqual(self.frame([(3, 0, 30, 40), (14, 2, 11, 21)])[1],
                         [(0, 1, 1, 30, 40), (0, 0, 1, 11, 21)])
        self.assertEqual(self.frame([(3, 2, 30, 40)])[1], [(0, 0, 0, 11, 21)])
        self.assertEqual(self.frame()[1], [(0, 1, 0, 30, 40)])

    def test_home_transition_and_explicit_release(self):
        self.frame([(9, 0, 50, 60)])
        self.assertEqual(self.frame([(9, 2, 500, 2040)])[1],
                         [(0, 0, 0, 50, 60), (1, 0, 1, 0, 0)])
        self.assertEqual(self.frame([(9, 2, 500, 2040)])[1], [])
        self.assertEqual(self.frame()[1], [(1, 0, 0, 0, 0)])
        self.frame([(14, 0, 1, 2), (13, 0, 500, 2040)])
        self.native.host_frame(ctypes.byref(self.mock), None, 0)
        self.assertEqual(self.mock.count, 2)
        self.assertFalse(any(slot.down for slot in self.mock.state.slots))
        self.assertEqual(self.mock.state.home, 0)

    def test_invalid_frame_preserves_state(self):
        self.frame([(14, 0, 1, 2)])
        before = bytes(self.mock.state)
        self.assertEqual(self.frame(valid=False)[0], 0)
        self.assertEqual(bytes(self.mock.state), before)

    def test_menu_back_not_invented_as_home(self):
        self.assertEqual(self.frame([(0, 0, 200, 2040), (1, 0, 800, 2040)])[1], [])


if __name__ == '__main__':
    unittest.main()
