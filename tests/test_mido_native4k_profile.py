import hashlib
import os
from pathlib import Path
import unittest

from tools.mido_native4k_profile import review, reference_tables, KERNEL_SHA256


class Native4KProfileTests(unittest.TestCase):
    def kernel(self):
        default = Path(__file__).resolve().parents[1] / "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"
        path = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", default))
        if not path.exists():
            self.skipTest("Pinned native-4K cloud artifact unavailable")
        return path.read_bytes()

    def test_unknown_binary_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact reviewed"):
            review(b"not reviewed")

    def test_actual_profile_contains_complete_pool_check_without_large_rodata(self):
        header, result = review(self.kernel(), True, True)
        self.assertEqual(result["kernel_sha256"], KERNEL_SHA256)
        self.assertEqual(result["bootstrap_pool_bytes"], 65536)
        self.assertIn("#define MIDO_NATIVE_TABLE_WORDS 8192", header)
        self.assertIn("#define MIDO_NATIVE_REFERENCE_WORDS 2048", header)
        self.assertFalse(result["boot_approved"])
        self.assertEqual(result["halt_vector_patch"]["replacement_word"], 0xf0ffffe0)

    def test_reference_matches_independent_executed_binary_report(self):
        kernel = self.kernel()
        _, result = review(kernel, True)
        tables = reference_tables(kernel, 0x11200000, result["values"]["MIDO_EARLY_VIRT_BASE"], 33554432)
        self.assertEqual(len(tables), 65536)
        self.assertEqual(hashlib.sha256(tables).hexdigest(), "a2f56243fe5f9f9c2a8cd6c4f16ad59fe85116db7c2aa330df158a7feca20e9e")
        self.assertFalse(any(tables[16384:]))

    def test_mmu_requires_explicit_tables(self):
        with self.assertRaisesRegex(ValueError, "requires native tables"):
            review(self.kernel(), False, True)

    def test_altered_geometry_rejected(self):
        kernel = self.kernel()
        _, result = review(kernel)
        with self.assertRaisesRegex(ValueError, "bounded"):
            reference_tables(kernel, 0x11200000, result["values"]["MIDO_EARLY_VIRT_BASE"], 3 << 30)
