import hashlib
import os
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols
from tools.mido_vm_checkpoint_plan import physmap_plan
from tools.mido_vm_physmap_complete_plan import COMPLETE_PHYSMAP_STAGES, complete_physmap_plan


MODULE = "tools.mido_vm_physmap_complete_plan"


class CompletePhysmapPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", Path(__file__).resolve().parents[1] /
                                   "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"))
        if not path.exists():
            raise unittest.SkipTest("Pinned native-4K kernel unavailable")
        cls.kernel = path.read_bytes()
        cls.symbols = macho_symbols(cls.kernel)
        cls.segments = inspect(cls.kernel)["segments"]

    def offset(self, caller, displacement):
        address = self.symbols[caller] + displacement
        segment = next(segment for segment in self.segments
                       if segment["vmaddr"] <= address < segment["vmaddr"] + segment["filesize"])
        return segment["fileoff"] + address - segment["vmaddr"]

    def test_exact_checkpoints_and_baseline_composition(self):
        expected = {
            "vm-physmap-handoff-request": 0x1358,
            "vm-physmap-handoff-mapped": 0x135c,
            "vm-physmap-rest-request": 0x1384,
            "vm-physmap-rest-mapped": 0x1388,
            "vm-physmap-before-sort": 0x13c0,
            "vm-physmap-sorted": 0x13c4,
            "vm-physmap-before-publish": 0x13d4,
            "vm-physmap-published": 0x13d8,
            "vm-physmap-before-ttbr": 0x13e4,
        }
        self.assertEqual(COMPLETE_PHYSMAP_STAGES, expected)
        with patch(MODULE + ".physmap_plan", wraps=physmap_plan) as baseline:
            result = complete_physmap_plan(self.kernel)
        baseline.assert_called_once_with(self.kernel)
        self.assertEqual(result, {name: 0xfffffff007445650 + displacement
                                  for name, displacement in expected.items()})
        self.assertEqual(tuple(result), tuple(expected))

    def test_identity_is_checked_before_baseline(self):
        mutated = bytearray(self.kernel)
        mutated[-1] ^= 1
        with patch(MODULE + ".physmap_plan") as baseline:
            for kernel in (b"unknown", self.kernel[:-1], mutated):
                with self.subTest(length=len(kernel)):
                    with self.assertRaisesRegex(ValueError, "exact reviewed"):
                        complete_physmap_plan(kernel)
            baseline.assert_not_called()

    def test_baseline_failure_propagates(self):
        with patch(MODULE + ".physmap_plan", side_effect=ValueError("baseline differs")):
            with self.assertRaisesRegex(ValueError, "baseline differs"):
                complete_physmap_plan(self.kernel)

    def test_every_call_requires_bl_and_exact_destination(self):
        sites = (("_arm_vm_init", 0x131c), ("_arm_vm_init", 0x1330),
                 ("_arm_vm_init", 0x1358), ("_arm_vm_init", 0x1384),
                 ("_arm_vm_physmap_slide", 0x108), ("_arm_vm_init", 0x13c0),
                 ("_arm_vm_init", 0x13d4), ("_arm_vm_init", 0x13e4),
                 ("_arm_vm_init", 0x13f4))
        for caller, displacement in sites:
            offset = self.offset(caller, displacement)
            original = struct.unpack_from("<I", self.kernel, offset)[0]
            for word in (original ^ 0x80000000, original ^ 1):
                with self.subTest(caller=caller, displacement=hex(displacement), word=hex(word)):
                    mutated = bytearray(self.kernel)
                    struct.pack_into("<I", mutated, offset, word)
                    with patch(MODULE + ".KERNEL_SHA256", hashlib.sha256(mutated).hexdigest()):
                        with patch(MODULE + ".physmap_plan"):
                            with self.assertRaisesRegex(ValueError, "complete physmap BL differs"):
                                complete_physmap_plan(mutated)

    def test_generic_qsort_and_swapped_ttbr_setters_are_rejected(self):
        for displacement, callee in ((0x13c0, "_qsort"),
                                      (0x13e4, "_set_mmu_ttb"),
                                      (0x13f4, "_set_mmu_ttb_alternate")):
            with self.subTest(displacement=hex(displacement), callee=callee):
                address = self.symbols["_arm_vm_init"] + displacement
                immediate = (self.symbols[callee] - address) // 4
                mutated = bytearray(self.kernel)
                struct.pack_into("<I", mutated, self.offset("_arm_vm_init", displacement),
                                 0x94000000 | (immediate & 0x3ffffff))
                with patch(MODULE + ".KERNEL_SHA256", hashlib.sha256(mutated).hexdigest()):
                    with patch(MODULE + ".physmap_plan"):
                        with self.assertRaisesRegex(ValueError, "complete physmap BL differs"):
                            complete_physmap_plan(mutated)


if __name__ == "__main__":
    unittest.main()
