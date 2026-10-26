import hashlib
import io
import struct
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools.test_mido_drbg import Reference, verify_dependency
from tools.mido_elf import symbols_from_elf


class DrbgVerificationTests(unittest.TestCase):
    def elf(self):
        blob = bytearray(512)
        blob[:6] = b"\x7fELF\x02\x01"
        struct.pack_into("<H", blob, 18, 183)
        struct.pack_into("<Q", blob, 40, 64)
        struct.pack_into("<HH", blob, 58, 64, 3)
        struct.pack_into("<IIQQQQIIQQ", blob, 128, 0, 3, 0, 0, 256, 12, 0, 0, 1, 0)
        struct.pack_into("<IIQQQQIIQQ", blob, 192, 0, 2, 0, 0, 288, 24, 1, 0, 8, 24)
        blob[256:268] = b"\0adapter_fn\0"
        struct.pack_into("<IBBHQQ", blob, 288, 1, 18, 0, 1, 0x10000000, 16)
        return blob

    def test_elf_explicit_required_symbols(self):
        self.assertEqual(symbols_from_elf(self.elf(), required=("adapter_fn",))["adapter_fn"], 0x10000000)

    def test_elf_rejects_missing_entry(self):
        with self.assertRaisesRegex(ValueError, "Missing"):
            symbols_from_elf(self.elf(), required=("_start",))

    def test_elf_rejects_missing_adapter(self):
        with self.assertRaisesRegex(ValueError, "Missing"):
            symbols_from_elf(self.elf(), required=("different_fn",))

    def dependency(self, root, member="bearssl-0.6/inc/sample.h"):
        archive = root / "source.tar.gz"
        with tarfile.open(archive, "w:gz") as bundle:
            info = tarfile.TarInfo(member)
            info.size = 4
            bundle.addfile(info, io.BytesIO(b"test"))
        source = root / "bearssl-0.6"
        (source / "inc").mkdir(parents=True)
        (source / "inc/sample.h").write_bytes(b"test")
        return archive, source

    def test_matching_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive, source = self.dependency(Path(temporary))
            with patch("tools.test_mido_drbg.ARCHIVE_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest()):
                verify_dependency(archive, source)

    def test_rejects_unknown_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive, source = self.dependency(Path(temporary))
            with self.assertRaisesRegex(ValueError, "Unreviewed"):
                verify_dependency(archive, source)

    def test_rejects_modified_dependency(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive, source = self.dependency(Path(temporary))
            (source / "inc/sample.h").write_bytes(b"changed")
            with patch("tools.test_mido_drbg.ARCHIVE_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(ValueError, "Modified"):
                    verify_dependency(archive, source)

    def test_rejects_extra_include(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive, source = self.dependency(Path(temporary))
            (source / "inc/stdint.h").write_bytes(b"unexpected")
            with patch("tools.test_mido_drbg.ARCHIVE_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(ValueError, "Unexpected"):
                    verify_dependency(archive, source)

    def test_rejects_archive_traversal(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive, source = self.dependency(Path(temporary), "bearssl-0.6/../outside")
            with patch("tools.test_mido_drbg.ARCHIVE_SHA256", hashlib.sha256(archive.read_bytes()).hexdigest()):
                with self.assertRaisesRegex(ValueError, "path"):
                    verify_dependency(archive, source)

    def test_reference_zero_request_preserves_state(self):
        generator = Reference(bytes(range(64)))
        before = generator.key, generator.value
        self.assertEqual(generator.generate(0), b"")
        self.assertEqual((generator.key, generator.value), before)

    def test_reference_reseed_changes_output(self):
        generator = Reference(bytes(range(64)))
        generator.update(bytes(range(32)))
        self.assertNotEqual(generator.generate(64), Reference(bytes(range(64))).generate(64))
