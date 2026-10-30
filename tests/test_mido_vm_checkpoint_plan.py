import os
from pathlib import Path
import unittest

from tools.mido_vm_checkpoint_plan import CHECKPOINTS, plan


class VMCheckpointPlanTests(unittest.TestCase):
    def test_unknown_kernel_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact reviewed"):
            plan(b"unknown")

    @unittest.skipUnless(os.environ.get("MIDO_NATIVE4K_KERNEL"), "Supply the pinned cloud kernel")
    def test_actual_calls_and_return_checkpoints(self):
        checkpoints = plan(Path(os.environ["MIDO_NATIVE4K_KERNEL"]).read_bytes())
        self.assertEqual(tuple(checkpoints), CHECKPOINTS)
        self.assertEqual(checkpoints["vm-geometry"], 0xfffffff007445734)
        self.assertEqual(checkpoints["vm-entropy-return"], checkpoints["vm-geometry"] + 4)
        self.assertEqual(checkpoints["vm-first-clear"], 0xfffffff007445858)
        self.assertEqual(checkpoints["vm-first-clear-return"], checkpoints["vm-first-clear"] + 4)
