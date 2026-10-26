from pathlib import Path
import tempfile
import unittest

from tools.check_xnu_build import check
from tools.stage_mido_irq_timer import stage_irq_timer, UNITS


class IrqTimerStagingTests(unittest.TestCase):
    def populate(self, root):
        source, workspace = root / "source", root / "workspace"
        (source / "osfmk/kern").mkdir(parents=True)
        (source / "osfmk/conf").mkdir()
        for name in ("files", "Makefile.arm64"):
            (source / "osfmk/conf" / name).write_text("original\n")
        for relative in UNITS.values():
            path = workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(relative)
        return source, workspace

    def test_unique_objects_and_explicit_per_file_opt_in(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, workspace = self.populate(Path(temporary))
            report = stage_irq_timer(source, workspace)
            graph = (source / "osfmk/conf/files").read_text()
            flags = (source / "osfmk/conf/Makefile.arm64").read_text()
            for name in ("irq_timer", "arm64_timer", "mido_irq_timer"):
                self.assertIn(f"mido_irq_{name}.c optional mido_runtime", graph)
                self.assertIn(f"mido_irq_{name}.o_CFLAGS_ADD += -DMIDO_IRQ_TIMER_DIAGNOSTIC=1", flags)
            self.assertNotIn("\nCFLAGS +=", flags)
            self.assertFalse(report["hardware_verified"])
            self.assertFalse(report["boot_approved"])
            self.assertEqual(len(report["files"]), 6)
            with self.assertRaisesRegex(ValueError, "replace"):
                stage_irq_timer(source, workspace)

    def test_missing_input_does_not_change_build_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, workspace = self.populate(Path(temporary))
            (workspace / UNITS["irq_timer.c"]).unlink()
            with self.assertRaises(OSError):
                stage_irq_timer(source, workspace)
            self.assertEqual((source / "osfmk/conf/files").read_text(), "original\n")
            self.assertFalse((source / "osfmk/kern/mido_irq").exists())

    def test_duplicate_configuration_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, workspace = self.populate(Path(temporary))
            (source / "osfmk/conf/Makefile.arm64").write_text("mido_irq_duplicate\n")
            with self.assertRaisesRegex(ValueError, "already configured"):
                stage_irq_timer(source, workspace)
            self.assertEqual((source / "osfmk/conf/files").read_text(), "original\n")
            self.assertFalse((source / "osfmk/kern/mido_irq").exists())

    def test_ordinary_build_cannot_enable_irq_diagnostics(self):
        with self.assertRaisesRegex(ValueError, "explicit bootstrap"):
            check(Path("unused"), "iphoneos", experimental_irq_timer=True)


if __name__ == "__main__":
    unittest.main()
