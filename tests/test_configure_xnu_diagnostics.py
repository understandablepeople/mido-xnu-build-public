import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.configure_xnu_diagnostics import (
    configure_warning_policy, enable_firehose_spi, stage_firehose_header,
    FIREHOSE_HEADER_SHA256, remove_firehose_link_flag,
)
from tools.check_xnu_build import phase_command


class DiagnosticBuildConfigurationTests(unittest.TestCase):
    def test_firehose_archive_flag_is_removed_without_removing_sdk_paths(self):
        data = (b"# LDFLAGS_KERNEL_SDK = -L$(SDKROOT)/usr/local/lib/kernel -lfirehose_kernel\n"
                b"LD_KERNEL_ARCHIVES = $(LDFLAGS_KERNEL_SDK) -lfirehose_kernel\n")
        result = remove_firehose_link_flag(data)
        self.assertNotIn(b"-lfirehose_kernel", result)
        self.assertIn(b"LD_KERNEL_ARCHIVES = $(LDFLAGS_KERNEL_SDK)\n", result)
        self.assertIn(b"-L$(SDKROOT)/usr/local/lib/kernel", result)
        with self.assertRaisesRegex(ValueError, "archive configuration"):
            remove_firehose_link_flag(result)

    def test_warnings_remain_enabled_without_werror(self):
        data = b"WERROR := -Werror\nWARNFLAGS_STD := -Wall " + bytes((92, 10)) + b"\t$(WERROR) " + bytes((92, 10))
        result = configure_warning_policy(data)
        self.assertNotIn(b"-Werror", result)
        self.assertIn(b"-Wall", result)
        self.assertIn(b"-Wno-error=unused-but-set-variable", result)
        self.assertIn(b"-Wno-error=pointer-to-int-cast", result)
        with self.assertRaisesRegex(ValueError, "warning configuration"):
            configure_warning_policy(result)
        with self.assertRaisesRegex(ValueError, "warning configuration"):
            configure_warning_policy(data + data)

    def test_make_commands_override_warning_errors_in_submakes(self):
        for target in ("exporthdrs", "build"):
            command = phase_command(Path("source"), Path("build"), "iphoneos", Path("availability.pl"), target)
            self.assertIn("BUILD_WERROR=0", command)
            self.assertIn("WERROR=", command)
            self.assertEqual(command[-1], target)

    def test_real_header_is_hash_pinned_nonempty_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            report = stage_firehose_header(source)
            target = source / "EXTERNAL_HEADERS/os/firehose_buffer_private.h"
            data = target.read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), FIREHOSE_HEADER_SHA256)
            self.assertIn(b"firehose_buffer", data)
            self.assertFalse(report["empty_stub"])
            with self.assertRaisesRegex(ValueError, "refusing"):
                stage_firehose_header(source)
            self.assertEqual(target.read_bytes(), data)

    def test_tampered_bundled_header_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            with patch("tools.configure_xnu_diagnostics.hashlib.sha256") as digest:
                digest.return_value.hexdigest.return_value = "invalid"
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    stage_firehose_header(source)
            self.assertFalse((source / "EXTERNAL_HEADERS").exists())

    def test_spi_defines_expose_the_genuine_kernel_declarations(self):
        data = b"DEFINES = -DAPPLE -DKERNEL -DKERNEL_PRIVATE -DXNU_KERNEL_PRIVATE other\n"
        result = enable_firehose_spi(data)
        self.assertEqual(result, data.replace(b" other", b" -DOS_FIREHOSE_SPI=1 other"))
        with self.assertRaisesRegex(ValueError, "define layout"):
            enable_firehose_spi(result)


if __name__ == "__main__":
    unittest.main()
