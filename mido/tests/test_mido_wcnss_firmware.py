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
import mido_pronto_stage as STAGE
import mido_pronto_payload as HANDOFF
import adt


class WcnssTests(unittest.TestCase):
    def staging_inputs(self):
        nodes = self.board(STAGE.SIZE)
        nodes["/reserved-memory/wcnss"]["reg"] = struct.pack(">QQ", STAGE.BASE, STAGE.SIZE)
        payload = bytearray(4096)
        payload[:8] = b"SWEETXNU"
        struct.pack_into("<II7Q", payload, 8, 1, 1, 0x100000, 0x100100,
                         800, 128, 0x102000, 0x20000000, 0x100000)
        struct.pack_into("<4Q", payload, 680, 0x100000, 4096, 1000, 128)
        return nodes, payload

    def test_private_staging_preserves_data_and_separate_metadata_without_device_writes(self):
        nodes, payload = self.staging_inputs()
        header, report = STAGE.prepare(self.directory, nodes, payload)
        self.assertIn("mido_pronto_segment_2", header)
        self.assertIn("0x54, 0x45, 0x53, 0x54, 0x43, 0x4f, 0x44, 0x45", header)
        self.assertEqual(report["allocation_bytes"], 8192)
        self.assertEqual(report["metadata_physical"] % 4096, 0)
        self.assertGreaterEqual(report["metadata_physical"], STAGE.BASE + 8192)
        self.assertLessEqual(report["metadata_physical"] + report["metadata_bytes"], STAGE.BASE + STAGE.SIZE)
        for flag in ("hardware_written", "pas_authentication_established", "network_ready"):
            self.assertFalse(report[flag])

    def test_private_staging_rejects_wrong_board_and_kernel_overlap(self):
        nodes, payload = self.staging_inputs()
        struct.pack_into("<Q", payload, 56, STAGE.BASE)
        with self.assertRaisesRegex(ValueError, "overlaps"):
            STAGE.prepare(self.directory, nodes, payload)
        nodes, payload = self.staging_inputs()
        nodes["/reserved-memory/wcnss"]["reg"] = struct.pack(">QQ", STAGE.BASE + 4096, STAGE.SIZE)
        with self.assertRaisesRegex(ValueError, "own mido"):
            STAGE.prepare(self.directory, nodes, payload)

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

    def bundle_inputs(self):
        nodes, payload = self.staging_inputs()
        root = adt.Node()
        root.props = [("name", 0, b"/\0")]
        chosen = adt.Node()
        chosen.props = [("name", 0, b"chosen\0"), ("dram-base", 0, struct.pack("<Q", 0x20000000)),
                        ("dram-size", 0, struct.pack("<Q", 0x100000)), ("keep", 0, b"unchanged")]
        root.children = [chosen]
        blob = adt.serialize(root)
        payload[800:800 + len(blob)] = blob
        struct.pack_into("<Q", payload, 40, len(blob))
        _, report = STAGE.prepare(self.directory, nodes, payload)
        return payload, STAGE.encode_bundle(self.directory, report)

    def test_binary_bundle_handoff_preserves_kernel_and_chosen_properties(self):
        payload, bundle = self.bundle_inputs()
        output, report = HANDOFF.attach(payload, bundle)
        self.assertEqual(output[:32], payload[:32])
        self.assertEqual(output[48:len(payload)], payload[48:])
        offset, size = struct.unpack_from("<QQ", output, 32)
        root, consumed = adt.parse(output[offset:offset + size])
        self.assertEqual(consumed, size)
        self.assertEqual(root.children[0].prop("keep"), b"unchanged")
        self.assertEqual(root.children[0].prop("mido-pronto-bundle"), bundle)
        self.assertFalse(report["device_written"])
        self.assertFalse(report["boot_arguments_changed"])
        with self.assertRaisesRegex(ValueError, "already attached"):
            HANDOFF.attach(output, bundle)

    def test_bundle_attachment_rejects_arena_mismatch_source_overlap_and_bad_count(self):
        payload, bundle = self.bundle_inputs()
        for offset, value in ((8, 0), (12, 33), (32, 0), (48, len(bundle) + 1),
                              (64, struct.unpack_from("<Q", bundle, 32)[0])):
            changed = bytearray(bundle)
            struct.pack_into("<I" if offset < 16 else "<Q", changed, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                HANDOFF.attach(payload, changed)
        struct.pack_into("<Q", payload, 64, 0x200000)
        with self.assertRaisesRegex(ValueError, "disagree"):
            HANDOFF.attach(payload, bundle)

    def board(self, size=8192):
        cell = lambda number: struct.pack(">I", number)
        return {"/soc/qcom,pronto@a21b000": {"qcom,pas-id": cell(6), "memory-region": cell(10)},
                "/soc/qcom,wcnss-wlan@0a000000": {"qcom,is-pronto-v3": b""},
                "/reserved-memory": {"#address-cells": cell(2), "#size-cells": cell(2)},
                "/reserved-memory/wcnss": {"phandle": cell(10), "no-map": b"",
                                            "reg": struct.pack(">QQ", 0x800000, size)}}

    def power_board(self):
        cell = lambda value: struct.pack(">I", value)
        nodes = self.board()
        wlan = nodes["/soc/qcom,wcnss-wlan@0a000000"]
        pronto = nodes["/soc/qcom,pronto@a21b000"]
        specs = [("pronto-vddmx", "smpa", 7, 384, 384, True),
                 ("pronto-vddcx", "smpa", 2, 256, 384, True),
                 ("pronto-vddpx", "ldoa", 5, 1800000, 1800000, False),
                 ("iris-vddxo", "ldoa", 7, 1800000, 1800000, False),
                 ("iris-vddrfa", "ldoa", 19, 1300000, 1300000, False),
                 ("iris-vddpa", "ldoa", 9, 3300000, 3300000, False),
                 ("iris-vdddig", "ldoa", 5, 1800000, 1800000, False)]
        for index, (role, resource, number, low, high, level) in enumerate(specs):
            handle = cell(100 + index)
            parent = "/rpm/" + role
            nodes[parent] = {"qcom,resource-name": resource.encode() + bytes(1),
                             "qcom,resource-id": cell(number)}
            node = {"phandle": handle, "qcom,set": cell(1 if index == 0 else 3),
                    "regulator-min-microvolt": cell(low), "regulator-max-microvolt": cell(high)}
            if level:
                node["qcom,use-voltage-level"] = b""
            nodes[parent + "/rail"] = node
            wlan["qcom," + role + "-supply"] = handle
            wlan["qcom," + role.removeprefix("pronto-") + "-voltage-level"] = struct.pack(">III", low, 0, high)
            wlan["qcom," + role + "-current"] = cell(10000)
        pronto["vdd_pronto_pll-supply"] = wlan["qcom,iris-vddxo-supply"]
        pronto["vdd_pronto_pll-uV-uA"] = struct.pack(">II", 1800000, 18000)
        names = b"xo\0scm_core_clk\0scm_iface_clk\0scm_bus_clk\0scm_core_clk_src\0"
        pronto["clock-names"] = pronto["qcom,proxy-clock-names"] = names
        pronto["clocks"] = b"".join(struct.pack(">II", 200, index) for index in range(5))
        pronto["qcom,scm_core_clk_src"] = cell(80000000)
        nodes["/clock"] = {"phandle": cell(200), "#clock-cells": cell(1)}
        return nodes

    def test_power_plan_preserves_level_vs_microvolt_units_and_proxy_references(self):
        result = FIRMWARE.inspect_power_dependencies(self.power_board())
        self.assertEqual(len(result["supplies"]), 7)
        self.assertEqual(result["supplies"][0]["voltage_units"], "rpm-level")
        self.assertEqual(result["supplies"][1]["resource_id"], 2)
        self.assertEqual(result["supplies"][3]["voltage_units"], "microvolt")
        self.assertEqual(result["scm_core_rate_hz"], 80000000)
        self.assertEqual(len(result["clocks"]), 5)
        self.assertEqual(result["shared_supply_groups"], [{"resource": "ldoa", "resource_id": 5,
                         "roles": ["pronto-vddpx", "iris-vdddig"]}])
        self.assertFalse(result["hardware_accessed"])
        self.assertTrue(result["requires_shared_supply_vote_aggregation"])

    def test_power_plan_rejects_bad_constraints_ambiguous_phandle_and_proxy(self):
        nodes = self.power_board()
        nodes["/rpm/pronto-vddcx/rail"]["regulator-max-microvolt"] = struct.pack(">I", 255)
        with self.assertRaisesRegex(ValueError, "supply constraints"):
            FIRMWARE.inspect_power_dependencies(nodes)
        nodes = self.power_board()
        nodes["/duplicate"] = dict(nodes["/rpm/iris-vddxo/rail"])
        with self.assertRaisesRegex(ValueError, "not unique"):
            FIRMWARE.inspect_power_dependencies(nodes)
        nodes = self.power_board()
        nodes["/soc/qcom,pronto@a21b000"]["vdd_pronto_pll-supply"] = struct.pack(">I", 100)
        with self.assertRaisesRegex(ValueError, "supply differ"):
            FIRMWARE.inspect_power_dependencies(nodes)
        nodes = self.power_board()
        nodes["/soc/qcom,pronto@a21b000"]["qcom,proxy-clock-names"] = b"unknown\0"
        with self.assertRaisesRegex(ValueError, "proxy clock"):
            FIRMWARE.inspect_power_dependencies(nodes)

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
