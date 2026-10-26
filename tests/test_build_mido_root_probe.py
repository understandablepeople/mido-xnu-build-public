import struct
import unittest

from tools.build_mido_root_probe import FILE_SIZE, TEXT_BASE, TEXT_OFFSET, executable
from tools.inspect_xnu import inspect


class RootProbeTests(unittest.TestCase):
    def test_standalone_arm64_thread_entry_and_code_without_dyld(self):
        code = struct.pack("<3I", 0xd2800290, 0xd4001001, 0x14000000)
        payload = executable(code)
        report = inspect(payload)
        self.assertEqual(len(payload), FILE_SIZE)
        self.assertEqual(report["entry_va"], TEXT_BASE + TEXT_OFFSET)
        self.assertEqual(payload[TEXT_OFFSET:TEXT_OFFSET + len(code)], code)
        self.assertEqual(report["flags"], 1)
        self.assertEqual(report["commands"], ["0x00000019", "0x00000019", "0x00000005", "0x00000032"])
        self.assertEqual(report["segments"][0]["initprot"], 0)
        self.assertEqual(report["segments"][1]["initprot"], 5)

    def test_rejects_empty_unaligned_and_oversized_code(self):
        for code in (b"", b"abc", bytes(4100)):
            with self.assertRaises(ValueError):
                executable(code)


if __name__ == "__main__":
    unittest.main()
