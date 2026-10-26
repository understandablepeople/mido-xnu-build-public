from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools.check_xnu_build_graph import check, clean_environment, make_command, run_make


class XnuBuildGraphTests(unittest.TestCase):
    def test_non_macos_is_rejected_before_source_preparation(self):
        with patch("tools.check_xnu_build_graph.sys.platform", "win32"):
            with patch("tools.check_xnu_build_graph.prepare") as prepare:
                with self.assertRaisesRegex(ValueError, "actual macOS"):
                    check(Path("unused"), "iphoneos")
                prepare.assert_not_called()

    def test_target_and_output_paths_are_explicit(self):
        source = Path("isolated/source")
        build = Path("isolated/build")
        command = make_command(source, build, "iphoneos")
        for expected in ("--just-print", "-j1", "TARGET_CONFIGS=DEVELOPMENT ARM64 MIDO", "SDKROOT=iphoneos",
                         f"OBJROOT={build / 'obj'}", f"SYMROOT={build / 'sym'}", f"DSTROOT={build / 'dst'}"):
            self.assertIn(expected, command)
        self.assertEqual(command[-1], "all")
        self.assertNotIn("install", command)

    def test_unknown_sdk_and_shell_injection_rejected(self):
        for sdk in ("iphoneos;exit", "iphoneos.internal", "default"):
            with self.assertRaises(ValueError):
                make_command(Path("source"), Path("build"), sdk)

    def test_credentials_and_inherited_make_state_removed(self):
        original = {"PATH": "tools", "GH_TOKEN": "sensitive", "ACTIONS_RUNTIME_TOKEN": "sensitive",
                    "PASSWORD": "sensitive", "SOME_SECRET": "sensitive", "MAKEFILES": "override.mk",
                    "MAKEFLAGS": "-e", "SDKROOT": "unexpected", "INPUT_SDK": "unexpected",
                    "CURRENT_BUILD_CONFIG": "wrong-target", "CC": "wrong-compiler", "CFLAGS": "wrong-flags"}
        self.assertEqual(clean_environment(original), {"PATH": "tools"})
        self.assertIn("GH_TOKEN", original)

    def test_green_graph_is_never_a_kernel_or_boot_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            def query(arguments, environment):
                value = str(output) if "--show-sdk-path" in arguments else "17.0"
                return {"exit_code": 0, "stdout": value, "stderr": ""}
            with patch("tools.check_xnu_build_graph.sys.platform", "darwin"), \
                    patch("tools.check_xnu_build_graph.prepare", return_value={}), \
                    patch("tools.check_xnu_build_graph.query", side_effect=query), \
                    patch("tools.check_xnu_build_graph.run_make", return_value={"exit_code": 0, "stopped_by": None}):
                report = check(output, "iphoneos")
            self.assertTrue(report["graph_passed"])
            for name in ("kernel_built", "boot_approved", "platform_memory_approved"):
                self.assertFalse(report[name])

    def test_dry_run_bootstrap_directories_exist_before_recursive_make(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            def query(arguments, environment):
                value = str(output) if "--show-sdk-path" in arguments else "18.5"
                return {"exit_code": 0, "stdout": value, "stderr": ""}
            def make(command, source, environment, log):
                for relative in ("obj/DEVELOPMENT_ARM64_MIDO", "sym", "dst"):
                    directory = output / "build" / relative
                    self.assertTrue(directory.is_dir())
                    self.assertEqual(list(directory.iterdir()), [])
                return {"exit_code": 2, "stopped_by": None}
            with patch("tools.check_xnu_build_graph.sys.platform", "darwin"), \
                    patch("tools.check_xnu_build_graph.prepare", return_value={}), \
                    patch("tools.check_xnu_build_graph.query", side_effect=query), \
                    patch("tools.check_xnu_build_graph.run_make", side_effect=make):
                report = check(output, "iphoneos")
            self.assertFalse(report["graph_passed"])
            self.assertFalse(report["kernel_built"])

    def test_missing_sdk_skips_make_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch("tools.check_xnu_build_graph.sys.platform", "darwin"), \
                    patch("tools.check_xnu_build_graph.prepare", return_value={}), \
                    patch("tools.check_xnu_build_graph.query", return_value={"exit_code": 1, "stdout": "", "stderr": "missing"}), \
                    patch("tools.check_xnu_build_graph.run_make") as make:
                report = check(output, "iphoneos")
            make.assert_not_called()
            self.assertFalse(report["graph_passed"])
            self.assertIsNone(report["make_result"]["exit_code"])

    def test_timeout_kills_the_entire_process_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            process = Mock(pid=42, returncode=-9)
            process.poll.return_value = None
            with patch("tools.check_xnu_build_graph.subprocess.Popen", return_value=process) as popen, \
                    patch("tools.check_xnu_build_graph.time.monotonic", side_effect=[0, 100, 101]), \
                    patch("tools.check_xnu_build_graph.os.killpg", create=True) as kill, \
                    patch("tools.check_xnu_build_graph.signal.SIGKILL", 9, create=True):
                result = run_make(["make"], directory, {}, directory / "make.log")
            self.assertEqual(result["stopped_by"], "timeout")
            self.assertTrue(popen.call_args.kwargs["start_new_session"])
            kill.assert_called_once_with(42, 9)
            process.wait.assert_called_once()

    def test_explicit_short_phase_timeout_kills_the_process_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            process = Mock(pid=42, returncode=-9)
            process.poll.return_value = None
            with patch("tools.check_xnu_build_graph.subprocess.Popen", return_value=process), \
                    patch("tools.check_xnu_build_graph.time.monotonic", side_effect=[0, 1, 1.1]), \
                    patch("tools.check_xnu_build_graph.os.killpg", create=True) as kill, \
                    patch("tools.check_xnu_build_graph.signal.SIGKILL", 9, create=True):
                result = run_make(["make"], directory, {}, directory / "make.log", timeout=0.5)
            self.assertEqual(result["stopped_by"], "timeout")
            kill.assert_called_once_with(42, 9)

    def test_completed_process_group_is_not_killed(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            process = Mock(returncode=0)
            process.poll.return_value = 0
            with patch("tools.check_xnu_build_graph.subprocess.Popen", return_value=process), \
                    patch("tools.check_xnu_build_graph.os.killpg", create=True) as kill:
                result = run_make(["make"], directory, {}, directory / "make.log")
            self.assertEqual(result["exit_code"], 0)
            self.assertIsNone(result["stopped_by"])
            kill.assert_not_called()

    def test_invalid_log_caps_never_start_processes(self):
        for limit in (0, -1, 16 * 1024 * 1024 + 1, True, 1.5):
            with self.subTest(limit=limit), patch("tools.check_xnu_build_graph.subprocess.Popen") as popen:
                with self.assertRaisesRegex(ValueError, "log limit"):
                    run_make(["make"], Path("source"), {}, Path("log"), log_limit=limit)
                popen.assert_not_called()

    def test_log_cap_kills_running_group_and_detects_completed_overshoot(self):
        for completed in (False, True):
            with self.subTest(completed=completed), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                process = Mock(pid=42, returncode=0 if completed else -9)
                process.poll.return_value = 0 if completed else None
                def launch(*args, **kwargs):
                    kwargs["stdout"].write(b"oversized log")
                    kwargs["stdout"].flush()
                    return process
                with patch("tools.check_xnu_build_graph.subprocess.Popen", side_effect=launch), \
                        patch("tools.check_xnu_build_graph.os.killpg", create=True) as kill, \
                        patch("tools.check_xnu_build_graph.signal.SIGKILL", 9, create=True):
                    result = run_make(["make"], directory, {}, directory / "log", log_limit=4)
                self.assertEqual(result["stopped_by"], "log limit")
                self.assertEqual(result["log_limit_bytes"], 4)
                if completed:
                    kill.assert_not_called()
                else:
                    kill.assert_called_once_with(42, 9)


if __name__ == "__main__":
    unittest.main()
