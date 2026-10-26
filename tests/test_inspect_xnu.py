import struct
import unittest

from tools.inspect_xnu import inspect


BASE = 0xFFFFFFF007004000


def make_image(extra=b"", subtype=0, entry=None):
    segment = struct.pack("<II16s4Q4I", 0x19, 72, b"__TEXT", BASE, 4096, 0, 1024, 5, 5, 0, 0)
    thread = bytearray(288)
    struct.pack_into("<4I", thread, 0, 5, 288, 6, 68)
    struct.pack_into("<Q", thread, 272, BASE + 512 if entry is None else entry)
    commands = segment + thread + extra
    image = bytearray(1024)
    struct.pack_into("<8I", image, 0, 0xFEEDFACF, 0x0100000C, subtype, 2, 2 + bool(extra), len(commands), 0, 0)
    image[32:32 + len(commands)] = commands
    return image


class XnuInspectionTests(unittest.TestCase):
    def test_valid_structure_is_never_boot_approval(self):
        result = inspect(make_image())
        self.assertFalse(result["boot_approved"])
        self.assertEqual(result["entry_va"], BASE + 512)
        self.assertEqual(result["segments"][0]["name"], "__TEXT")
        self.assertTrue(result["blockers"])

    def test_wrong_cpu_and_arm64e(self):
        for subtype in (1, 2, 0x80000002):
            with self.subTest(subtype=subtype), self.assertRaises(ValueError):
                inspect(make_image(subtype=subtype))
        image = make_image()
        struct.pack_into("<I", image, 4, 0x01000007)
        with self.assertRaises(ValueError):
            inspect(image)

    def test_wrong_magic_or_filetype(self):
        for offset, value in ((0, 0xCAFEBABE), (12, 12), (28, 1)):
            image = make_image()
            struct.pack_into("<I", image, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                inspect(image)

    def test_truncated_header_or_data(self):
        for size in (0, 31, 39, 1023):
            with self.subTest(size=size), self.assertRaises(ValueError):
                inspect(make_image()[:size])

    def test_bad_command_size(self):
        for size in (0, 7, 73, 4096):
            image = make_image()
            struct.pack_into("<I", image, 36, size)
            with self.subTest(size=size), self.assertRaises(ValueError):
                inspect(image)

    def test_command_count_mismatch(self):
        for count in (0, 1, 3, 0xFFFFFFFF):
            image = make_image()
            struct.pack_into("<I", image, 16, count)
            with self.subTest(count=count), self.assertRaises(ValueError):
                inspect(image)

    def test_non_executable_or_unbacked_entry(self):
        for entry in (BASE - 4, BASE + 513, BASE + 1024):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                inspect(make_image(entry=entry))
        image = make_image()
        struct.pack_into("<I", image, 92, 1)
        with self.assertRaises(ValueError):
            inspect(image)

    def test_virtual_range_overflow(self):
        image = make_image()
        struct.pack_into("<Q", image, 56, (1 << 64) - 16)
        with self.assertRaises(ValueError):
            inspect(image)

    def test_invalid_sizes_protections_or_sections(self):
        for offset, value, fmt in ((64, 512, "<Q"), (80, 1025, "<Q"), (88, 8, "<I"), (92, 7, "<I"), (96, 1, "<I")):
            image = make_image()
            struct.pack_into(fmt, image, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                inspect(image)

    def test_overlapping_segments(self):
        for address, offset in ((BASE, 0), (BASE + 8192, 512)):
            extra = struct.pack("<II16s4Q4I", 0x19, 72, b"__DATA", address, 4096, offset, 512, 3, 3, 0, 0)
            with self.subTest(address=address), self.assertRaises(ValueError):
                inspect(make_image(extra))

    def test_thread_shape_and_duplicate(self):
        for offset, value in ((112, 7), (116, 67)):
            image = make_image()
            struct.pack_into("<I", image, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                inspect(image)
        image = make_image()
        with self.assertRaises(ValueError):
            inspect(make_image(bytes(image[104:392])))

    def test_fixups_are_blocked_not_resolved(self):
        command = struct.pack("<4I", 0x80000034, 16, 900, 32)
        result = inspect(make_image(command))
        self.assertIn("chained fixups require a separate validated resolver", result["blockers"])
        for offset, size in ((1024, 1), (900, 0), (0xFFFFFFFF, 32)):
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                inspect(make_image(struct.pack("<4I", 0x80000034, 16, offset, size)))

    def test_unknown_command_blocks(self):
        result = inspect(make_image(struct.pack("<II", 0x777, 8)))
        self.assertTrue(any("0x00000777" in reason for reason in result["blockers"]))


if __name__ == "__main__":
    unittest.main()
