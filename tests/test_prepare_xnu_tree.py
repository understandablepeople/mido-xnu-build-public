from pathlib import Path
import tarfile
import unittest
from unittest.mock import patch

from tools.prepare_xnu_tree import ARCHIVE_ROOT, EXPANDED_LIMIT, MEMBER_LIMIT, prepare, validate_members


def member(path, kind=tarfile.REGTYPE, size=0):
    entry = tarfile.TarInfo(path)
    entry.type = kind
    entry.size = size
    return entry


class PrepareXnuTreeTests(unittest.TestCase):
    def test_regular_tree(self):
        entries = [member(ARCHIVE_ROOT, tarfile.DIRTYPE), member(ARCHIVE_ROOT + "/config", tarfile.DIRTYPE),
                   member(ARCHIVE_ROOT + "/config/MASTER", size=123)]
        self.assertEqual(validate_members(entries), 123)

    def test_empty_or_excessive_entry_count(self):
        for entries in ([], [member(ARCHIVE_ROOT)] * (MEMBER_LIMIT + 1)):
            with self.assertRaisesRegex(ValueError, "count"):
                validate_members(entries)

    def test_wrong_root_absolute_and_traversal(self):
        for path in ("other/file", "/" + ARCHIVE_ROOT + "/file", ARCHIVE_ROOT + "/../escape"):
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "path"):
                validate_members([member(path)])

    def test_windows_ambiguous_paths(self):
        for suffix in ("/file:stream", "/folder\\file", "/file.", "/folder /file"):
            with self.subTest(suffix=suffix), self.assertRaisesRegex(ValueError, "path"):
                validate_members([member(ARCHIVE_ROOT + suffix)])

    def test_links_and_devices_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE):
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "special"):
                validate_members([member(ARCHIVE_ROOT + "/entry", kind)])

    def test_case_collisions_and_duplicate_names(self):
        for suffix in ("file", "FILE"):
            with self.assertRaisesRegex(ValueError, "colliding"):
                validate_members([member(ARCHIVE_ROOT + "/file"), member(ARCHIVE_ROOT + "/" + suffix)])

    def test_expanded_limit(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_members([member(ARCHIVE_ROOT + "/file", size=EXPANDED_LIMIT + 1)])

    def test_negative_size(self):
        with self.assertRaisesRegex(ValueError, "special"):
            validate_members([member(ARCHIVE_ROOT + "/file", size=-1)])

    def test_existing_or_outside_output_precedes_download(self):
        workspace = Path(__file__).resolve().parent.parent
        with patch("tools.prepare_xnu_tree.urllib.request.urlopen") as download:
            for output in (workspace, workspace / "artifacts"):
                with self.assertRaisesRegex(ValueError, "new directory"):
                    prepare(output)
            download.assert_not_called()

    def test_wrong_archive_hash_never_creates_output(self):
        workspace = Path(__file__).resolve().parent.parent
        with patch("tools.prepare_xnu_tree.urllib.request.urlopen") as download:
            download.return_value.__enter__.return_value.read.return_value = b"not XNU"
            with patch("tools.prepare_xnu_tree.Path.exists", return_value=False):
                with patch("tools.prepare_xnu_tree.Path.mkdir") as mkdir:
                    with self.assertRaisesRegex(ValueError, "SHA-256"):
                        prepare(workspace / "artifacts/unit-unused-output")
                    mkdir.assert_not_called()


if __name__ == "__main__":
    unittest.main()
