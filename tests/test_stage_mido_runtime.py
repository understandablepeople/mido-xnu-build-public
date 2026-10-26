import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.stage_mido_runtime import REPLACEMENTS, RUNTIME_NAMES, SOURCE_HASHES, stage_runtime


def populate(source):
    contents = {"osfmk/conf/files": b"osfmk/kern/priority.c standard\n"}
    contents.update({relative: b"\n".join(before for before, after in pairs)
                     for relative, pairs in REPLACEMENTS.items()})
    for relative, data in contents.items():
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    (source / "osfmk/kern").mkdir(parents=True)
    return {relative: hashlib.sha256(data).hexdigest() for relative, data in contents.items()}


class MidoRuntimeStagingTests(unittest.TestCase):
    def test_stage_is_mido_only_and_reports_disabled_services(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            hashes = populate(source)
            with patch.dict(SOURCE_HASHES, hashes):
                report = stage_runtime(source)
            manifest = (source / "osfmk/conf/files").read_text()
            for name in RUNTIME_NAMES:
                self.assertIn(f"osfmk/kern/{name} optional mido_runtime", manifest)
                self.assertTrue((source / "osfmk/kern" / name).is_file())
            self.assertFalse(report["firehose_transport_available"])
            self.assertFalse(report["pmu_available"])
            self.assertFalse(report["apple_monitor_available"])
            self.assertFalse(report["boot_approved"])
            self.assertEqual(report["ubsan_policy"], "panic")

    def test_validation_failure_does_not_partially_edit_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            hashes = populate(source)
            path = source / "bsd/kern/subr_log.c"
            path.write_bytes(b"unexpected")
            before = {relative: (source / relative).read_bytes() for relative in SOURCE_HASHES}
            with patch.dict(SOURCE_HASHES, hashes), self.assertRaisesRegex(ValueError, "unexpected"):
                stage_runtime(source)
            for relative, data in before.items():
                self.assertEqual((source / relative).read_bytes(), data)
            self.assertFalse((source / "osfmk/kern/mido_runtime.c").exists())

    def test_existing_runtime_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            hashes = populate(source)
            path = source / "osfmk/kern/mido_runtime.c"
            path.write_bytes(b"existing runtime")
            with patch.dict(SOURCE_HASHES, hashes), self.assertRaisesRegex(ValueError, "replace"):
                stage_runtime(source)
            self.assertEqual(path.read_bytes(), b"existing runtime")

    def test_logging_device_rejects_requests_without_buffer_mapping(self):
        for original, updated in REPLACEMENTS["bsd/kern/subr_log.c"]:
            self.assertIn(b"#if defined(ARM64_BOARD_CONFIG_MIDO)\n\treturn ENOTSUP;\n#endif", updated)
            self.assertTrue(updated.startswith(original))

    def test_log_disable_is_set_before_and_during_initialization(self):
        for original, updated in REPLACEMENTS["libkern/os/log.c"]:
            self.assertIn(b"#if defined(ARM64_BOARD_CONFIG_MIDO)", updated)
            self.assertIn(b"oslog_disabled = true;", updated)
            self.assertIn(original, updated)


if __name__ == "__main__":
    unittest.main()
