import os
from pathlib import Path
import struct
import unittest

from tools.inspect_xnu import inspect
from tools.mido_vm_checkpoint_plan import remaining_plan
from tools.mido_vm_remaining_reference import RemainingReference, REMAINING_STAGES


class RemainingReferenceTests(unittest.TestCase):
    def kernel(self):
        path = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", Path(__file__).resolve().parents[1] /
                                   "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"))
        if not path.exists():
            self.skipTest("Pinned kernel unavailable")
        return path.read_bytes()

    def reference(self, count=1):
        kernel = self.kernel()
        remaining_plan(kernel)
        return RemainingReference(inspect(kernel)["segments"], 0xfffffff007000000,
                                  0x11200000, 0x12401000, count)

    def test_unknown_kernel_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact reviewed"):
            remaining_plan(b"unreviewed")

    def test_reviewed_call_boundaries(self):
        checkpoints = remaining_plan(self.kernel())
        self.assertEqual(tuple(checkpoints), tuple(REMAINING_STAGES))
        self.assertEqual(checkpoints["vm-bootdata-mapped"], 0xfffffff007444a60)
        self.assertEqual(checkpoints["vm-stack-guards-mapped"], 0xfffffff007444acc)
        self.assertEqual(checkpoints["vm-all-segments-mapped"], 0xfffffff007444c3c)

    def test_empty_segments_do_not_allocate(self):
        reference = self.reference()
        self.assertEqual(reference.expected("vm-hibdata-mapped"), reference.expected("vm-data-mapped"))
        self.assertEqual(list(reference.mappings("__PLK_LINKEDIT")), [])
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            reference.arguments("unreviewed")

    def test_stack_guards_override_all_four_native_pages(self):
        reference = self.reference()
        _, before = reference.state("__BOOTDATA")
        layout, after = reference.state("excepstack_high_guard")
        for name in ("intstack_low_guard", "intstack_high_guard", "excepstack_high_guard"):
            start, length, _, _, access, _, granule = reference.arguments(name)
            self.assertEqual((length, access, granule), (16384, 2, 0))
            for address in range(start, start + length, 4096):
                destination = layout[(address - reference.virtual) >> 21] + ((address >> 12) & 511) * 8
                self.assertEqual(before[destination] & 0xc0, 0)
                self.assertEqual(after[destination], before[destination] | 0x80)
                self.assertTrue(after[destination] & (1 << 53))

    def test_final_tables_include_linkedit_and_lastdata(self):
        for count in (1, 2):
            reference = self.reference(count)
            layout, descriptors = reference.state("__PRELINK_INFO")
            self.assertEqual(set(layout), {0, 1, 5, 6, 7})
            expected = reference.expected("vm-all-segments-mapped")
            self.assertEqual(len(expected), (7 + count) * 4096)
            for address, value in descriptors.items():
                self.assertEqual(struct.unpack_from("<Q", expected, address - reference.top)[0], value)
            _, length, _, _, access, xn, _ = reference.arguments("__KLD")
            self.assertEqual((length, access, xn), (16384, 2, 0))
            self.assertEqual(reference.arguments("__KLDDATA")[4:6], (2, 1))
            self.assertEqual(reference.arguments("__LASTDATA_CONST")[4:6], (0, 1))

    def test_guard_stores_require_original_site_and_readonly_descriptor(self):
        reference = self.reference()
        reference.request = "intstack_low_guard"
        helper = 0xfffffff007445090
        address, value, block = next(reference.mappings(reference.request))
        layout, _ = reference.state(reference.request)
        destination = layout[(address - reference.virtual) >> 21] + ((address >> 12) & 511) * 8
        self.assertFalse(block)
        self.assertTrue(reference.accepts(destination, 8, value, helper + 0x210, helper))
        self.assertFalse(reference.accepts(destination, 8, value ^ 0x80, helper + 0x210, helper))
        self.assertFalse(reference.accepts(destination, 8, value, helper + 0x214, helper))


if __name__ == "__main__":
    unittest.main()
