from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SpawnDiagnosticTests(unittest.TestCase):
    def test_diagnostic_is_a_statement_block_after_label(self):
        patch = (ROOT / "xnu/patches/0122-mido-spawn-failure-diagnostics.patch").read_text()
        added = "\n".join(line[1:] for line in patch.splitlines()
                          if line.startswith("+") and not line.startswith("+++"))
        self.assertIn(" bad:", patch)
        self.assertTrue(added.strip().startswith("#if defined(ARM64_BOARD_CONFIG_MIDO)\n    {\n"))
        self.assertTrue(added.rstrip().endswith("    }\n#endif"))
        self.assertIn("static uint32_t mido_spawn_reports = 0;", added)
        self.assertIn("error != 0", added)
        self.assertIn("os_atomic_inc_orig(&mido_spawn_reports, relaxed) < 64", added)
        self.assertNotIn("error =", added.replace("mido_path_error =", "path_result :="))


if __name__ == "__main__":
    unittest.main()
