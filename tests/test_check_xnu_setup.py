from contextlib import contextmanager
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.check_xnu_setup import (HOST_TOOLS, SETUP_DATA, SETUP_PROGRAMS, check,
                                   executable_resource, inspect_outputs, probe_availability, safe_query, setup_command)


class XnuSetupTests(unittest.TestCase):
    @contextmanager
    def ready_environment(self, output):
        def query(arguments, environment):
            value = str(output) if "--show-sdk-path" in arguments else "18.5"
            if "--find" in arguments:
                value = f"/tools/{arguments[-1]}"
            return {"exit_code": 0, "stdout": value, "stderr": ""}
        with patch("tools.check_xnu_setup.sys.platform", "darwin"), \
                patch("tools.check_xnu_setup.prepare", return_value={}), \
                patch("tools.check_xnu_setup.safe_query", side_effect=query), \
                patch("tools.check_xnu_setup.probe_availability", return_value={"ready": True, "queries": {}}), \
                patch("tools.check_xnu_setup.executable_resource", return_value=True):
            yield

    def write_synthetic_outputs(self, build):
        for relative in SETUP_DATA:
            path = build / "obj" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic fixture, not a generated XNU file\n"
                            "__DARWIN_ALIAS_STARTING_IPHONE___IPHONE_16_6\n"
                            "__DARWIN_ALIAS_STARTING_MAC___MAC_13_5\n"
                            "___POSIX_C_DEPRECATED_STARTING_200809L\n")
        header = struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 2, 0, 0, 0, 0)
        for name in SETUP_PROGRAMS:
            path = build / "obj" / "SETUP" / name / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(header)
            path.chmod(0o755)

    def test_setup_target_is_real_serial_and_never_all_or_install(self):
        command = setup_command(Path("source"), Path("build"), "iphoneos")
        self.assertEqual(command[-1], "setup")
        self.assertIn("MAKEJOBS=--jobs=1", command)
        self.assertIn("-j1", command)
        self.assertIn("HOST_SDKROOT=macosx", command)
        for forbidden in ("--just-print", "all", "install", "build", "config"):
            self.assertNotIn(forbidden, command)

    def test_unknown_sdk_is_rejected(self):
        with self.assertRaises(ValueError):
            setup_command(Path("source"), Path("build"), "iphoneos;all")

    def test_non_macos_rejected_before_download(self):
        with patch("tools.check_xnu_setup.sys.platform", "win32"), \
                patch("tools.check_xnu_setup.prepare") as prepare:
            with self.assertRaisesRegex(ValueError, "actual macOS"):
                check(Path("unused"), "iphoneos", execute_setup=True)
            prepare.assert_not_called()

    def test_unknown_sdk_rejected_before_download(self):
        with patch("tools.check_xnu_setup.sys.platform", "darwin"), \
                patch("tools.check_xnu_setup.prepare") as prepare:
            with self.assertRaisesRegex(ValueError, "unsupported SDK"):
                check(Path("unused"), "iphoneos.internal", execute_setup=True)
            prepare.assert_not_called()

    def test_audit_never_starts_make_and_never_reports_setup_passed(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.ready_environment(output), patch("tools.check_xnu_setup.run_make") as make:
                report = check(output, "iphoneos")
            make.assert_not_called()
            self.assertTrue(report["prerequisites_ready"])
            self.assertFalse(report["setup_passed"])
            self.assertFalse((output / "build").exists())
            self.assertTrue((output / "setup-report.json").is_file())
            self.assertEqual(set(report["sdks"]), {"iphoneos", "macosx"})
            self.assertEqual(set(report["host_tools"]), set(HOST_TOOLS))

    def test_missing_private_availability_resource_blocks_compilation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.ready_environment(output), \
                    patch("tools.check_xnu_setup.executable_resource", side_effect=lambda path: path.name != "availability.pl"), \
                    patch("tools.check_xnu_setup.run_make") as make:
                report = check(output, "iphoneos", execute_setup=True)
            make.assert_not_called()
            self.assertFalse(report["prerequisites_ready"])
            self.assertTrue(any("availability.pl" in item for item in report["blockers"]))

    def test_open_dependency_is_explicit_and_never_an_sdk_overlay(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            script = output / "dependencies/AvailabilityVersions-121/availability.pl"
            with self.ready_environment(output), \
                    patch("tools.check_xnu_setup.prepare_availability", return_value={"script_path": str(script)}) as prepare, \
                    patch("tools.check_xnu_setup.run_make") as make:
                report = check(output, "iphoneos", open_availability=True)
            prepare.assert_called_once_with(output.resolve())
            make.assert_not_called()
            self.assertIn(f"MIDO_AVAILABILITY_PL={script}", report["make_command"])
            self.assertEqual(report["resources"]["availability.pl"]["path"], str(script))
            self.assertFalse(report["setup_passed"])

    def test_missing_host_sdk_blocks_make(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.ready_environment(output), \
                    patch("tools.check_xnu_setup.sdk_result_ready", side_effect=[True, False]), \
                    patch("tools.check_xnu_setup.run_make") as make:
                report = check(output, "iphoneos", execute_setup=True)
            make.assert_not_called()
            self.assertIn("SDK unavailable: macosx", report["blockers"])

    def test_missing_host_tool_blocks_make(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            def query(arguments, environment):
                if "--find" in arguments:
                    return {"exit_code": 1, "stdout": "", "stderr": "not installed"}
                value = str(output) if "--show-sdk-path" in arguments else "18.5"
                return {"exit_code": 0, "stdout": value, "stderr": ""}
            with self.ready_environment(output), \
                    patch("tools.check_xnu_setup.safe_query", side_effect=query), \
                    patch("tools.check_xnu_setup.run_make") as make:
                report = check(output, "iphoneos", execute_setup=True)
            make.assert_not_called()
            self.assertIn("host tool unavailable: clang", report["blockers"])

    def test_make_start_failure_is_saved_in_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.ready_environment(output), \
                    patch("tools.check_xnu_setup.run_make", side_effect=OSError("spawn failed")):
                report = check(output, "iphoneos", execute_setup=True)
            self.assertFalse(report["setup_passed"])
            self.assertIn("spawn failed", report["make_result"]["stopped_by"])
            self.assertTrue((output / "setup-report.json").is_file())

    def test_failed_availability_interpreter_prevents_host_compilation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.ready_environment(output), \
                    patch("tools.check_xnu_setup.probe_availability", return_value={"ready": False, "queries": {}}), \
                    patch("tools.check_xnu_setup.run_make") as make:
                report = check(output, "iphoneos", execute_setup=True)
            make.assert_not_called()
            self.assertFalse(report["prerequisites_ready"])
            self.assertTrue(any("version lists" in item for item in report["blockers"]))

    def test_availability_probe_rejects_empty_lists_and_interpreter_failure(self):
        results = (subprocess.CompletedProcess([], 0, "", ""),
                   subprocess.CompletedProcess([], 1, "16.6 13.5", "Perl failed"))
        with patch("tools.check_xnu_setup.subprocess.run", side_effect=results):
            report = probe_availability(Path("availability.pl"), {})
        self.assertFalse(report["ready"])

    def test_availability_probe_accepts_real_version_format_and_required_versions(self):
        results = (subprocess.CompletedProcess([], 0, "2.0 3.1.2 16.6", ""),
                   subprocess.CompletedProcess([], 0, "10.0 11.00 13.5", ""))
        with patch("tools.check_xnu_setup.subprocess.run", side_effect=results):
            report = probe_availability(Path("availability.pl"), {})
        self.assertTrue(report["ready"])

    def test_nonempty_header_without_alias_macros_is_not_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            self.write_synthetic_outputs(build)
            relative = "bsd/sys/_symbol_aliasing.h"
            (build / "obj" / relative).write_text("header without emitted aliases")
            self.assertFalse(inspect_outputs(build)[relative]["valid"])

    def test_successful_make_without_outputs_is_not_green(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.ready_environment(output), \
                    patch("tools.check_xnu_setup.run_make", return_value={"exit_code": 0, "stopped_by": None}):
                report = check(output, "iphoneos", execute_setup=True)
            self.assertFalse(report["setup_passed"])
            self.assertEqual(len(report["outputs"]), 12)

    def test_mock_setup_success_is_never_graph_or_kernel_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            def make(command, source, environment, log):
                self.assertNotIn("GH_TOKEN", environment)
                self.assertNotIn("MAKEFLAGS", environment)
                self.write_synthetic_outputs(output / "build")
                return {"exit_code": 0, "stopped_by": None}
            with self.ready_environment(output), \
                    patch.dict("os.environ", {"GH_TOKEN": "fixture", "MAKEFLAGS": "-n"}), \
                    patch("tools.check_xnu_setup.run_make", side_effect=make):
                report = check(output, "iphoneos", execute_setup=True)
            self.assertTrue(report["setup_passed"])
            for name in ("graph_passed", "kernel_built", "boot_approved", "platform_memory_approved"):
                self.assertFalse(report[name])

    def test_make_failure_and_timeout_are_not_green_even_with_outputs(self):
        for result in ({"exit_code": 2, "stopped_by": None}, {"exit_code": 0, "stopped_by": "timeout"}):
            with self.subTest(result=result), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary)
                self.write_synthetic_outputs(output / "build")
                with self.ready_environment(output), patch("tools.check_xnu_setup.run_make", return_value=result):
                    report = check(output, "macosx", execute_setup=True)
                self.assertFalse(report["setup_passed"])

    def test_invalid_or_empty_outputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            self.write_synthetic_outputs(build)
            (build / "obj/SETUP/config/config").write_text("not a Mach-O executable")
            (build / "obj" / SETUP_DATA[0]).write_bytes(b"")
            report = inspect_outputs(build)
            self.assertFalse(report["SETUP/config/config"]["valid"])
            self.assertFalse(report[SETUP_DATA[0]]["valid"])

    def test_query_timeout_is_reportable_not_uncaught(self):
        with patch("tools.check_xnu_setup.query", side_effect=subprocess.TimeoutExpired(["xcrun"], 15)):
            result = safe_query(["--sdk", "macosx", "--find", "clang"], {})
        self.assertIsNone(result["exit_code"])
        self.assertEqual(result["stdout"], "")
        self.assertIn("timed out", result["stderr"])

    def test_native_program_without_execute_permission_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            self.write_synthetic_outputs(build)
            with patch("tools.check_xnu_setup.os.access", return_value=False):
                report = inspect_outputs(build)
            self.assertFalse(report["SETUP/config/config"]["valid"])
            self.assertTrue(report[SETUP_DATA[0]]["valid"])

    def test_resource_must_be_a_real_executable_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.assertFalse(executable_resource(directory))
            self.assertFalse(executable_resource(directory / "missing"))
            path = directory / "resource"
            path.write_text("fixture")
            with patch("tools.check_xnu_setup.os.access", return_value=False):
                self.assertFalse(executable_resource(path))


if __name__ == "__main__":
    unittest.main()
