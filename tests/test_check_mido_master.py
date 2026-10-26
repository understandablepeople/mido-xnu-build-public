from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.check_mido_master import (
    FORBIDDEN, REQUIRED, SOURCE_HASHES, check, reject_preprocessing,
    selector_script, validate_configuration, validate_sources,
)


def fragment(config="DEVELOPMENT"):
    return ('machine "arm64"\nmakeoptions OSFMK_MACHINE = "arm64"\n'
            + "".join(f"options {name}\n" for name in sorted(REQUIRED | {config})))


class MidoMasterTests(unittest.TestCase):
    def test_real_link_dependencies_are_required_without_apple_pmu(self):
        dependencies = {"CONFIG_SCHED_MULTIQ", "CONFIG_FSE", "IPSEC", "IPSEC_ESP",
                        "CRYPTO", "PF", "CONTENT_FILTER", "CONFIG_ATM", "CONFIG_TELEMETRY",
                        "CONFIG_PROC_UUID_POLICY", "MACH_KDP", "CONFIG_KDP_INTERACTIVE_DEBUGGING",
                        "CONFIG_DTRACE", "IOTRACKING", "CONFIG_XNUPOST", "CONFIG_COREDUMP"}
        self.assertLessEqual(dependencies, REQUIRED)
        self.assertLessEqual({"KPC", "KPERF", "XNU_MONITOR", "CONFIG_KERNEL_INTEGRITY"}, FORBIDDEN)

    def test_development_and_debug(self):
        for config in ("DEVELOPMENT", "DEBUG"):
            self.assertEqual(set(validate_configuration(fragment(config), config)), REQUIRED | {config})

    def test_missing_each_required_option(self):
        for name in REQUIRED:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "missing="):
                validate_configuration(fragment().replace(f"options {name}\n", ""), "DEVELOPMENT")

    def test_each_forbidden_option(self):
        for name in FORBIDDEN:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "forbidden="):
                validate_configuration(fragment() + f"options {name}\n", "DEVELOPMENT")

    def test_duplicate_options(self):
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_configuration(fragment() + "options MACH=1\n", "DEVELOPMENT")

    def test_unsupported_configurations(self):
        for config in ("RELEASE", "KASAN", "PROFILE", "DEVELOPMENT;exit"):
            with self.subTest(config=config), self.assertRaisesRegex(ValueError, "unsupported"):
                validate_configuration(fragment(), config)

    def test_wrong_debug_development_selection(self):
        for text in (fragment("DEBUG"), fragment() + "options DEBUG\n", fragment().replace("options DEVELOPMENT\n", "")):
            with self.assertRaisesRegex(ValueError, "wrong kernel"):
                validate_configuration(text, "DEVELOPMENT")

    def test_machine_must_be_single_arm64(self):
        for replacement in ('machine "arm64e"\n', '', 'machine "arm64"\nmachine "arm64"\n'):
            with self.assertRaisesRegex(ValueError, "one arm64 machine"):
                validate_configuration(fragment().replace('machine "arm64"\n', replacement), "DEVELOPMENT")

    def test_osfmk_machine_must_be_single_arm64(self):
        for replacement in ('makeoptions OSFMK_MACHINE = "arm64e"\n', '', 'makeoptions OSFMK_MACHINE = "arm64"\n' * 2):
            with self.assertRaisesRegex(ValueError, "OSFMK"):
                validate_configuration(fragment().replace('makeoptions OSFMK_MACHINE = "arm64"\n', replacement), "DEVELOPMENT")

    def test_preprocessor_directives_rejected(self):
        for directive in ("if", "ifdef", "ifndef", "elif", "else", "endif", "define", "undef", "include"):
            with self.subTest(directive=directive), self.assertRaisesRegex(ValueError, "unifdef"):
                reject_preprocessing(f"  # {directive} CONFIG\n")

    def test_functional_master_annotations_are_not_cpp(self):
        reject_preprocessing('# BASE = [ mach ]\noptions MACH # <mach>\n# ordinary prose\n')

    def test_selector_boundaries_rejected(self):
        start = "    sed -n \\\n"
        end = " >$SYSCONF.new"
        for text in ("", start, end, start * 2 + end, start + end * 2):
            with self.assertRaisesRegex(ValueError, "boundaries"):
                selector_script(text)

    def test_selector_body_preserved(self):
        body = "-e 'p' | awk '{print}'"
        script = selector_script("wrapper\n    sed -n \\\n" + body + " >$SYSCONF.new\nwrapper")
        self.assertTrue(script.endswith("    sed -n \\\n" + body + "\n"))
        self.assertIn("set -o pipefail", script)
        self.assertIn("printf '+%s\\n'", script)
        self.assertNotIn("SYSCONF", script)

    def test_wrong_source_set_rejected(self):
        with self.assertRaisesRegex(ValueError, "file set"):
            validate_sources({})

    def test_modified_upstream_rejected(self):
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_sources(dict.fromkeys(SOURCE_HASHES, b"modified"))

    def test_matching_source_hashes_accepted(self):
        with patch("tools.check_mido_master.hashlib.sha256") as checksum:
            checksum.return_value.hexdigest.side_effect = SOURCE_HASHES.values()
            validate_sources(dict.fromkeys(SOURCE_HASHES, b"fixture"))
            self.assertEqual(checksum.call_count, 2)

    def test_output_guard_precedes_network(self):
        workspace = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            for output in (Path(directory) / "new", workspace / "artifacts"):
                with patch("tools.check_mido_master.urllib.request.urlopen") as download:
                    with self.assertRaisesRegex(ValueError, "new directory"):
                        check(Path("unused"), output)
                    download.assert_not_called()
        with patch("tools.check_mido_master.Path.exists", return_value=True):
            with patch("tools.check_mido_master.urllib.request.urlopen") as download:
                with self.assertRaisesRegex(ValueError, "new directory"):
                    check(Path("unused"), workspace / "artifacts/reserved-test-output")
                download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
