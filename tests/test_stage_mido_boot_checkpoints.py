import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.check_xnu_build import check
from tools.stage_mido_boot_checkpoints import ARGS, ENTRY, MACRO, stage_boot_checkpoints


class BootCheckpointStagingTests(unittest.TestCase):
    def populate(self, root):
        source, workspace = root / "source", root / "workspace"
        startup = source / "osfmk/arm64/start.s"
        startup.parent.mkdir(parents=True)
        before = b"prefix\n" + ENTRY + b"original instructions\n" + ARGS + b"suffix\n"
        startup.write_bytes(before)
        config = source / "config/MASTER.arm64.MIDO"
        config.parent.mkdir()
        config.write_text("MIDO\n")
        macro = workspace / MACRO
        macro.parent.mkdir(parents=True)
        macro.write_text(".macro MIDO_EARLY_MARK row\n.endmacro\n")
        return source, workspace, startup, before

    def test_opt_in_preserves_original_instructions(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, workspace, startup, before = self.populate(Path(temporary))
            with patch("tools.stage_mido_boot_checkpoints.START_SHA256", hashlib.sha256(before).hexdigest()):
                result = stage_boot_checkpoints(source, workspace)
            after = startup.read_bytes()
            self.assertIn(ENTRY, after)
            self.assertIn(ARGS, after)
            self.assertIn(b"original instructions\n", after)
            self.assertLess(after.index(b"MIDO_EARLY_MARK 560"), after.index(ARGS))
            self.assertGreater(after.index(b"MIDO_EARLY_MARK 584"), after.index(ARGS))
            self.assertEqual(after.count(b"#if defined(MIDO)"), 3)
            self.assertFalse(result["boot_approved"])
            self.assertFalse(result["original_startup_instructions_removed"])
            with self.assertRaisesRegex(ValueError, "unexpected prepared"):
                stage_boot_checkpoints(source, workspace)

    def test_hash_mismatch_leaves_source_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, workspace, startup, before = self.populate(Path(temporary))
            with self.assertRaisesRegex(ValueError, "unexpected prepared"):
                stage_boot_checkpoints(source, workspace)
            self.assertEqual(startup.read_bytes(), before)

    def test_warm_boot_argument_load_is_not_instrumented(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, workspace, startup, before = self.populate(Path(temporary))
            before = ARGS + before
            startup.write_bytes(before)
            with patch("tools.stage_mido_boot_checkpoints.START_SHA256", hashlib.sha256(before).hexdigest()):
                stage_boot_checkpoints(source, workspace)
            after = startup.read_bytes()
            self.assertTrue(after.startswith(ARGS))
            self.assertEqual(after.count(b"MIDO_EARLY_MARK 584"), 1)
            self.assertGreater(after.index(b"MIDO_EARLY_MARK 584"), after.index(ENTRY))

    def test_missing_macro_does_not_write_startup(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, workspace, startup, before = self.populate(Path(temporary))
            (workspace / MACRO).unlink()
            with patch("tools.stage_mido_boot_checkpoints.START_SHA256", hashlib.sha256(before).hexdigest()):
                with self.assertRaises(OSError):
                    stage_boot_checkpoints(source, workspace)
            self.assertEqual(startup.read_bytes(), before)

    def test_ambiguous_anchor_does_not_write_startup(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, workspace, startup, before = self.populate(Path(temporary))
            before += ENTRY
            startup.write_bytes(before)
            with patch("tools.stage_mido_boot_checkpoints.START_SHA256", hashlib.sha256(before).hexdigest()):
                with self.assertRaisesRegex(ValueError, "ambiguous"):
                    stage_boot_checkpoints(source, workspace)
            self.assertEqual(startup.read_bytes(), before)

    def test_ordinary_build_cannot_enable_checkpoints(self):
        with self.assertRaisesRegex(ValueError, "explicit bootstrap"):
            check(Path("unused"), "iphoneos", experimental_boot_checkpoints=True)


if __name__ == "__main__":
    unittest.main()
