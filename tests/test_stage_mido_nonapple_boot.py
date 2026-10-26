import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.check_xnu_build import check
from tools.stage_mido_nonapple_boot import ANCHOR, REPLACEMENT, stage_nonapple_boot


class NonAppleBootTests(unittest.TestCase):
    def populate(self, root):
        startup = root / "osfmk/kern/startup.c"
        startup.parent.mkdir(parents=True)
        data = b'original\n' + ANCHOR + b'\n\ttrust_cache_runtime_init();\n\tload_static_trust_cache();\n#endif\n'
        startup.write_bytes(data)
        config = root / "config/MASTER.arm64.MIDO"
        config.parent.mkdir()
        config.write_bytes(b"MIDO configuration without proprietary runtime\n")
        return startup, config, data

    def test_only_extends_upstream_platform_gate_without_replacing_security_apis(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            startup, config, data = self.populate(root)
            with patch("tools.stage_mido_nonapple_boot.STARTUP_SHA256", hashlib.sha256(data).hexdigest()):
                report = stage_nonapple_boot(root)
            self.assertEqual(startup.read_bytes(), data.replace(ANCHOR, REPLACEMENT))
            self.assertEqual(config.read_bytes(), b"MIDO configuration without proprietary runtime\n")
            self.assertFalse(report["trust_cache_api_implementations_modified"])
            self.assertFalse(report["code_signature_api_implementations_modified"])
            self.assertFalse(report["image4_backend_available"])

    def test_image4_enabled_configuration_is_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            startup, config, data = self.populate(root)
            config.write_bytes(b"# MIDO_BASE = [ config_img4 ]\n")
            with patch("tools.stage_mido_nonapple_boot.STARTUP_SHA256", hashlib.sha256(data).hexdigest()), \
                    self.assertRaisesRegex(ValueError, "requests Image4"):
                stage_nonapple_boot(root)
            self.assertEqual(startup.read_bytes(), data)

    def test_unreviewed_startup_is_rejected_before_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            startup, config, data = self.populate(root)
            with self.assertRaisesRegex(ValueError, "unexpected original"):
                stage_nonapple_boot(root)
            self.assertEqual(startup.read_bytes(), data)

    def test_normal_build_cannot_silently_select_nonapple_startup(self):
        with patch("tools.check_xnu_build.setup") as setup, self.assertRaisesRegex(ValueError, "explicit experimental"):
            check(Path("unused"), "iphoneos", attempt_kernel=True, mido_no_image4_boot=True)
        setup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
