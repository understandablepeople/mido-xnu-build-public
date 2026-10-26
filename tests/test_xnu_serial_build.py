from pathlib import Path
import unittest
from unittest.mock import patch

from tools.check_xnu_build import phase_command, run_phase


class SerialBuildTests(unittest.TestCase):
    def test_serial_build_budget_and_pipeline_cap(self):
        for target, elapsed, expected in (("build", 0, 600), ("build", 100, 550),
                                          ("exporthdrs", 0, 90)):
            with self.subTest(target=target, elapsed=elapsed):
                with patch("tools.check_xnu_build.time.monotonic", return_value=elapsed):
                    with patch("tools.check_xnu_build.run_make", return_value={}) as make:
                        run_phase(["make", target], Path("source"), {}, Path("build.log"), 0)
                self.assertEqual(make.call_args.kwargs["timeout"], expected)

    def test_all_make_phases_are_serial_and_stop_on_error(self):
        for target in ("exporthdrs", "build"):
            with self.subTest(target=target):
                command = phase_command(Path("source"), Path("build"), "iphoneos", "availability", target)
                self.assertIn("-j1", command)
                self.assertIn("MAKEJOBS=--jobs=1", command)
                self.assertNotIn("-j3", command)
                self.assertNotIn("--keep-going", command)
                self.assertEqual(command[-1], target)


if __name__ == "__main__":
    unittest.main()
