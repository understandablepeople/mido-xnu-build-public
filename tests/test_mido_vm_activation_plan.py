import hashlib
import os
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols
from tools.mido_vm_activation_plan import activation_plan, CALLER, SETTERS
from tools.mido_vm_physmap_complete_plan import complete_physmap_plan


MODULE = "tools.mido_vm_activation_plan"


class ActivationPlanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", Path(__file__).resolve().parents[1] /
                                   "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"))
        if not path.exists():
            raise unittest.SkipTest("Pinned native-4K kernel unavailable")
        cls.kernel = path.read_bytes()
        cls.symbols = macho_symbols(cls.kernel)
        cls.segments = inspect(cls.kernel)["segments"]

    def offset(self, address):
        segment = next(segment for segment in self.segments
                       if segment["vmaddr"] <= address < segment["vmaddr"] + segment["filesize"])
        return segment["fileoff"] + address - segment["vmaddr"]

    def test_precise_control_flow_and_stop(self):
        with patch(MODULE + ".complete_physmap_plan", wraps=complete_physmap_plan) as baseline:
            result = activation_plan(self.kernel)
        baseline.assert_called_once_with(self.kernel)
        self.assertEqual(result["entry"], 0xfffffff007446a34)
        self.assertEqual(result["stages"], {
            "vm-before-ttbr1": 0xfffffff007446a34,
            "vm-ttbr1-return": 0xfffffff007446a38,
            "vm-before-ttbr0": 0xfffffff007446a44,
            "vm-ttbr0-return": 0xfffffff007446a48,
            "vm-after-activation-sync": 0xfffffff007446a54,
        })
        self.assertEqual(result["caller_sync"], [0xfffffff007446a48, 0xfffffff007446a4c, 0xfffffff007446a50])
        self.assertEqual(result["stop"]["address"], 0xfffffff007446a54)
        self.assertTrue(result["stop"]["exclusive"])
        self.assertEqual(result["next_bounded_work"]["call"], 0xfffffff007446a60)
        self.assertEqual(result["next_bounded_work"]["target"], 0xfffffff007443ed0)
        self.assertFalse(result["next_bounded_work"]["followed"])
        self.assertTrue(result["offline_only"])
        self.assertFalse(result["boot_approved"])
        self.assertEqual(len(result["caller"]), 11)

    def test_setter_bodies_roots_and_returns(self):
        result = activation_plan(self.kernel)
        for call, target, slot, register, barrier in zip(
                result["calls"], (0xfffffff00722d838, 0xfffffff00722d848),
                (0xfffffff007162010, 0xfffffff007162008),
                ("TTBR1_EL1", "TTBR0_EL1"), ("dsb sy", "dsb ish")):
            self.assertEqual(call["target"], target)
            self.assertEqual(call["return_instruction"], target + 12)
            self.assertEqual(call["return_site"], call["call"] + 4)
            self.assertEqual(call["root_slot"], slot)
            self.assertEqual(call["register"], register)
            self.assertEqual(call["argument"], "load64(root_slot) & 0x0000ffffffffffff")
            self.assertIsNone(call["runtime_root_value"])
            body = result["setter_bodies"][call["symbol"]]
            self.assertEqual([row["assembly"] for row in body],
                             [barrier, f"msr {register}, x0", "isb", "ret"])
            self.assertEqual([row["address"] for row in body], [target + offset for offset in (0, 4, 8, 12)])
        for row in result["caller"] + result["next_bounded_work"]["instructions"]:
            self.assertEqual(bytes.fromhex(row["bytes"]), self.kernel[row["file_offset"]:row["file_offset"] + 4])

    def test_unknown_kernel_rejected_before_baseline(self):
        mutated = bytearray(self.kernel)
        mutated[-1] ^= 1
        with patch(MODULE + ".complete_physmap_plan") as baseline:
            for kernel in (b"unknown", self.kernel[:-1], mutated):
                with self.assertRaisesRegex(ValueError, "exact reviewed"):
                    activation_plan(kernel)
            baseline.assert_not_called()

    def test_every_instruction_rejects_mutation_even_with_rebased_hash(self):
        for owner, listing in {"_arm_vm_init": CALLER, **SETTERS}.items():
            for displacement, word, _ in listing:
                with self.subTest(owner=owner, displacement=hex(displacement)):
                    mutated = bytearray(self.kernel)
                    struct.pack_into("<I", mutated, self.offset(self.symbols[owner] + displacement), word ^ 1)
                    with patch(MODULE + ".KERNEL_SHA256", hashlib.sha256(mutated).hexdigest()):
                        with patch(MODULE + ".complete_physmap_plan", return_value={
                                "vm-physmap-before-ttbr": self.symbols["_arm_vm_init"] + 0x13e4}):
                            with self.assertRaisesRegex(ValueError, "activation bytes differ"):
                                activation_plan(mutated)

    def test_baseline_failure_propagates(self):
        with patch(MODULE + ".complete_physmap_plan", side_effect=ValueError("baseline differs")):
            with self.assertRaisesRegex(ValueError, "baseline differs"):
                activation_plan(self.kernel)

    def test_changed_symbols_and_boundary_rejected(self):
        symbols = dict(self.symbols, _cpu_ttep=self.symbols["_invalid_ttep"])
        with patch(MODULE + ".macho_symbols", return_value=symbols):
            with self.assertRaisesRegex(ValueError, "symbols differ"):
                activation_plan(self.kernel)
        with patch(MODULE + ".complete_physmap_plan", return_value={"vm-physmap-before-ttbr": 0}):
            with self.assertRaisesRegex(ValueError, "boundary differs"):
                activation_plan(self.kernel)

    def test_invalid_instruction_backing_rejected(self):
        for segments, message in (([], "unique file backing"),
                                  (self.segments + self.segments, "unique file backing"),
                                  ([dict(segment, fileoff=len(self.kernel)) for segment in self.segments],
                                   "kernel bounds")):
            with self.subTest(message=message):
                with patch(MODULE + ".inspect", return_value={"segments": segments}):
                    with self.assertRaisesRegex(ValueError, message):
                        activation_plan(self.kernel)


if __name__ == "__main__":
    unittest.main()
