from pathlib import Path
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch

from tools.backport_iig_output import backport, install_hook


class BackportOutputTests(unittest.TestCase):
    def workspace_directory(self):
        artifacts = Path(__file__).resolve().parent.parent / "artifacts"
        artifacts.mkdir(exist_ok=True)
        return tempfile.TemporaryDirectory(dir=artifacts)

    def test_external_build_roots_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "isolated artifact"):
                backport(root / "output.cpp", root / "header.h", root)

    def test_unreviewed_bytes_do_not_modify_generated_output(self):
        with self.workspace_directory() as temporary:
            root = Path(temporary)
            target = root / "DEVELOPMENT_ARM64_MIDO/iokit/DriverKit/OSObject.iig.cpp"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"unreviewed generator output")
            header = root / "IORPC.h"
            header.write_bytes(b"unreviewed header")
            with self.assertRaisesRegex(ValueError, "unreviewed"):
                backport(target, header, root)
            self.assertEqual(target.read_bytes(), b"unreviewed generator output")
            self.assertEqual(list(target.parent.glob('.reviewed-rpc-*')), [])

    def test_only_reviewed_output_locations_can_be_replaced(self):
        with self.workspace_directory() as temporary:
            root = Path(temporary)
            target = root / "OSObject.iig.cpp"
            target.write_bytes(b"must stay unchanged")
            with self.assertRaisesRegex(ValueError, "output location"):
                backport(target, root / "IORPC.h", root)
            self.assertEqual(target.read_bytes(), b"must stay unchanged")

    def test_successful_adaptation_appends_checks_and_replaces_only_target(self):
        with self.workspace_directory() as temporary:
            root = Path(temporary)
            target = root / "DEVELOPMENT_ARM64_MIDO/iokit/DEVELOPMENT/DriverKit/OSObject.iig.cpp"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"fixture generator output")
            header = root / "IORPC.h"
            header.write_bytes(b"fixture header")
            with patch('tools.backport_iig_output.legacy_candidate', return_value=(b"} Fake_Call_Invocation;", {})):
                report = backport(target, header, root)
            self.assertEqual(report['invocation_unions_checked'], 1)
            self.assertIn(b"RPC overlay size", target.read_bytes())
            self.assertEqual(header.read_bytes(), b"fixture header")
            self.assertEqual(list(target.parent.glob('.reviewed-rpc-*')), [])

    def test_temporary_fallback_retains_source_in_a_diagnostic_report(self):
        with self.workspace_directory() as temporary:
            root = Path(temporary)
            target = root / "DEVELOPMENT_ARM64_MIDO/iokit/DriverKit/IOBufferMemoryDescriptor.iig.cpp"
            target.parent.mkdir(parents=True)
            fixture = Path(__file__).parent / "fixtures/IOBufferMemoryDescriptor-driverkit-286.iig.cpp"
            source = fixture.read_bytes().replace(b"\r\n", b"\n") + b"\n// diagnostic variant\n"
            target.write_bytes(source)
            header = root / "IORPC.h"
            header.write_bytes(b"header")
            with patch("tools.prepare_iig_legacy_probe.IORPC_SHA256", hashlib.sha256(b"header").hexdigest()), contextlib.redirect_stderr(io.StringIO()):
                report = backport(target, header, root)
            saved = json.loads(Path(report["unreviewed_source_report"]).read_text())
            self.assertEqual(saved["implementation"], source.decode())
            self.assertFalse(saved["hash_reviewed"])
            self.assertTrue(target.read_bytes().startswith(source))
            self.assertEqual(target.read_bytes().count(b"RPC overlay field"), 8)
            self.assertEqual(header.read_bytes(), b"header")

    def test_unreviewed_generation_recipe_is_not_modified(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            target = source / 'iokit/DriverKit/Makefile'
            target.parent.mkdir(parents=True)
            target.write_bytes(b"unreviewed make rules")
            with self.assertRaisesRegex(ValueError, "generation Makefile"):
                install_hook(source)
            self.assertEqual(target.read_bytes(), b"unreviewed make rules")


if __name__ == '__main__':
    unittest.main()
