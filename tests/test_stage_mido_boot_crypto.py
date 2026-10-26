from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.check_xnu_build import check
from tools.stage_mido_boot_crypto import stage_boot_crypto


class BootstrapCryptoTests(unittest.TestCase):
    def populate(self, root):
        source, workspace = root / "source", root / "workspace"
        for relative in ("osfmk/conf/files", "osfmk/conf/Makefile.arm64"):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"original\n")
        (source / "osfmk/kern").mkdir()
        for relative in ("devices/mido/xnu/runtime/mido_boot_crypto.c",
                         "devices/mido/xnu/early/drbg.c", "devices/mido/xnu/early/drbg.h",
                         "devices/mido/xnu/runtime/mido_digest.h", "artifacts/bearssl-0.6/inc/bearssl.h",
                         "devices/mido/xnu/runtime/mido_kernel_limits.h",
                         "artifacts/bearssl-0.6/src/inner.h", "artifacts/bearssl-0.6/src/config.h",
                         "artifacts/bearssl-0.6/LICENSE.txt"):
            path = workspace / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(relative.encode())
        return source, workspace

    def test_stages_unique_units_and_per_file_diagnostic_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            source, workspace = self.populate(Path(directory))
            units = {"drbg.c": "devices/mido/xnu/early/drbg.c"}
            with patch("tools.stage_mido_boot_crypto.UNIT_PATHS", units), \
                    patch("tools.stage_mido_boot_crypto.verify_dependency") as verify:
                report = stage_boot_crypto(source, workspace)
            verify.assert_called_once()
            manifest = (source / "osfmk/conf/files").read_text()
            self.assertIn("mido_crypto_drbg.c optional mido_runtime", manifest)
            self.assertIn("mido_crypto_mido_boot_crypto.c optional mido_runtime", manifest)
            self.assertEqual(report["units"], 2)
            self.assertTrue(report["diagnostic_only"])
            self.assertFalse(report["complete_crypto_provider"])
            self.assertFalse(report["provider_registration_executed"])
            self.assertEqual(report["unsupported_operation_policy"], "panic")
            flags = (source / "osfmk/conf/Makefile.arm64").read_text()
            self.assertIn("mido_crypto_drbg.o_CFLAGS_ADD += -DMIDO_BOOT_CRYPTO_DIAGNOSTIC=1", flags)
            self.assertNotIn("\nCFLAGS +=", flags)
            target = source / "osfmk/kern/mido_crypto"
            self.assertTrue((target / "LICENSE.txt").is_file())
            self.assertTrue((target / "inner.h").is_file())
            self.assertEqual((target / "limits.h").read_bytes(),
                             (workspace / "devices/mido/xnu/runtime/mido_kernel_limits.h").read_bytes())
            with patch("tools.stage_mido_boot_crypto.verify_dependency"), \
                    self.assertRaisesRegex(ValueError, "replace"):
                stage_boot_crypto(source, workspace)

    def test_unverified_dependency_does_not_modify_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source, workspace = self.populate(Path(directory))
            with patch("tools.stage_mido_boot_crypto.verify_dependency", side_effect=ValueError("unverified")), \
                    self.assertRaisesRegex(ValueError, "unverified"):
                stage_boot_crypto(source, workspace)
            self.assertEqual((source / "osfmk/conf/files").read_bytes(), b"original\n")
            self.assertFalse((source / "osfmk/kern/mido_crypto").exists())

    def test_missing_input_does_not_partially_modify_graph(self):
        with tempfile.TemporaryDirectory() as directory:
            source, workspace = self.populate(Path(directory))
            units = {"missing.c": "devices/mido/xnu/early/missing.c"}
            with patch("tools.stage_mido_boot_crypto.UNIT_PATHS", units), \
                    patch("tools.stage_mido_boot_crypto.verify_dependency"), self.assertRaises(OSError):
                stage_boot_crypto(source, workspace)
            self.assertEqual((source / "osfmk/conf/files").read_bytes(), b"original\n")
            self.assertFalse((source / "osfmk/kern/mido_crypto").exists())

    def test_diagnostic_provider_cannot_be_selected_for_header_only_or_macos_build(self):
        for sdk, attempt in (("iphoneos", False), ("macosx", True)):
            with self.subTest(sdk=sdk), patch("tools.check_xnu_build.setup") as setup, \
                    self.assertRaisesRegex(ValueError, "explicit iphoneos"):
                check(Path("unused"), sdk, attempt_kernel=attempt, experimental_boot_crypto=True)
            setup.assert_not_called()

    def test_unsupported_entry_points_never_return_success(self):
        text = Path("devices/mido/xnu/runtime/mido_boot_crypto.c").read_text()
        self.assertIn('panic("MIDO diagnostic crypto: unsupported " #name)', text)
        self.assertIn("#error MIDO boot crypto requires explicit diagnostic-only opt-in", text)
        self.assertIn("STARTUP(EARLY_BOOT, STARTUP_RANK_FIRST, mido_boot_crypto_startup)", text)
        self.assertLess(text.index("register_crypto_functions(&boot_functions)"),
                        text.index("mido_kernel_prng_install_native();"))
        self.assertNotIn("return 0", text)
        self.assertNotIn("return true", text)


if __name__ == "__main__":
    unittest.main()
