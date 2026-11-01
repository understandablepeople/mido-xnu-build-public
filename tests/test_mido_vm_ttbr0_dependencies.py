import hashlib
import os
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from tools.mido_vm_activation_audit import TOP, walk
from tools.mido_vm_ttbr0_dependencies import (
    ISLAND, OBSERVER, RECORD, VIRTUAL, PHYSICAL, _final, _span, audit)


MODULE = "tools.mido_vm_ttbr0_dependencies"


class DependencyInputTests(unittest.TestCase):
    def test_malformed_kernel(self):
        for kernel in (b"", b"not a kernel", bytes(4096)):
            with self.subTest(size=len(kernel)), self.assertRaises(ValueError):
                audit(kernel)

    def test_span_bounds(self):
        for address, length, physical in ((ISLAND, 0, PHYSICAL),
                                          (ISLAND, -1, PHYSICAL),
                                          ((1 << 64) - 4, 8, PHYSICAL),
                                          (ISLAND, 8, (1 << 40) - 4)):
            with self.subTest(address=address, length=length), self.assertRaises(ValueError):
                _span(bytes(8192), address, length, physical, False, True)

    def test_snapshot_bounds(self):
        for snapshot in (b"", bytes(4096), bytes(8193)):
            with self.subTest(size=len(snapshot)), self.assertRaises(ValueError):
                _final(snapshot, ISLAND)


class PinnedDependencyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", Path(__file__).resolve().parents[1] /
                                   "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"))
        if not path.exists():
            raise unittest.SkipTest("Pinned native-4K kernel unavailable")
        cls.kernel = path.read_bytes()
        cls.report = audit(cls.kernel)
        from tools.inspect_xnu import inspect
        from tools.mido_vm_physmap_complete_reference import CompletePhysmapReference
        reference = CompletePhysmapReference(inspect(cls.kernel)["segments"],
                                             VIRTUAL, PHYSICAL, TOP, 1)
        reference.physmap = VIRTUAL + TOP - PHYSICAL
        reference.end_kernel = VIRTUAL + 0xf6c000
        cls.snapshot = reference.expected("vm-physmap-before-ttbr")

    def test_report_geometry_and_checkpoint(self):
        report = self.report
        self.assertEqual(report["checkpoint"], 0xfffffff007446a54)
        self.assertEqual([(case["l2_count"], case["slide"]) for case in report["cases"].values()],
                         [(1, 0), (2, 0x3ffff000), (1, 0x37000000)])
        self.assertTrue(report["passed"])
        self.assertTrue(report["offline_only"])
        for key in ("boot_approved", "runtime_verified", "tables_modified",
                    "device_commands_executed", "native_observer_runnable_with_final_ttbr1"):
            self.assertFalse(report[key])
        self.assertEqual(len(report["dependencies"]), 2)

    def test_final_mappings_and_low_absence(self):
        for case in self.report["cases"].values():
            final = case["final"]
            self.assertEqual(final["ttbr0_zero_descriptors"], 512)
            self.assertFalse(final["low_record"]["mapped"])
            self.assertEqual(final["low_record"]["trace"][0]["table"], TOP)
            expected = {"original-execution": (0x11646a54, False, True),
                        "island": (0x11d4ff00, False, True),
                        "stack": (0x11e9bff0, True, False),
                        "vbar": (0x1142c000, False, True),
                        "native-observer": (0x12400000, True, False)}
            for name, values in expected.items():
                span = final["cases"][name]
                self.assertEqual(tuple(span[key] for key in
                                       ("physical", "writable", "executable")), values)
            self.assertEqual(final["cases"]["island"]["end"], ISLAND + 256)
            self.assertEqual(final["cases"]["island"]["samples"][-1]["address"], ISLAND + 255)

    def test_bootstrap_restores_dependencies(self):
        restored = self.report["bootstrap"]["cases"]
        self.assertEqual(restored["low_record"]["physical"], RECORD)
        self.assertTrue(restored["low_record"]["writable"])
        self.assertEqual(restored["native_observer"]["physical"], 0x12400000)
        self.assertTrue(restored["native_observer"]["executable"])

    def test_entire_ttbr0_page_must_be_zero(self):
        for slot in (0, 255, 256, 511):
            snapshot = bytearray(self.snapshot)
            struct.pack_into("<Q", snapshot, slot * 8, 2)
            with self.subTest(slot=slot), self.assertRaisesRegex(ValueError, "512 zero"):
                _final(snapshot, self.report["checkpoint"])

    def test_permission_and_destination_corruption(self):
        for address in (ISLAND, OBSERVER, 0xfffffff007c9bff0, 0xfffffff00722c000):
            leaf = walk(self.snapshot, address)["trace"][-1]
            for mask in (1 << 7, 1 << 53, 1 << 10, 1 << 21):
                snapshot = bytearray(self.snapshot)
                struct.pack_into("<Q", snapshot, leaf["slot"] - TOP, leaf["descriptor"] ^ mask)
                with self.subTest(address=address, mask=mask), self.assertRaises(ValueError):
                    _final(snapshot, self.report["checkpoint"])

    def test_table_outside_snapshot_fails_closed(self):
        root = walk(self.snapshot, ISLAND)["trace"][0]
        snapshot = bytearray(self.snapshot)
        struct.pack_into("<Q", snapshot, root["slot"] - TOP, TOP + len(snapshot) | 3)
        with self.assertRaises(ValueError):
            _final(snapshot, self.report["checkpoint"])

    def test_low_absence_is_independently_required(self):
        def unexpected_low(snapshot, address, **kwargs):
            if address == RECORD:
                return dict(mapped=True)
            return walk(snapshot, address, **kwargs)

        with patch(MODULE + ".walk", side_effect=unexpected_low):
            with self.assertRaisesRegex(ValueError, "Low identity"):
                _final(self.snapshot, self.report["checkpoint"])

    def test_bootstrap_corruption_fails_closed(self):
        with patch(MODULE + ".reference_tables", return_value=bytes(65536)):
            with self.assertRaises(ValueError):
                audit(self.kernel)

    def test_cross_page_span_checks_next_page(self):
        snapshot = bytearray(self.snapshot)
        next_page = walk(snapshot, ISLAND + 256)["trace"][-1]
        struct.pack_into("<Q", snapshot, next_page["slot"] - TOP, 0)
        _span(snapshot, ISLAND, 256, 0x11d4ff00, False, True)
        with self.assertRaises(ValueError):
            _span(snapshot, ISLAND, 257, 0x11d4ff00, False, True)

    def test_readonly_inputs_and_snapshot_digest(self):
        snapshot = bytearray(self.snapshot)
        before = bytes(snapshot)
        result = _final(snapshot, self.report["checkpoint"])
        self.assertEqual(snapshot, before)
        self.assertEqual(result["snapshot_sha256"], hashlib.sha256(before).hexdigest())
        kernel = bytearray(self.kernel)
        audit(kernel)
        self.assertEqual(kernel, self.kernel)

    def test_audit_propagates_model_corruption(self):
        snapshot = bytearray(self.snapshot)
        snapshot[4095] = 1
        with patch(MODULE + ".CompletePhysmapReference.expected", return_value=snapshot):
            with self.assertRaises(ValueError):
                audit(self.kernel)


if __name__ == "__main__":
    unittest.main()
