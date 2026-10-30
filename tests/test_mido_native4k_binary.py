import os
from pathlib import Path
import struct
import unittest

from tools.audit_mido_native4k_binary import audit, reference_tables, PHYSICAL, POOL_SIZE


class Native4KBinaryTests(unittest.TestCase):
    def test_reference_clears_unused_pages(self):
        tables, exhausted = reference_tables(0x11352000, PHYSICAL + 16384, 0xfffffff007004000, 33554432)
        self.assertFalse(exhausted)
        self.assertEqual(len(tables), POOL_SIZE)
        self.assertEqual(tables[16384:], bytes(49152))
        self.assertEqual(struct.unpack_from("<Q", tables, 8192 + 137 * 8)[0], 0x11200601)

    def test_reference_detects_exhaustion(self):
        tables, exhausted = reference_tables(0x11352000, PHYSICAL + 16384, 0xfffffff007004000, 8 << 30)
        self.assertTrue(exhausted)
        self.assertEqual(len(tables), POOL_SIZE)

    def test_reference_rejects_unsupported_extent(self):
        for extent in (0, -1, 1 << 40):
            with self.subTest(extent=extent), self.assertRaises(ValueError):
                reference_tables(0x11352000, PHYSICAL + 16384, 0xfffffff007004000, extent)

    def test_unknown_binary_rejected_before_emulation(self):
        with self.assertRaisesRegex(ValueError, "exact reviewed"):
            audit(b"not a reviewed kernel")

    @unittest.skipUnless(os.environ.get("MIDO_NATIVE4K_KERNEL"), "Set MIDO_NATIVE4K_KERNEL to the pinned cloud artifact")
    def test_actual_binary_normal_cross_boundary_and_exhaustion(self):
        kernel = Path(os.environ["MIDO_NATIVE4K_KERNEL"]).read_bytes()
        for extent, exhausted in ((33554432, False), (3 << 30, False), (8 << 30, True)):
            with self.subTest(extent=extent):
                result = audit(kernel, extent)
                self.assertEqual(result["pool_exhaustion_stopped"], exhausted)
                self.assertEqual(result["all_arena_bytes_verified"], 33554432)
                self.assertFalse(result["boot_approved"])
                self.assertFalse(result["mmu_enabled"])
