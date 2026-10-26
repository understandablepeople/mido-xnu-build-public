import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.repair_xnu_scalar_cookies import (REPLACEMENTS, SOURCE_HASHES,
                                           repair_scalar_cookies, stage_scalar_cookies)


class ScalarCookieTests(unittest.TestCase):
    def repair_fixture(self, relative, data):
        digest = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
        with patch.dict(SOURCE_HASHES, {relative: digest}):
            return repair_scalar_cookies(relative, data)

    def test_all_sources_reject_unreviewed_data(self):
        self.assertEqual(len(SOURCE_HASHES), 11)
        self.assertEqual(set(SOURCE_HASHES), set(REPLACEMENTS))
        for relative in SOURCE_HASHES:
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "scalar cookie source"):
                repair_scalar_cookies(relative, b"unreviewed")

    def test_exact_changes_preserve_surrounding_data_and_line_endings(self):
        self.assertEqual(sum(count for entries in REPLACEMENTS.values() for before, after, count in entries), 21)
        for relative, entries in REPLACEMENTS.items():
            before = b"start\n" + b"\n".join(original for original, updated, count in entries for index in range(count)) + b"\nend"
            after = b"start\n" + b"\n".join(updated for original, updated, count in entries for index in range(count)) + b"\nend"
            with self.subTest(relative=relative):
                self.assertEqual(self.repair_fixture(relative, before), after)
                self.assertEqual(self.repair_fixture(relative, before.replace(b"\n", b"\r\n")), after)
                with self.assertRaisesRegex(ValueError, "scalar cookie source"):
                    repair_scalar_cookies(relative, after)

    def test_anchor_inventory_fails_closed(self):
        for relative, entries in REPLACEMENTS.items():
            data = b"\n".join(original for original, updated, count in entries for index in range(count))
            for original, updated, count in entries:
                for invalid in (data.replace(original, b"missing", 1), data + original):
                    with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "anchor"):
                        self.repair_fixture(relative, invalid)

    def test_cookie_repairs_only_add_pointer_width_conversion(self):
        files = 0
        sites = 0
        for relative, entries in REPLACEMENTS.items():
            if relative in ("osfmk/arm/model_dep.c", "pexpert/arm/pe_init.c", "iokit/Kernel/IONVRAMV3Handler.cpp"):
                continue
            files += 1
            for original, updated, count in entries:
                self.assertEqual(updated.replace(b"(uintptr_t)", b"").replace(b")p1", b") p1"), original)
                sites += count
        self.assertEqual((files, sites), (8, 15))

    def test_zero_and_signature_values_are_preserved(self):
        original, updated, count = REPLACEMENTS["osfmk/arm/model_dep.c"][0]
        self.assertEqual((original, updated, count), (b"(ppnum_t)NULL", b"(ppnum_t)0", 3))
        for literal, expected in ((b"'SHMC'", 0x53484D43), (b"'BTRC'", 0x42545243), (b"'NVV3'", 0x4E565633)):
            self.assertEqual(int.from_bytes(literal[1:-1], "big"), expected)

    def test_staging_checks_all_inputs_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("first.c", "second.c"):
                (root / relative).write_bytes(b"original")
            with patch.dict(SOURCE_HASHES, dict.fromkeys(("first.c", "second.c"), "unused"), clear=True):
                with patch("tools.repair_xnu_scalar_cookies.repair_scalar_cookies",
                           side_effect=[b"updated", ValueError("bad source")]):
                    with self.assertRaises(ValueError):
                        stage_scalar_cookies(root)
            self.assertEqual((root / "first.c").read_bytes(), b"original")
