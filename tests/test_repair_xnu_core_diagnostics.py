import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.repair_xnu_core_diagnostics import (SOURCE_HASHES, repair_core_diagnostics,
                                             repair_numeric_enum_assertions,
                                             repair_smr_bucket_selector, stage_core_diagnostics)


class CoreDiagnosticTests(unittest.TestCase):
    def test_all_sources_reject_unpinned_data(self):
        self.assertEqual(len(SOURCE_HASHES), 3)
        for relative in SOURCE_HASHES:
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "core diagnostic source"):
                repair_core_diagnostics(relative, b"unreviewed")

    def test_numeric_enum_assertions_retain_both_constants_and_equality(self):
        for arena, count, template in (
                (True, 3, "static_assert(SKMEM_ARENA_TYPE_{name} == SAR_TYPE_{name});\n"),
                (False, 27, "_CASSERT(SREG_{name} == SKMEM_REGION_{name});\n")):
            original = "".join(template.format(name="VALUE" + "X" * index) for index in range(count)).encode()
            repaired = repair_numeric_enum_assertions(original, arena)
            self.assertEqual(repaired.replace(b"(int)", b""), original)
            self.assertEqual(repaired.count(b" == "), count)
            for invalid in (b"", original + original, repaired):
                with self.assertRaises(ValueError):
                    repair_numeric_enum_assertions(invalid, arena)

    def test_smr_invalid_selector_panics_instead_of_using_uninitialized_array(self):
        original = (b"#include <kern/counter.h>\n\tswitch (sel) {\n\tcase SMRSH_CUR:\ncurrent();\nbreak;\n"
                    b"\tcase SMRSH_NEW:\nnew_array();\nbreak;\n}\n")
        repaired = repair_smr_bucket_selector(original)
        addition = b'\tdefault:\n\t\tpanic("invalid SMR hash bucket selector");\n'
        self.assertEqual(repaired.replace(addition, b"").replace(b"#include <kern/debug.h>\n", b""), original)
        self.assertEqual(repaired.count(b"panic("), 1)
        for invalid in (b"", original + original, original.replace(b"SMRSH_NEW", b"OTHER")):
            with self.assertRaises(ValueError):
                repair_smr_bucket_selector(invalid)

    def test_staging_validates_all_inputs_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("first.c", "second.c"):
                (root / relative).write_bytes(b"original")
            profiles = {relative: hashlib.sha256(b"original").hexdigest()
                        for relative in ("first.c", "second.c")}
            with patch.dict(SOURCE_HASHES, profiles, clear=True):
                with patch("tools.repair_xnu_core_diagnostics.repair_core_diagnostics",
                           side_effect=[b"updated", ValueError("bad source")]):
                    with self.assertRaises(ValueError):
                        stage_core_diagnostics(root)
            self.assertEqual((root / "first.c").read_bytes(), b"original")
