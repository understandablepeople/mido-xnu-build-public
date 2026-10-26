import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest

from tools.inspect_aboot import file_offset, parse_elf32, verify_readback


def make_elf():
    image = bytearray(128)
    identification = b"\x7fELF\x01\x01\x01" + bytes(9)
    struct.pack_into("<16sHHIIIIIHHHHHH", image, 0, identification, 2, 40, 1, 0x1000, 52, 0, 0, 52, 32, 1, 0, 0, 0)
    struct.pack_into("<8I", image, 52, 1, 96, 0x1000, 0x1000, 16, 32, 5, 16)
    return image


class AbootInspectionTests(unittest.TestCase):
    def test_entry_and_address_translation(self):
        elf = parse_elf32(make_elf())
        self.assertEqual(elf["entry"], 0x1000)
        self.assertEqual(file_offset(elf, 0x1004, 4), 100)

    def test_bss_is_not_file_backed(self):
        with self.assertRaises(ValueError):
            file_offset(parse_elf32(make_elf()), 0x1010, 4)

    def test_segment_outside_file(self):
        image = make_elf()
        struct.pack_into("<I", image, 52 + 4, 120)
        with self.assertRaises(ValueError):
            parse_elf32(image)

    def test_reject_other_architecture(self):
        image = make_elf()
        struct.pack_into("<H", image, 18, 183)
        with self.assertRaises(ValueError):
            parse_elf32(image)

    def test_reject_bad_entry(self):
        image = make_elf()
        struct.pack_into("<I", image, 24, 0x2000)
        with self.assertRaises(ValueError):
            parse_elf32(image)

    def test_verified_manifest_and_tamper(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest = []
            for name in ("aboot", "abootbak", "persist"):
                data = bytes(make_elf())
                (root / (name + ".img")).write_bytes(data)
                manifest.append({"Name": name, "Bytes": len(data), "SHA256": hashlib.sha256(data).hexdigest()})
            (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8-sig")
            self.assertEqual(len(verify_readback(root)), 3)
            (root / "persist.img").write_bytes(b"modified")
            with self.assertRaises(ValueError):
                verify_readback(root)


if __name__ == "__main__":
    unittest.main()
