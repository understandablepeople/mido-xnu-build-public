from pathlib import Path
import unittest
from unittest.mock import patch

from tools.check_xnu_boot_args import assertion_source, check_header, FIELD_OFFSETS


class BootArgsTests(unittest.TestCase):
    def test_all_documented_offsets_have_assertions(self):
        source = assertion_source()
        self.assertEqual(len(FIELD_OFFSETS), 13)
        for field, offset in FIELD_OFFSETS.items():
            self.assertIn(f"__builtin_offsetof(boot_args, {field}) == {offset}", source)
        self.assertIn("sizeof(boot_args) == 736", source)
        self.assertIn("_Alignof(boot_args) == 8", source)

    def test_modified_header_never_reaches_compiler(self):
        with patch("tools.check_xnu_boot_args.subprocess.run") as compiler:
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                check_header(b"not the pinned header", Path("clang"))
            compiler.assert_not_called()


if __name__ == "__main__":
    unittest.main()
