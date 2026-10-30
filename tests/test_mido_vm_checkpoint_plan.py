import os
from pathlib import Path
import unittest

from tools.mido_vm_checkpoint_plan import CHECKPOINTS, TABLE_CHECKPOINTS, plan, table_plan


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
        tables = table_plan(Path(os.environ["MIDO_NATIVE4K_KERNEL"]).read_bytes())
        self.assertEqual(tuple(tables), TABLE_CHECKPOINTS)
        self.assertEqual(tables["vm-second-clear-return"], 0xfffffff0074458c8)
        self.assertEqual(tables["vm-first-l2-return"], 0xfffffff00744595c)
        self.assertEqual(tables["vm-l2-pages-ready"], 0xfffffff0074459b8)
