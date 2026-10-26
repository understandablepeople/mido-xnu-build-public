from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.capture_mido_recovery import capture, READS


class RecoveryCaptureTests(unittest.TestCase):
    def runner(self, argv, **kwargs):
        self.commands.append(argv)
        stdout = b"List of devices attached\nexample recovery\n" if argv[-1] == "devices" else b"mido\n"
        return subprocess.CompletedProcess(argv, 0, stdout, b"")

    def setUp(self):
        self.commands = []

    def test_refuses_existing_or_external_output_before_device_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            existing = workspace / "artifacts/existing"
            existing.mkdir(parents=True)
            for output in (existing, workspace, workspace / "artifacts"):
                with self.assertRaises(ValueError):
                    capture(Path("adb"), "example", output, workspace, self.runner)
            self.assertFalse(self.commands)

    def test_requires_exact_recovery_device_before_any_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            with self.assertRaisesRegex(ValueError, "recovery"):
                capture(Path("adb"), "different", workspace / "artifacts/new", workspace, self.runner)
            self.assertEqual(len(self.commands), 1)
            self.assertFalse((workspace / "artifacts/new").exists())

    def test_only_fixed_reads_and_exact_device_are_executed(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            result = capture(Path("adb"), "example", workspace / "artifacts/new", workspace, self.runner)
            self.assertEqual(len(self.commands), 2 + len(READS))
            self.assertEqual([command[-1] for command in self.commands[2:]], list(READS.values()))
            self.assertTrue(all(command[1:4] == ["-s", "example", "exec-out"] for command in self.commands[2:]))
            self.assertTrue(result["all_reads_succeeded"])
            self.assertNotIn("example", str(result))
            self.assertFalse(result["files"]["live.dtb"]["header_valid"])

    def test_wrong_product_is_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            def runner(argv, **kwargs):
                reply = self.runner(argv, **kwargs)
                if argv[-1] == "getprop ro.product.device":
                    reply.stdout = b"other-device\n"
                return reply
            with self.assertRaisesRegex(ValueError, "non-MIDO"):
                capture(Path("adb"), "example", workspace / "artifacts/new", workspace, runner)
            self.assertFalse((workspace / "artifacts/new").exists())
