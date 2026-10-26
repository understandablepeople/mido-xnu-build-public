import gzip
from pathlib import Path
import struct
import tempfile
import unittest

from tools.inspect_boot import align, decode_property, find_fdts, inspect, parse_boot, parse_fdt


def make_fdt():
    structure = struct.pack(">I", 1) + b"\0\0\0\0"
    value = b"test,mido\0"
    structure += struct.pack(">III", 3, len(value), 0) + value
    structure += b"\0" * (align(len(structure), 4) - len(structure))
    structure += struct.pack(">II", 2, 9)
    strings = b"compatible\0"
    total = 56 + len(structure) + len(strings)
    header = struct.pack(">10I", 0xD00DFEED, total, 56, 56 + len(structure), 40, 17, 16, 0, len(strings), len(structure))
    return header + bytes(16) + structure + strings


def make_boot(kernel):
    image = bytearray(align(2048 + len(kernel), 2048))
    image[:8] = b"ANDROID!"
    struct.pack_into("<10I", image, 8, len(kernel), 0x80008000, 0, 0x82000000, 0, 0, 0x81E00000, 2048, 0, 0)
    image[2048:2048 + len(kernel)] = kernel
    return image


class InspectionTests(unittest.TestCase):
    def test_numeric_properties_are_not_strings(self):
        self.assertEqual(decode_property(bytes(4), "reg"), ["0x0"])
        self.assertEqual(decode_property(struct.pack(">II", 65, 0), "interrupts"), ["0x41", "0x0"])
        self.assertEqual(decode_property(b"qcom,mido\0", "compatible"), ["qcom,mido"])

    def test_boot_layout(self):
        header, parts = parse_boot(make_boot(b"kernel"))
        self.assertEqual(header["page_size"], 2048)
        self.assertEqual(parts["kernel"], b"kernel")

    def test_reject_truncation(self):
        with self.assertRaises(ValueError):
            parse_boot(make_boot(b"kernel")[:2049])

    def test_reject_new_header(self):
        image = make_boot(b"kernel")
        struct.pack_into("<I", image, 40, 2)
        with self.assertRaises(ValueError):
            parse_boot(image)

    def test_valid_tree(self):
        self.assertEqual(parse_fdt(make_fdt())["nodes"]["/"]["compatible"], b"test,mido\0")

    def test_skip_false_magic(self):
        found = list(find_fdts(b"\xd0\x0d\xfe\xed" + bytes(40) + make_fdt()))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], 44)

    def test_reject_property_bounds(self):
        blob = bytearray(make_fdt())
        struct.pack_into(">I", blob, 68, 100000)
        with self.assertRaises(ValueError):
            parse_fdt(blob)

    def test_reject_unbalanced_tree(self):
        blob = bytearray(make_fdt())
        struct.pack_into(">I", blob, 56, 2)
        with self.assertRaises(ValueError):
            parse_fdt(blob)

    def test_extract_gzip_tail_and_preserve_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "phone-backup" / "boot.win"
            source.parent.mkdir()
            original = bytes(make_boot(gzip.compress(b"linux") + make_fdt()))
            source.write_bytes(original)
            report = inspect(source, root / "output")
            self.assertEqual(len(report["device_trees"]), 1)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual((root / "output" / "dtb-00.dtb").read_bytes(), make_fdt())
            with self.assertRaises(ValueError):
                inspect(source, root / "output")
            with self.assertRaises(ValueError):
                inspect(source, source.parent / "output")


if __name__ == "__main__":
    unittest.main()
