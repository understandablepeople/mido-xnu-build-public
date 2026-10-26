import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.check_xnu_build import check
from tools.stage_mido_memory_root import (BLOCK_LOOKUP, GUARD, MEDIA_ASSERT, MEDIA_CONTEXT,
                                         adapt_service, stage_memory_root)


class MemoryRootTests(unittest.TestCase):
    def fixture(self):
        return (b"void setRootMedia(IOService *root) {\n" + BLOCK_LOOKUP
                + b"\twhile (root) { root = root->getProvider(); }\n"
                + b"\tLOCKWRITENOTIFY();\n\tgIOServiceRootMediaParent = root;\n\tUNLOCKNOTIFY();\n"
                + b"\tpublishHiddenMedia(root);\n}\nvoid publishHiddenMedia(IOService *parent) {\n"
                + b"\tiomediaClass = lookup();\n" + MEDIA_ASSERT
                + b"\tLOCKWRITENOTIFY();\n\tif (wasHiding && !parent) gIOServiceHideIOMedia = false;\n"
                + b"\tUNLOCKNOTIFY();\n" + MEDIA_CONTEXT
                + b"\tif (wasHiding) iomediaClass->applyToInstances(applier, &ctx);\n}\n")

    def test_only_null_root_can_omit_storage_family_and_lifecycle_stays(self):
        before = self.fixture()
        with patch("tools.stage_mido_memory_root.SOURCE_SHA256", hashlib.sha256(before).hexdigest()):
            after = adapt_service(before)
        self.assertIn(GUARD + b"\tif (root) {\n#endif\n" + BLOCK_LOOKUP, after)
        self.assertIn(b"assert(iomediaClass || !parent)", after)
        self.assertIn(b"#else\n" + MEDIA_ASSERT, after)
        self.assertEqual(after.count(b"gIOServiceRootMediaParent = root;"), 1)
        self.assertEqual(after.count(b"gIOServiceHideIOMedia = false;"), 1)
        start = after.index(b"void publishHiddenMedia")
        self.assertLess(after.index(b"UNLOCKNOTIFY();", start), after.index(b"if (!iomediaClass)"))
        self.assertLess(after.index(b"if (!iomediaClass)"), after.index(MEDIA_CONTEXT))
        self.assertIn(b"if (wasHiding) iomediaClass->applyToInstances", after)

    def test_unreviewed_source_rejected(self):
        with self.assertRaisesRegex(ValueError, "unexpected prepared IOService"):
            adapt_service(self.fixture())

    def test_duplicate_anchor_rejected(self):
        before = self.fixture() + MEDIA_ASSERT
        with patch("tools.stage_mido_memory_root.SOURCE_SHA256", hashlib.sha256(before).hexdigest()), \
                self.assertRaisesRegex(ValueError, "ambiguous"):
            adapt_service(before)

    def test_stages_only_scoped_compiler_flag_and_preserves_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = root / "iokit/Kernel/IOService.cpp"
            service.parent.mkdir(parents=True)
            service.write_bytes(self.fixture())
            makefile = root / "iokit/conf/Makefile.arm64"
            makefile.parent.mkdir()
            makefile.write_bytes(b"original rules\n")
            config = root / "config/MASTER.arm64.MIDO"
            config.parent.mkdir()
            config.write_bytes(b"pseudo-device mido_runtime\n")
            with patch("tools.stage_mido_memory_root.SOURCE_SHA256", hashlib.sha256(service.read_bytes()).hexdigest()):
                report = stage_memory_root(root)
            self.assertEqual(config.read_bytes(), b"pseudo-device mido_runtime\n")
            self.assertEqual(makefile.read_bytes(), b"original rules\n\nIOService.cpo_CFLAGS_ADD += -DMIDO_DIAGNOSTIC_MEMORY_ROOT=1\n")
            self.assertFalse(report["boot_approved"])
            self.assertFalse(report["storage_driver_implemented"])
            self.assertFalse(report["filesystem_implemented"])
            with self.assertRaisesRegex(ValueError, "already staged"):
                stage_memory_root(root)

    def test_requires_explicit_platform_before_setup(self):
        with patch("tools.check_xnu_build.setup") as setup, \
                self.assertRaisesRegex(ValueError, "explicit diagnostic platform"):
            check(Path("unused"), "iphoneos", attempt_kernel=True, experimental_memory_root=True)
        setup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
