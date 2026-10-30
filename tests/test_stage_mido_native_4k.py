import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import stage_mido_native_4k as native


class Native4KStagingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.unit = self.source / "osfmk/arm/arm_init.c"
        self.unit.parent.mkdir(parents=True)
        self.unit.write_bytes(b"old page policy\n")
        self.flags = self.source / native.FLAGS
        self.flags.parent.mkdir(parents=True)
        self.flags.write_bytes(b"MACHINE_FLAGS_ARM64_MIDO = -DARM64_BOARD_CONFIG_MIDO\n")
        self.candidate = self.root / "candidate.patch"
        self.candidate.write_bytes(
            b"diff --git a/osfmk/arm/arm_init.c b/osfmk/arm/arm_init.c\n"
            b"--- a/osfmk/arm/arm_init.c\n+++ b/osfmk/arm/arm_init.c\n"
            b"@@ -1 +1 @@\n-old page policy\n+new page policy\n")
        self.hashes = {"osfmk/arm/arm_init.c": hashlib.sha256(self.unit.read_bytes()).hexdigest()}
        self.addCleanup(patch.stopall)
        patch.object(native, "SOURCE_HASHES", self.hashes).start()
        patch.object(native, "PATCH", self.candidate).start()
        patch.object(native, "PATCH_SHA256", hashlib.sha256(self.candidate.read_bytes()).hexdigest()).start()

    def test_applies_reviewed_patch_and_enables_only_mido(self):
        report = native.stage_native_4k(self.source)
        self.assertEqual(self.unit.read_bytes(), b"new page policy\n")
        self.assertIn(b"MACHINE_FLAGS_ARM64_MIDO += -DMIDO_NATIVE_4K_USER_ABI=1", self.flags.read_bytes())
        self.assertFalse(report["boot_approved"])
        self.assertFalse(report["signature_subpage_support_verified"])
        self.assertEqual(len(report["files"]), 2)

    def test_unknown_source_does_not_modify_flags(self):
        self.unit.write_bytes(b"unreviewed policy\n")
        original = self.flags.read_bytes()
        with self.assertRaisesRegex(ValueError, "unreviewed"):
            native.stage_native_4k(self.source)
        self.assertEqual(self.flags.read_bytes(), original)

    def test_invalid_patch_does_not_modify_any_source(self):
        original = self.unit.read_bytes(), self.flags.read_bytes()
        self.candidate.write_bytes(b"invalid patch\n")
        native.PATCH_SHA256 = hashlib.sha256(self.candidate.read_bytes()).hexdigest()
        with self.assertRaisesRegex(ValueError, "preflight"):
            native.stage_native_4k(self.source)
        self.assertEqual((self.unit.read_bytes(), self.flags.read_bytes()), original)

    def test_non_mido_flags_are_rejected(self):
        self.flags.write_bytes(b"MACHINE_FLAGS_ARM64_OTHER = -DOTHER\n")
        with self.assertRaisesRegex(ValueError, "MIDO machine flags"):
            native.stage_native_4k(self.source)
        self.assertEqual(self.unit.read_bytes(), b"old page policy\n")

    def test_unreviewed_patch_is_rejected(self):
        self.candidate.write_bytes(b"changed patch\n")
        with self.assertRaisesRegex(ValueError, "unreviewed native 4K patch"):
            native.stage_native_4k(self.source)
        self.assertEqual(self.unit.read_bytes(), b"old page policy\n")

    def test_repeated_activation_is_rejected(self):
        self.flags.write_bytes(self.flags.read_bytes() + b"MIDO_NATIVE_4K_USER_ABI\n")
        with self.assertRaisesRegex(ValueError, "already staged"):
            native.stage_native_4k(self.source)


if __name__ == "__main__":
    unittest.main()
