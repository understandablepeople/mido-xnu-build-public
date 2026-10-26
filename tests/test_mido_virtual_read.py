import struct
import unittest

from tools.mido_mmu_fault import read_upper


class VirtualReadTests(unittest.TestCase):
    def setUp(self):
        self.ram = bytearray(0x10000)
        self.base = 0xffffff8000000000
        self.tcr = (2 << 30) | (25 << 16)
        struct.pack_into("<Q", self.ram, 0x1000, 0x2003)
        struct.pack_into("<Q", self.ram, 0x2000, 0x3003)
        struct.pack_into("<Q", self.ram, 0x3000, 0x7403)
        struct.pack_into("<Q", self.ram, 0x3008, 0x9403)
        self.ram[0x7ffe:0x8000] = b"md"
        self.ram[0x9000:0x9002] = b"0\0"

    def read(self, address, count):
        return bytes(self.ram[address:address + count])

    def test_reads_noncontiguous_native_pages_without_changes(self):
        before = bytes(self.ram)
        result = read_upper(self.read, self.tcr, 0x1000, self.base + 4094, 4, 0, len(self.ram))
        self.assertEqual(result, b"md0\0")
        self.assertEqual(bytes(self.ram), before)

    def test_rejects_missing_page_and_access_flag(self):
        for descriptor in (0, 0x9003):
            struct.pack_into("<Q", self.ram, 0x3008, descriptor)
            with self.assertRaisesRegex(ValueError, "accessible mapping"):
                read_upper(self.read, self.tcr, 0x1000, self.base + 4094, 4, 0, len(self.ram))

    def test_rejects_outside_ram(self):
        with self.assertRaisesRegex(ValueError, "outside fixture RAM"):
            read_upper(self.read, self.tcr, 0x1000, self.base + 4096, 4, 0, 0x8000)

    def test_rejects_invalid_size_and_wraparound(self):
        for address, count in ((self.base, 0), (self.base, 4097), ((1 << 64) - 2, 4)):
            with self.assertRaisesRegex(ValueError, "bounded virtual read"):
                read_upper(self.read, self.tcr, 0x1000, address, count, 0, len(self.ram))


if __name__ == "__main__":
    unittest.main()
