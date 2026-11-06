import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mido_gpu_firmware", ROOT / "tools/mido_gpu_firmware.py")
FIRMWARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIRMWARE)


class FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        ident = bytes.fromhex("7f454c46010101") + bytes(9)
        self.header = FIRMWARE.ELF_HEADER.pack(
            ident, 2, 164, 1, 0x5000, 52, 0, 3, 52, 32, 3, 0, 0, 0)
        self.programs = [
            (0, 0, 0, 0, 148, 0, 0x07000000, 0),
            (0, 4096, 0x7000, 0x7000, 8, 8192, 0x02200000, 4096),
            (1, 12288, 0x5000, 0x5000, 8, 16, 0x08000007, 1048576)]
        self.write_metadata()
        (self.directory / "a506_zap.b01").write_bytes(b"TESTHASH")
        (self.directory / "a506_zap.b02").write_bytes(b"TESTCODE")
        for name in ("a530_pfp.fw", "a530_pm4.fw"):
            (self.directory / name).write_bytes(bytes(16))

    def write_metadata(self):
        table = self.header + b"".join(struct.pack("<8I", *program) for program in self.programs)
        (self.directory / "a506_zap.mdt").write_bytes(table + b"TESTHASH")
        (self.directory / "a506_zap.b00").write_bytes(table)

    def test_valid_bundle_is_not_claimed_authenticated_or_loaded(self):
        result = FIRMWARE.inspect_bundle(self.directory)
        self.assertFalse(result["signature_verified"])
        self.assertFalse(result["hardware_loaded"])
        self.assertEqual(result["pas_id"], 13)
        self.assertEqual(result["segments"][0]["memory_size"], 16)
        self.assertTrue(result["segments"][0]["relocatable"])
        self.assertEqual(len(result["files"]), 6)

    def test_rejects_truncated_metadata(self):
        (self.directory / "a506_zap.mdt").write_bytes(self.header[:24])
        with self.assertRaisesRegex(ValueError, "Truncated"):
            FIRMWARE.inspect_bundle(self.directory)

    def test_rejects_wrong_architecture(self):
        metadata = bytearray((self.directory / "a506_zap.mdt").read_bytes())
        struct.pack_into("<H", metadata, 18, 40)
        (self.directory / "a506_zap.mdt").write_bytes(metadata)
        with self.assertRaisesRegex(ValueError, "Hexagon"):
            FIRMWARE.inspect_bundle(self.directory)

    def test_rejects_short_segment(self):
        (self.directory / "a506_zap.b02").write_bytes(b"SHORT")
        with self.assertRaisesRegex(ValueError, "size mismatch"):
            FIRMWARE.inspect_bundle(self.directory)

    def test_rejects_changed_authentication(self):
        (self.directory / "a506_zap.b01").write_bytes(b"BAD_HASH")
        with self.assertRaisesRegex(ValueError, "authentication data"):
            FIRMWARE.inspect_bundle(self.directory)

    def test_rejects_changed_split_header(self):
        (self.directory / "a506_zap.b00").write_bytes(bytes(148))
        with self.assertRaisesRegex(ValueError, "ELF header differs"):
            FIRMWARE.inspect_bundle(self.directory)

    def test_rejects_file_larger_than_memory(self):
        self.programs[2] = (1, 12288, 0x5000, 0x5000, 8, 4, 0x08000007, 1048576)
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, "extent"):
            FIRMWARE.inspect_bundle(self.directory)

    def test_rejects_unaligned_microcode_length(self):
        (self.directory / "a530_pfp.fw").write_bytes(bytes(9))
        with self.assertRaisesRegex(ValueError, "word layout"):
            FIRMWARE.inspect_bundle(self.directory)

    def test_missing_segment_does_not_use_another_chip_firmware(self):
        (self.directory / "a506_zap.b02").unlink()
        (self.directory / "a530_zap.b02").write_bytes(b"TESTCODE")
        with self.assertRaises(FileNotFoundError):
            FIRMWARE.inspect_bundle(self.directory)


if __name__ == "__main__":
    unittest.main()
