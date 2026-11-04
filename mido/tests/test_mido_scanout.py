import ctypes
import os
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from patch_sources import kernel_source


class Buffer(ctypes.Structure):
    _fields_ = [('pixels', ctypes.POINTER(ctypes.c_uint8)), ('length', ctypes.c_uint64),
                ('width', ctypes.c_uint32), ('height', ctypes.c_uint32),
                ('row_bytes', ctypes.c_uint32), ('pixel_bytes', ctypes.c_uint32)]


class Rect(ctypes.Structure):
    _fields_ = [(name, ctypes.c_int32) for name in
                ('source_x', 'source_y', 'source_width', 'source_height',
                 'target_x', 'target_y', 'target_width', 'target_height')]


class PatchConsistencyTests(unittest.TestCase):
    def test_kernel_uses_tested_header(self):
        root = Path(__file__).resolve().parents[2]
        header = kernel_source(root, "mido_scanout.h", "0106-mido-bgr24-scaled-display.patch")
        self.assertEqual(header, (root / 'mido/display/mido_scanout.h').read_text())


@unittest.skipIf(os.name == 'nt', 'run native scanout tests with WSL clang')
class ScanoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which('clang') or shutil.which('cc')
        if not cls.compiler:
            raise unittest.SkipTest('host C compiler unavailable')
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.host = Path(__file__).with_name('scanout_host.c')
        library = Path(cls.temporary.name) / 'scanout.so'
        subprocess.run([cls.compiler, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        '-shared', '-fPIC', str(cls.host), '-o', str(library)], check=True)
        cls.native = ctypes.CDLL(str(library))
        cls.native.host_blit.argtypes = [ctypes.POINTER(Buffer), ctypes.POINTER(Buffer),
                                        ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(Rect)]
        cls.native.host_blit.restype = ctypes.c_uint64
        cls.native.host_touch.argtypes = [ctypes.c_int32, ctypes.c_uint32]
        cls.native.host_touch.restype = ctypes.c_uint32

    def blit(self, source_data, width, height, stride, target_width,
             target_height, target_stride, pixel_bytes, canvas, rect):
        source_raw = (ctypes.c_uint8 * len(source_data)).from_buffer_copy(source_data)
        length = target_stride * target_height
        target_raw = (ctypes.c_uint8 * (length + 32))(*([0x5a] * (length + 32)))
        source = Buffer(source_raw, len(source_data), width, height, stride, 4)
        target = Buffer(ctypes.cast(ctypes.byref(target_raw, 16), ctypes.POINTER(ctypes.c_uint8)),
                        length, target_width, target_height, target_stride, pixel_bytes)
        count = self.native.host_blit(source, target, *canvas, rect)
        self.assertEqual(bytes(target_raw[:16]), b'Z' * 16)
        self.assertEqual(bytes(target_raw[-16:]), b'Z' * 16)
        return count, bytes(target_raw[16:-16])

    def test_pixel_order(self):
        count, data = self.blit(bytes([1, 2, 3, 255, 4, 5, 6, 127]), 2, 1, 8,
                                2, 1, 8, 3, (2, 1), Rect(0, 0, 2, 1, 0, 0, 2, 1))
        self.assertEqual(count, 2)
        self.assertEqual(data, bytes([1, 2, 3, 4, 5, 6, 90, 90]))

    def test_reference_random_rectangles(self):
        generator = random.Random(4242)
        for trial in range(1500):
            width, height, target_width, target_height = [generator.randint(1, 12) for _ in range(4)]
            canvas_width, canvas_height = [generator.randint(1, 15) for _ in range(2)]
            pixel_bytes = generator.choice((3, 4))
            stride = width * 4 + generator.randint(0, 7)
            target_stride = target_width * pixel_bytes + generator.randint(0, 7)
            source = generator.randbytes(stride * height)
            values = [generator.randint(-10, 20) for _ in range(8)]
            rect = Rect(*values)
            expected = bytearray(b'Z' * (target_stride * target_height))
            copied = 0
            if min(rect.source_width, rect.source_height, rect.target_width, rect.target_height) > 0:
                for panel_y in range(target_height):
                    logical_y = panel_y * canvas_height // target_height
                    if not rect.target_y <= logical_y < rect.target_y + rect.target_height:
                        continue
                    source_y = rect.source_y + (logical_y - rect.target_y) * rect.source_height // rect.target_height
                    if not 0 <= source_y < height:
                        continue
                    for panel_x in range(target_width):
                        logical_x = panel_x * canvas_width // target_width
                        if not rect.target_x <= logical_x < rect.target_x + rect.target_width:
                            continue
                        source_x = rect.source_x + (logical_x - rect.target_x) * rect.source_width // rect.target_width
                        if not 0 <= source_x < width:
                            continue
                        source_offset = source_y * stride + source_x * 4
                        target_offset = panel_y * target_stride + panel_x * pixel_bytes
                        expected[target_offset:target_offset + pixel_bytes] = source[source_offset:source_offset + pixel_bytes]
                        copied += 1
            count, data = self.blit(source, width, height, stride, target_width, target_height,
                                    target_stride, pixel_bytes, (canvas_width, canvas_height), rect)
            self.assertEqual((count, data), (copied, bytes(expected)), f'trial {trial}: {values}')

    def test_short_allocation_and_stride(self):
        source_raw = (ctypes.c_uint8 * 16)()
        target_raw = (ctypes.c_uint8 * 12)()
        rect = Rect(0, 0, 2, 2, 0, 0, 2, 2)
        for length, stride in [(15, 8), (16, 7)]:
            source = Buffer(source_raw, length, 2, 2, stride, 4)
            target = Buffer(target_raw, 12, 2, 2, 6, 3)
            self.assertEqual(self.native.host_blit(source, target, 2, 2, rect), 0)
            self.assertEqual(bytes(target_raw), bytes(12))

    def test_full_iphone_8_plus_canvas(self):
        source = bytes([11, 22, 33, 255]) * (1242 * 2208)
        count, data = self.blit(source, 1242, 2208, 1242 * 4, 1080, 1920, 3240,
                                3, (1242, 2208), Rect(0, 0, 1242, 2208, 0, 0, 1242, 2208))
        self.assertEqual(count, 1080 * 1920)
        self.assertEqual(data, bytes([11, 22, 33]) * (1080 * 1920))

    def test_touch_corners_and_clamping(self):
        for extent in (1080, 1920):
            self.assertEqual(self.native.host_touch(-100, extent), 0)
            self.assertEqual(self.native.host_touch(0, extent), 0)
            self.assertEqual(self.native.host_touch(extent // 2, extent), 32768)
            self.assertEqual(self.native.host_touch(extent - 1, extent), ((extent - 1) << 16) // extent)
            self.assertEqual(self.native.host_touch(2147483647, extent), self.native.host_touch(extent - 1, extent))
        self.assertEqual(self.native.host_touch(10, 0), 0)

    def test_sanitizers(self):
        executable = Path(self.temporary.name) / 'sanitized'
        compiler = shutil.which('gcc') or self.compiler
        subprocess.run([compiler, '-std=c11', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
                        '-DMIDO_SCANOUT_SELF_TEST', str(self.host), '-o', str(executable)], check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == '__main__':
    unittest.main()
