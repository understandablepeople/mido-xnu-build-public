import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.repair_xnu_formats import PROFILES, CAST_PROFILES, repair_formats, stage_format_repairs


class FormatRepairTests(unittest.TestCase):
    def test_reviewed_inventory_is_bounded(self):
        self.assertEqual(len(PROFILES), 36)
        self.assertEqual(sum(len(profile[1]) for profile in PROFILES.values()), 126)
        self.assertEqual(sum(len(profile["casts"]) for profile in CAST_PROFILES.values()), 52)
        for relative, (expected, replacements) in PROFILES.items():
            self.assertNotIn("..", Path(relative).parts)
            self.assertFalse(Path(relative).is_absolute())
            self.assertEqual(len(expected), 64)
            self.assertEqual(len(replacements), len(set(replacements)))

    def test_every_profile_rejects_unpinned_source(self):
        for relative in PROFILES:
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(ValueError, "unexpected format repair source"):
                    repair_formats(relative, b"unreviewed input")

    def test_reverse_order_preserves_later_columns_and_other_bytes(self):
        data = b'printf("%ld %lld", size, timestamp);\n'
        profile = (hashlib.sha256(data).hexdigest(),
                   ((1, 9, "%ld", "%zu"), (1, 13, "%lld", "%llu")))
        with patch.dict(PROFILES, {"fixture.c": profile}):
            result = repair_formats("fixture.c", data)
        self.assertEqual(result, b'printf("%zu %llu", size, timestamp);\n')

    def test_wrong_coordinate_or_conversion_fails_closed(self):
        data = b'printf("%ld", value);\n'
        for replacement in ((1, 8, "%ld", "%lu"), (0, 9, "%ld", "%lu"),
                            (1, 9, "%ld", "%s")):
            with self.subTest(replacement=replacement):
                profile = (hashlib.sha256(data).hexdigest(), (replacement,))
                with patch.dict(PROFILES, {"fixture.c": profile}):
                    with self.assertRaises(ValueError):
                        repair_formats("fixture.c", data)

    def test_no_source_written_if_later_validation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            data = b'printf("%ld", value);\n'
            (source / "first.c").write_bytes(data)
            (source / "second.c").write_bytes(b"unexpected")
            profile = (hashlib.sha256(data).hexdigest(), ((1, 9, "%ld", "%lu"),))
            with patch.dict(PROFILES, {"first.c": profile, "second.c": profile}, clear=True):
                with self.assertRaises(ValueError):
                    stage_format_repairs(source)
            self.assertEqual((source / "first.c").read_bytes(), data)

    def test_integer_cast_evaluates_the_same_simple_expression_once(self):
        data = b'printf("%x", object->result);\n'
        expected = hashlib.sha256(data).hexdigest()
        with patch.dict(PROFILES, {"fixture.c": (expected, ())}):
            with patch.dict(CAST_PROFILES, {"fixture.c": {"casts": ((1, 14, "object->result", "unsigned int"),)}}):
                result = repair_formats("fixture.c", data)
        self.assertEqual(result, b'printf("%x", (unsigned int)(object->result));\n')
        self.assertEqual(result.count(b"object->result"), 1)

    def test_integer_cast_disallows_calls_arithmetic_and_unknown_types(self):
        data = b'printf("%x", value);\n'
        expected = hashlib.sha256(data).hexdigest()
        for expression, primitive in (("value()", "unsigned int"), ("value + 1", "unsigned int"),
                                      ("value", "void *"), ("value", "unsigned short")):
            with self.subTest(expression=expression, primitive=primitive):
                with patch.dict(PROFILES, {"fixture.c": (expected, ())}):
                    with patch.dict(CAST_PROFILES, {"fixture.c": {"casts": ((1, 14, expression, primitive),)}}):
                        with self.assertRaisesRegex(ValueError, "unreviewed integer cast"):
                            repair_formats("fixture.c", data)
