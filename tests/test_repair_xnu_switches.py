import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.repair_xnu_switches import PROFILES, repair_switches, stage_switch_repairs


class SwitchRepairTests(unittest.TestCase):
    def test_inventory_and_all_source_pins(self):
        self.assertEqual(len(PROFILES), 23)
        self.assertEqual(sum(len(profile["insertions"]) for profile in PROFILES.values()), 55)
        for relative in PROFILES:
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(ValueError, "switch repair source"):
                    repair_switches(relative, b"unreviewed")

    def test_default_precedes_cases_and_does_not_create_a_last_case_fallthrough(self):
        data = b"switch (value) {\ncase 1: result = 4;\n}\n"
        profile = {"sha256": hashlib.sha256(data).hexdigest(),
                   "insertions": [[1, "switch (value) {\n", ""]]}
        with patch.dict(PROFILES, {"fixture.c": profile}):
            result = repair_switches("fixture.c", data)
        self.assertEqual(result, b"switch (value) {\ndefault:\n\tbreak;\ncase 1: result = 4;\n}\n")
        self.assertEqual(result.replace(b"default:\n\tbreak;\n", b""), data)

    def test_descending_insertions_preserve_nested_original_coordinates(self):
        data = b"switch (outer) {\ncase 1:\n\tswitch (inner) {\n\tcase 2: return 3;\n\t}\n}\n"
        profile = {"sha256": hashlib.sha256(data).hexdigest(),
                   "insertions": [[1, "switch (outer) {\n", ""], [3, "\tswitch (inner) {\n", "\t"]]}
        with patch.dict(PROFILES, {"fixture.c": profile}):
            result = repair_switches("fixture.c", data)
        self.assertEqual(result.count(b"default:"), 2)
        self.assertIn(b"switch (inner) {\n\tdefault:\n\t\tbreak;\n", result)

    def test_bad_coordinates_duplicate_rows_and_nonempty_indents_are_rejected(self):
        data = b"switch (value) {\n}\n"
        good = [1, "switch (value) {\n", ""]
        for insertions in ([good, good], [[0, good[1], ""]], [[1, "wrong {\n", ""]], [[1, good[1], "code"]]):
            profile = {"sha256": hashlib.sha256(data).hexdigest(), "insertions": insertions}
            with patch.dict(PROFILES, {"fixture.c": profile}):
                with self.assertRaises(ValueError):
                    repair_switches("fixture.c", data)

    def test_staging_checks_every_source_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            data = b"switch (value) {\n}\n"
            (source / "first.c").write_bytes(data)
            (source / "second.c").write_bytes(b"bad")
            profile = {"sha256": hashlib.sha256(data).hexdigest(),
                       "insertions": [[1, "switch (value) {\n", ""]]}
            with patch.dict(PROFILES, {"first.c": profile, "second.c": profile}, clear=True):
                with self.assertRaises(ValueError):
                    stage_switch_repairs(source)
            self.assertEqual((source / "first.c").read_bytes(), data)
