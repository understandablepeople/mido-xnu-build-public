import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("mido_wcnss_firmware",
                                            ROOT / "tools/mido_wcnss_firmware.py")
FIRMWARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(FIRMWARE)


class WcnssTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        ident = bytes.fromhex("7f454c46010101") + bytes(9)
        self.header = struct.pack("<16sHHIIIIIHHHHHH", ident, 2, 40, 1,
                                  0x1000, 52, 0, 0, 52, 32, 4, 0, 0, 0)
        self.programs = [(0, 0, 0, 0, 180, 0, 0x07000000, 0),
                         (0, 4096, 0, 0, 8, 8, 0x02200000, 4096),
                         (1, 8192, 0x1000, 0x1000, 8, 16, 0x08000007, 4096),
                         (1, 8200, 0x2000, 0x2000, 0, 4096, 0x08000006, 4096)]
        self.write_metadata()
        (self.directory / "wcnss.b01").write_bytes(b"TESTHASH")
        (self.directory / "wcnss.b02").write_bytes(b"TESTCODE")

    def write_metadata(self):
        table = self.header + b"".join(struct.pack("<8I", *item) for item in self.programs)
        (self.directory / "wcnss.mdt").write_bytes(table + b"TESTHASH")
        (self.directory / "wcnss.b00").write_bytes(table)

    def board(self, size=8192):
        cell = lambda number: struct.pack(">I", number)
        return {"/soc/qcom,pronto@a21b000": {"qcom,pas-id": cell(6), "memory-region": cell(10)},
                "/soc/qcom,wcnss-wlan@0a000000": {"qcom,is-pronto-v3": b""},
                "/reserved-memory": {"#address-cells": cell(2), "#size-cells": cell(2)},
                "/reserved-memory/wcnss": {"phandle": cell(10), "no-map": b"",
                                            "reg": struct.pack(">QQ", 0x800000, size)}}

    def test_relocation_plan_preserves_holes_and_bss_without_accessing_device(self):
        result = FIRMWARE.inspect_board(self.board(), FIRMWARE.inspect_bundle(self.directory))
        self.assertEqual(result["relocation_delta"], 0x7ff000)
        self.assertEqual(result["segments"][0]["destination"], 0x800000)
        self.assertEqual(result["segments"][1]["destination"], 0x801000)
        self.assertEqual(result["segments"][1]["zero_bytes"], 4096)
        self.assertFalse(result["hardware_accessed"])

    def test_rejects_short_board_reservation(self):
        with self.assertRaisesRegex(ValueError, "exceeds"):
            FIRMWARE.inspect_board(self.board(4096), FIRMWARE.inspect_bundle(self.directory))

    def test_rejects_wrong_pas_or_missing_no_map(self):
        nodes = self.board()
        nodes["/soc/qcom,pronto@a21b000"]["qcom,pas-id"] = struct.pack(">I", 13)
        with self.assertRaisesRegex(ValueError, "PAS6"):
            FIRMWARE.inspect_board(nodes, FIRMWARE.inspect_bundle(self.directory))
        nodes = self.board()
        del nodes["/reserved-memory/wcnss"]["no-map"]
        with self.assertRaisesRegex(ValueError, "no-map"):
            FIRMWARE.inspect_board(nodes, FIRMWARE.inspect_bundle(self.directory))

    def test_zero_fill_and_allocation_are_not_a_loaded_radio(self):
        result = FIRMWARE.inspect_bundle(self.directory)
        self.assertEqual(result["pas_id"], 6)
        self.assertEqual(result["zero_fill_bytes"], 4104)
        self.assertEqual(result["allocation_bytes"], 8192)
        self.assertIsNone(result["segments"][1]["file"])
        for field in ("signature_verified", "hardware_loaded", "network_ready"):
            self.assertFalse(result[field])

    def test_rejects_wrong_architecture(self):
        self.header = self.header[:18] + struct.pack("<H", 164) + self.header[20:]
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, "ARM executable"):
            FIRMWARE.inspect_bundle(self.directory)

    def test_rejects_overlap(self):
        self.programs[3] = (1, 8200, 0x1008, 0x1008, 0, 4096, 0x08000006, 4)
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            FIRMWARE.inspect_bundle(self.directory)

    def test_rejects_missing_payload(self):
        (self.directory / "wcnss.b02").unlink()
        with self.assertRaises(FileNotFoundError):
            FIRMWARE.inspect_bundle(self.directory)

    def test_rejects_mismatched_authentication(self):
        (self.directory / "wcnss.b01").write_bytes(b"BAD_HASH")
        with self.assertRaisesRegex(ValueError, "authentication data"):
            FIRMWARE.inspect_bundle(self.directory)

    def test_rejects_nonrelocatable_payload(self):
        self.programs[2] = (1, 8192, 0x1000, 0x1000, 8, 16, 7, 4096)
        self.write_metadata()
        with self.assertRaisesRegex(ValueError, "relocatable"):
            FIRMWARE.inspect_bundle(self.directory)
