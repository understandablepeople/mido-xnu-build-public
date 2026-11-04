import ctypes
import os
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


class Contact(ctypes.Structure):
    _fields_ = [('x', ctypes.c_uint16), ('y', ctypes.c_uint16),
                ('identity', ctypes.c_uint8), ('down', ctypes.c_uint8),
                ('kind', ctypes.c_uint8)]


class Frame(ctypes.Structure):
    _fields_ = [('count', ctypes.c_uint8), ('active', ctypes.c_uint8),
                ('contacts', Contact * 10)]


@unittest.skipIf(os.name == 'nt', 'run native C tests in WSL')
class FT5435Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which('clang') or shutil.which('cc')
        if not compiler:
            raise unittest.SkipTest('C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        source = directory / 'host.c'
        source.write_text('#include "mido_ft5435.h"\n'
                          'int decode(const uint8_t *data, size_t length, struct mido_ft_frame *frame) '
                          '{ return mido_ft_decode(data, length, frame); }\n'
                          'size_t command(uint8_t address, uint8_t reg, unsigned length, '
                          'uint8_t *output, size_t capacity) '
                          '{ return mido_ft_read_command(address, reg, length, output, capacity); }\n')
        include = Path(__file__).resolve().parents[1] / 'input'
        library = directory / 'host.so'
        subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror',
                        '-shared', '-fPIC', '-O2', '-I', str(include), str(source),
                        '-o', str(library)], check=True)
        cls.native = ctypes.CDLL(str(library))
        cls.native.decode.argtypes = [ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t,
                                     ctypes.POINTER(Frame)]
        cls.native.command.argtypes = [ctypes.c_uint8, ctypes.c_uint8, ctypes.c_uint,
                                      ctypes.POINTER(ctypes.c_uint8), ctypes.c_size_t]
        cls.native.command.restype = ctypes.c_size_t

    def report(self, contacts=(), active=None):
        report = bytearray([0, 0, sum(event != 1 for identity, event, xpos, ypos in contacts)
                            if active is None else active] + [255] * 60)
        for index, (identity, event, xpos, ypos) in enumerate(contacts):
            offset = 3 + 6 * index
            report[offset:offset + 6] = bytes([
                (event << 6) | (xpos >> 8), xpos & 255,
                (identity << 4) | (ypos >> 8), ypos & 255, 1, 1])
        return report

    def decode(self, report):
        raw = (ctypes.c_uint8 * len(report)).from_buffer_copy(report)
        frame = Frame()
        ctypes.memset(ctypes.byref(frame), 0x5a, ctypes.sizeof(frame))
        before = bytes(frame)
        result = self.native.decode(raw, len(report), ctypes.byref(frame))
        if not result:
            self.assertEqual(bytes(frame), before)
        return result, frame

    def test_touch_and_release(self):
        result, frame = self.decode(self.report([(4, 0, 1079, 1919), (13, 1, 20, 30)]))
        self.assertEqual((result, frame.count, frame.active), (1, 2, 1))
        self.assertEqual((frame.contacts[0].identity, frame.contacts[0].x,
                          frame.contacts[0].y, frame.contacts[0].kind), (4, 1079, 1919, 0))
        self.assertEqual(frame.contacts[1].down, 0)
        result, frame = self.decode(self.report(active=0))
        self.assertEqual((result, frame.count, frame.active), (1, 0, 0))

    def test_virtual_keys(self):
        for xpos, kind in [(500, 1), (200, 2), (800, 3), (501, 4)]:
            result, frame = self.decode(self.report([(0, 2, xpos, 2040)]))
            self.assertEqual((result, frame.contacts[0].kind), (1, kind))
        for xpos, ypos in [(1080, 0), (0, 1920), (500, 2039)]:
            result, frame = self.decode(self.report([(0, 0, xpos, ypos)]))
            self.assertEqual((result, frame.contacts[0].kind), (1, 4))

    def test_reject_invalid_without_output_mutation(self):
        invalid = [self.report()[:-1], self.report() + b'0',
                   self.report([(1, 0, 1, 1), (1, 2, 2, 2)]),
                   self.report([(0, 3, 1, 1)], active=1),
                   self.report(active=11), self.report(active=1)]
        factory = self.report()
        factory[0] = 0x40
        invalid.append(factory)
        for report in invalid:
            self.assertEqual(self.decode(report)[0], 0)
        self.assertEqual(self.native.decode(None, 63, ctypes.byref(Frame())), 0)

    def test_randomized_contacts(self):
        generator = random.Random(5435)
        for iteration in range(2000):
            count = generator.randrange(1, 11)
            contacts = [(identity, generator.choice([0, 2]),
                         generator.randrange(1080), generator.randrange(1920))
                        for identity in generator.sample(range(15), count)]
            result, frame = self.decode(self.report(contacts))
            self.assertEqual((result, frame.count, frame.active), (1, count, count))
            for index, (identity, event, xpos, ypos) in enumerate(contacts):
                contact = frame.contacts[index]
                self.assertEqual((contact.identity, contact.down, contact.x, contact.y,
                                  contact.kind), (identity, 1, xpos, ypos, 0))

    def test_qup_v2_read_command(self):
        output = (ctypes.c_uint8 * 13)(*([0x5a] * 13))
        self.assertEqual(self.native.command(0x38, 0, 63, output, 9), 9)
        self.assertEqual(bytes(output[:9]), bytes.fromhex('81 70 82 01 00 81 71 87 3f'))
        self.assertEqual(bytes(output[9:]), b'Z' * 4)
        for address, length, capacity in [(0x80, 63, 9), (0x38, 0, 9),
                                          (0x38, 256, 9), (0x38, 63, 8)]:
            before = bytes(output)
            self.assertEqual(self.native.command(address, 0, length, output, capacity), 0)
            self.assertEqual(bytes(output), before)
        self.assertEqual(self.native.command(0x38, 0, 63, None, 9), 0)

    def test_sanitized_malformed_reports(self):
        compiler = shutil.which('gcc')
        if not compiler:
            self.skipTest('GCC sanitizer runtime unavailable')
        directory = Path(self.temporary.name)
        source = directory / 'sanitize.c'
        source.write_text(r'''
#include "mido_ft5435.h"
#include <string.h>
int main(void)
{
    uint32_t random_state = 5435;
    for (unsigned iteration = 0; iteration < 100000; iteration++) {
        uint8_t report[MIDO_FT_REPORT_BYTES];
        for (unsigned index = 0; index < sizeof(report); index++) {
            random_state = random_state * 1664525U + 1013904223U;
            report[index] = (uint8_t)(random_state >> 24);
        }
        struct guarded_frame {
            uint64_t before;
            struct mido_ft_frame frame;
            uint64_t after;
        } guarded;
        memset(&guarded, 0x5a, sizeof(guarded));
        struct mido_ft_frame previous = guarded.frame;
        size_t length = iteration % (sizeof(report) + 1);
        int result = mido_ft_decode(report, length, &guarded.frame);
        if (guarded.before != 0x5a5a5a5a5a5a5a5aULL ||
            guarded.after != 0x5a5a5a5a5a5a5a5aULL ||
            (!result && memcmp(&previous, &guarded.frame, sizeof(previous)))) {
            return 1;
        }
        if (result && (guarded.frame.count > MIDO_FT_CONTACTS ||
            guarded.frame.active > guarded.frame.count)) {
            return 2;
        }
    }
    return 0;
}
''')
        executable = directory / 'sanitize'
        include = Path(__file__).resolve().parents[1] / 'input'
        subprocess.run([compiler, '-std=c11', '-O1', '-g', '-Wall', '-Wextra',
                        '-Werror', '-fsanitize=address,undefined',
                        '-fno-sanitize-recover=all', '-I', str(include), str(source),
                        '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    unittest.main()
