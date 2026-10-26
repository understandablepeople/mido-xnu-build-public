import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import pack_screen_test as packer
from inspect_boot import parse_boot, parse_fdt


def payload_fixture():
    payload = bytearray(8192)
    struct.pack_into("<IIQQQ", payload, 0, 0x14000010, 0xD503201F, 0x80000, len(payload), 0)
    struct.pack_into("<I", payload, 44, len(payload))
    payload[56:60] = b"ARM\x64"
    return bytes(payload)


def reference_fixture():
    names = b"qcom,msm-id\0qcom,board-id\0"
    structure = struct.pack(">I", 1) + bytes(4)
    structure += struct.pack(">IIIII", 3, 8, 0, 293, 0)
    structure += struct.pack(">IIIII", 3, 8, 12, 11, 0)
    structure += struct.pack(">II", 2, 9)
    header = struct.pack(">10I", 0xD00DFEED, 56 + len(structure) + len(names), 56,
                         56 + len(structure), 40, 17, 16, 0, len(names), len(structure))
    return header + bytes(16) + structure + names


class ScreenPackagingTests(unittest.TestCase):
    def setUp(self):
        self.reference = reference_fixture()
        self.pin = patch.object(packer, "RECOVERY_DTB_SHA256", hashlib.sha256(self.reference).hexdigest())
        self.pin.start()
        self.addCleanup(self.pin.stop)

    def test_minimal_tree_does_not_fabricate_framebuffer(self):
        tree = parse_fdt(packer.make_tree(self.reference))
        self.assertEqual(set(tree["nodes"]), {"/", "/memory", "/chosen", "/reserved-memory"})
        self.assertEqual(tree["nodes"]["/"]["compatible"], b"mido,arm64-screen-test\0")
        self.assertNotIn("reg", tree["nodes"]["/reserved-memory"])

    def test_reference_hash_required(self):
        with self.assertRaises(ValueError):
            packer.make_tree(self.reference + b"changed")

    def test_wrong_device_rejected_even_if_hash_pinned(self):
        changed = self.reference.replace(struct.pack(">II", 293, 0), struct.pack(">II", 294, 0))
        with patch.object(packer, "RECOVERY_DTB_SHA256", hashlib.sha256(changed).hexdigest()):
            with self.assertRaises(ValueError):
                packer.make_tree(changed)

    def test_boot_round_trip(self):
        payload = payload_fixture()
        tree = packer.make_tree(self.reference)
        image = packer.make_image(payload, tree)
        header, parts = parse_boot(image)
        self.assertEqual(parts["kernel"], payload + tree)
        self.assertEqual(parts["ramdisk"], b"")
        self.assertEqual(parts["second"], b"")
        self.assertEqual(header["page_size"], 2048)
        self.assertEqual(header["kernel_address"], "0x10080000")
        self.assertIn(b"lk2nd.pass-simplefb=keep", image[:2048])
        self.assertNotIn(b"androidboot", image[:2048])

    def test_invalid_payload_fields_rejected(self):
        for offset in (0, 8, 16, 24, 44, 56):
            with self.subTest(offset=offset):
                payload = bytearray(payload_fixture())
                payload[offset] ^= 1
                with self.assertRaises(ValueError):
                    packer.validate_payload(payload)

    def test_invalid_payload_lengths_rejected(self):
        for length in (0, 63, 4095, 8191, 65536):
            with self.subTest(length=length):
                with self.assertRaises(ValueError):
                    packer.validate_payload(bytes(length))

    def test_bad_tree_rejected(self):
        with self.assertRaises(ValueError):
            packer.make_image(payload_fixture(), b"not a DTB")

    def test_diagnostics_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload_path = root / "payload.bin"
            reference_path = root / "reference.dtb"
            payload_path.write_bytes(payload_fixture())
            reference_path.write_bytes(self.reference)
            report = packer.package(payload_path, reference_path, root / "package", diagnostics=True)
            self.assertTrue(report["diagnostics"])
            self.assertIn("exceptions/counter", report["purpose"])
            self.assertFalse(report["device_commands_executed"])

    def test_package_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload_path = root / "payload.bin"
            reference_path = root / "reference.dtb"
            payload_path.write_bytes(payload_fixture())
            reference_path.write_bytes(self.reference)
            output = root / "package"
            report = packer.package(payload_path, reference_path, output)
            image = (output / "mido-arm64-screen-test.img").read_bytes()
            self.assertEqual(report["image_sha256"], hashlib.sha256(image).hexdigest())
            self.assertFalse(report["device_commands_executed"])
            with self.assertRaises(ValueError):
                packer.package(payload_path, reference_path, output)
            self.assertEqual((output / "mido-arm64-screen-test.img").read_bytes(), image)


if __name__ == "__main__":
    unittest.main()
