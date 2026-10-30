import os
from pathlib import Path
import struct
import unittest

from tools.inspect_xnu import inspect
from tools.mido_vm_executable_reference import ExecutableReference
from tools.mido_vm_checkpoint_plan import EXECUTABLE_CHECKPOINTS, executable_plan


class ExecutableReferenceTests(unittest.TestCase):
    def kernel(self):
        path = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", Path(__file__).resolve().parents[1] /
                                   "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"))
        if not path.exists():
            self.skipTest("Pinned kernel unavailable")
        return path.read_bytes()

    def reference(self):
        kernel = self.kernel()
        executable_plan(kernel)
        return ExecutableReference(inspect(kernel)["segments"], 0xfffffff007000000, 0x11200000, 0x12401000)

    def test_unknown_kernel_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact reviewed"):
            executable_plan(b"unreviewed")

    def test_boundaries_follow_actual_calls_and_block_store(self):
        checkpoints = executable_plan(self.kernel())
        self.assertEqual(tuple(checkpoints), EXECUTABLE_CHECKPOINTS)
        self.assertEqual(checkpoints["vm-before-executable-block"], 0xfffffff007444f90)
        self.assertEqual(checkpoints["vm-first-executable-block"], 0xfffffff007444f94)
        self.assertEqual(checkpoints["vm-data-mapped"], 0xfffffff007444a10)

    def test_executable_maps_three_readonly_executable_blocks(self):
        reference = self.reference()
        layout, descriptors = reference.state("__TEXT_EXEC")
        self.assertEqual(layout, {0: 0x12404000, 1: 0x12405000, 5: 0x12406000})
        for index in range(3):
            self.assertEqual(descriptors[0x12403000 + (58 + index) * 8],
                             (0x11600000 + index * 0x200000) | 0x0040000000000681)
        self.assertEqual(descriptors[0x124050a0], 0x0040000011414683)
        self.assertEqual(descriptors[0x12405100], 0x0050000011420683)
        self.assertEqual(len(reference.expected("vm-executable-mapped")), 24576)

    def test_data_remains_writable_nonexecutable(self):
        reference = self.reference()
        layout, descriptors = reference.state("__DATA")
        self.assertEqual(layout[6], 0x12407000)
        self.assertEqual(descriptors[0x12406ae0], 0x0060000011d5c603)
        self.assertEqual(descriptors[0x12407000], 0x0070000011e00603)
        self.assertEqual(len(reference.expected("vm-data-mapped")), 28672)

    def test_first_block_checkpoint_does_not_include_future_blocks(self):
        reference = self.reference()
        before = reference.expected("vm-before-executable-block")
        after = reference.expected("vm-first-executable-block")
        self.assertEqual(len(before), 20480)
        self.assertEqual(len(after), 20480)
        self.assertFalse(any(before[8192 + 58 * 8:8192 + 61 * 8]))
        self.assertEqual(struct.unpack_from("<Q", after, 8192 + 58 * 8)[0], 0x0040000011600681)
        self.assertFalse(any(after[8192 + 59 * 8:8192 + 61 * 8]))

    def test_store_site_and_execute_permissions_are_not_interchangeable(self):
        reference = self.reference()
        reference.request = "__TEXT_EXEC"
        helper, granular = 0xfffffff007445090, 0xfffffff007444d90
        address, value = 0x12403000 + 58 * 8, 0x0040000011600681
        self.assertTrue(reference.accepts(address, 8, value, granular + 0x200, helper))
        self.assertFalse(reference.accepts(address, 8, value, helper + 0x210, helper))
        self.assertFalse(reference.accepts(address, 8, value ^ (1 << 53), granular + 0x200, helper))
        self.assertFalse(reference.accepts(address + 8, 8, value, granular + 0x200, helper))
        self.assertFalse(reference.accepts(address, 4, value, granular + 0x200, helper))


if __name__ == "__main__":
    unittest.main()
