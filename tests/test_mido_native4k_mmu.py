import os
from pathlib import Path
import unittest

from tools.audit_mido_native4k_mmu import MODES, execute, branch_word, adrp_word


class Native4KMMUTests(unittest.TestCase):
    def test_branch_bounds(self):
        self.assertEqual(branch_word(0x18000000, 0x10000000), 0x16000000)
        self.assertEqual(branch_word(0x10000000, 0x17fffffc), 0x15ffffff)
        for source, target in ((0, 1), (0, 1 << 27), (0x18000004, 0x10000000)):
            with self.subTest(source=source, target=target), self.assertRaises(ValueError):
                branch_word(source, target)

    def test_adrp_halt_vector_patch(self):
        self.assertEqual(adrp_word(0xfffffff00722d38c, 0xfffffff00722c000), 0xf0ffffe0)
        self.assertEqual(adrp_word(0xfffffff00722d38c, 0xfffffff007229000), 0x90ffffe0)
        with self.assertRaises(ValueError):
            adrp_word(0, 1 << 32)

    def test_unknown_binary_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact reviewed"):
            execute(b"unreviewed", b"unreviewed")

    def test_unknown_mode_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            execute(b"", b"", "ignore-faults")

    @unittest.skipUnless(os.environ.get("MIDO_NATIVE4K_KERNEL") and os.environ.get("MIDO_NATIVE4K_OBSERVER"),
                         "Set pinned kernel and compiled observer paths to enable integration")
    def test_actual_mmu_startup_and_each_missing_mapping(self):
        kernel = Path(os.environ["MIDO_NATIVE4K_KERNEL"]).read_bytes()
        observer = Path(os.environ["MIDO_NATIVE4K_OBSERVER"]).read_bytes()
        for mode in MODES:
            with self.subTest(mode=mode):
                result = execute(kernel, observer, mode)
                self.assertEqual(bool(result["faults"]), mode != "normal")
                self.assertFalse(result["boot_approved"])
                self.assertEqual(result["all_arena_bytes_verified"], 33554432)
        with self.assertRaisesRegex(ValueError, "mapped observer"):
            execute(kernel, observer[:-1])
