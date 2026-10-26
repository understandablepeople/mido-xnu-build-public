import struct
import unittest

from tools.mido_boot_checkpoints import bl_target, call_sites


class BootCheckpointTests(unittest.TestCase):
    def test_bl_signed_offsets_and_non_call_instructions(self):
        self.assertEqual(bl_target(0x1000, 0x94000002), 0x1008)
        self.assertEqual(bl_target(0x1000, 0x97ffffff), 0xffc)
        self.assertEqual(bl_target(0x10000000, 0x96000000), 0x08000000)
        self.assertEqual(bl_target(0x10000000, 0x95ffffff), 0x17fffffc)
        for instruction in (0x14000002, 0xd65f03c0, 0xd63f0000, 0):
            self.assertIsNone(bl_target(0x1000, instruction))

    def fixture(self):
        blob = struct.pack("<4I", 0x94000008, 0xd503201f, 0x94000006, 0xd65f03c0)
        inspection = dict(segments=[dict(vmaddr=0x1000, fileoff=0, filesize=16, initprot=5)])
        symbols = dict(caller=0x1000, next_function=0x1010, target=0x1020)
        return blob, inspection, symbols

    def test_only_actual_calls_in_caller_are_checkpoint_evidence(self):
        blob, inspection, symbols = self.fixture()
        self.assertEqual(call_sites(blob, inspection, symbols, "caller", "target"), [0x1000, 0x1008])
        symbols["target"] = 0x2000
        self.assertEqual(call_sites(blob, inspection, symbols, "caller", "target"), [])

    def test_invalid_boundaries_are_not_accepted(self):
        blob, inspection, symbols = self.fixture()
        with self.assertRaises(ValueError):
            call_sites(blob[:-1], inspection, symbols, "caller", "target")
        inspection["segments"][0]["initprot"] = 1
        with self.assertRaises(ValueError):
            call_sites(blob, inspection, symbols, "caller", "target")
        with self.assertRaises(ValueError):
            call_sites(blob, inspection, symbols, "missing", "target")
