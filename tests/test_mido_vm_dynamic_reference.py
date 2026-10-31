import os
from pathlib import Path
import struct
import unittest

from tools.inspect_xnu import inspect
from tools.mido_vm_checkpoint_plan import dynamic_plan
from tools.mido_vm_dynamic_reference import DynamicReference, DYNAMIC_STAGES
from tools.mido_vm_translation_audit import walk, VIRTUAL, PHYSICAL, TOP


class DynamicReferenceTests(unittest.TestCase):
    def kernel(self):
        path = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", Path(__file__).resolve().parents[1] /
                                   "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"))
        if not path.exists():
            self.skipTest("Pinned kernel unavailable")
        return path.read_bytes()

    def reference(self, count=1):
        kernel = self.kernel()
        dynamic_plan(kernel)
        return DynamicReference(inspect(kernel)["segments"], VIRTUAL, PHYSICAL, TOP, count)

    def test_unknown_kernel_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact reviewed"):
            dynamic_plan(b"unknown")

    def test_eight_exact_boundaries(self):
        plan = dynamic_plan(self.kernel())
        self.assertEqual(tuple(plan), tuple(DYNAMIC_STAGES))
        self.assertEqual(plan["vm-dynamic-before-first-link"], 0xfffffff007446cd0)
        self.assertEqual(plan["vm-dynamic-roots-ready"], 0xfffffff007446924)
        self.assertEqual(plan["vm-physmap-entry"], 0xfffffff007446954)

    def test_every_dynamic_root_is_unique_sequential_and_nonexecutable(self):
        for count in (1, 2):
            reference = self.reference(count)
            links = reference.links()
            self.assertEqual(len(links), 48 - count)
            first = TOP + (8 + count) * 4096
            for index, (address, value) in enumerate(links.items()):
                self.assertEqual(address, TOP + 4096 + (192 + count + index) * 8)
                self.assertEqual(value, (first + index * 4096) | 0x3800000000000003)

    def test_no_hardcoded_single_geometry_and_all_56_pages_compared(self):
        for count in (1, 2):
            reference = self.reference(count)
            snapshot = reference.expected("vm-physmap-entry")
            self.assertEqual(len(snapshot), 56 * 4096)
            for address, value in reference.links().items():
                self.assertEqual(struct.unpack_from("<Q", snapshot, address - TOP)[0], value)
                page = (value & 0x0000fffffffff000) - TOP
                self.assertEqual(snapshot[page:page + 4096], bytes(4096))
            self.assertEqual(snapshot, reference.expected("vm-dynamic-roots-ready"))

    def test_first_clear_preserves_poison_until_original_call(self):
        reference = self.reference()
        base = reference.expected("vm-dynamic-before-first-link")
        before = reference.expected("vm-dynamic-before-first-clear")
        after = reference.expected("vm-dynamic-first-cleared")
        self.assertEqual(len(before), len(base) + 4096)
        self.assertEqual(before[-4096:], bytes([165]) * 4096)
        self.assertEqual(after[-4096:], bytes(4096))
        self.assertEqual(before[:-4096], after[:-4096])

    def test_writes_need_exact_site_address_and_permissions(self):
        reference = self.reference()
        address, value = next(iter(reference.links().items()))
        start = 0xfffffff007445650
        self.assertTrue(reference.accepts_dynamic_link(address, 8, value, start + 0x1680, start))
        self.assertFalse(reference.accepts_dynamic_link(address, 8, value, start + 0x1684, start))
        self.assertFalse(reference.accepts_dynamic_link(address, 4, value, start + 0x1680, start))
        self.assertFalse(reference.accepts_dynamic_link(address, 8, value ^ (1 << 59), start + 0x1680, start))
        self.assertFalse(reference.accepts_dynamic_link(address + 8, 8, value, start + 0x1680, start))

    def test_dynamic_roots_still_have_no_leaf_mappings(self):
        reference = self.reference()
        snapshot = reference.expected("vm-physmap-entry")
        for slot in reference.dynamic_slots:
            address = ((1 << 64) - (1 << 38)) + (slot << 30)
            result = walk(snapshot, address)
            self.assertFalse(result["mapped"])
            self.assertEqual(result["reason"], "invalid-descriptor")
            self.assertEqual(result["trace"][0]["descriptor"] >> 59 & 7, 7)


if __name__ == "__main__":
    unittest.main()
