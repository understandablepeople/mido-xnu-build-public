import os
from pathlib import Path
import struct
import unittest

from tools.mido_vm_protection_reference import ProtectionReference
from tools.mido_vm_checkpoint_plan import PROTECTION_CHECKPOINTS, protection_plan


class ProtectionReferenceTests(unittest.TestCase):
    def reference(self):
        return ProtectionReference([
            dict(name="__TEXT", vmaddr=0xfffffff007004000, vmsize=0x13c000),
            dict(name="__DATA_CONST", vmaddr=0xfffffff007140000, vmsize=0xd4000)],
            0xfffffff007000000, 0x11200000, 0x12401000)

    def test_real_checkpoint_calls_are_pinned(self):
        if not os.environ.get("MIDO_NATIVE4K_KERNEL"):
            self.skipTest("Pinned kernel unavailable")
        path = Path(os.environ["MIDO_NATIVE4K_KERNEL"])
        checkpoints = protection_plan(path.read_bytes())
        self.assertEqual(tuple(checkpoints), PROTECTION_CHECKPOINTS)
        self.assertEqual(checkpoints["vm-memory-map-lookup"], 0xfffffff0074446c8)
        self.assertEqual(checkpoints["vm-data-const-mapped"], 0xfffffff0074449c0)

    def test_unknown_kernel_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact reviewed"):
            protection_plan(b"unreviewed")

    def test_text_permissions_and_contiguous_edges(self):
        reference = self.reference()
        leaves = reference.leaves("__TEXT")
        self.assertEqual(len(leaves), 316)
        self.assertEqual(leaves[0x12404020], 0x0060000011204683)
        self.assertEqual(leaves[0x12404078], 0x006000001120f683)
        self.assertEqual(leaves[0x12404080], 0x0070000011210683)
        self.assertEqual(leaves[0x124049f8], 0x007000001133f683)

    def test_data_const_is_writable_nonexecutable_without_hint(self):
        leaves = self.reference().leaves("__DATA_CONST")
        self.assertEqual(len(leaves), 212)
        self.assertEqual(leaves[0x12404a00], 0x0060000011340603)
        self.assertFalse(any(value & (1 << 52) for value in leaves.values()))

    def test_exact_store_sites_values_and_addresses_only(self):
        reference = self.reference()
        helper = 0xfffffff007445090
        address, value = reference.link()
        self.assertFalse(reference.accepts(address, 8, value, helper + 0x128, helper))
        reference.request = "__TEXT"
        self.assertTrue(reference.accepts(address, 8, value, helper + 0x128, helper))
        for changed_address, length, changed_value, pc in (
                (address + 8, 8, value, helper + 0x128),
                (address, 4, value, helper + 0x128),
                (address, 8, value ^ 1, helper + 0x128),
                (address, 8, value, helper + 0x12c)):
            self.assertFalse(reference.accepts(changed_address, length, changed_value, pc, helper))
        address, value = next(iter(reference.leaves("__TEXT").items()))
        self.assertTrue(reference.accepts(address, 8, value, helper + 0x210, helper))
        self.assertFalse(reference.accepts(address, 8, value ^ 0x80, helper + 0x210, helper))
        self.assertFalse(reference.accepts(address, 8, value, helper + 0x214, helper))

    def test_four_pages_preserve_unmapped_slots_and_initial_roots(self):
        reference = self.reference()
        before = reference.expected("vm-before-l3-clear")
        cleared = reference.expected("vm-after-l3-clear")
        mapped = reference.expected("vm-data-const-mapped")
        self.assertEqual(before[12288:], bytes([165]) * 4096)
        self.assertFalse(any(cleared[12288:]))
        self.assertEqual(len(mapped), 20480)
        self.assertFalse(any(mapped[:4096]))
        self.assertEqual(struct.unpack_from("<Q", mapped, 4096 + 192 * 8)[0], 0x2000000012403003)
        self.assertEqual(struct.unpack_from("<Q", mapped, 8192 + 56 * 8)[0], 0x12404003)
        self.assertFalse(any(mapped[12288:12288 + 32]))
        self.assertEqual(struct.unpack_from("<Q", mapped, 8192 + 57 * 8)[0], 0x12405003)
        self.assertFalse(any(mapped[16384 + 20 * 8:]))

    def test_mapping_must_not_escape_first_l3(self):
        reference = self.reference()
        reference.segments["__TEXT"]["vmsize"] = 0x400000
        with self.assertRaisesRegex(ValueError, "escaped"):
            reference.leaves("__TEXT")


if __name__ == "__main__":
    unittest.main()
