import hashlib
import os
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from tools.mido_vm_activation_audit import TOP, TCR, VIRTUAL, PHYSICAL, audit, run, walk


class WalkerTests(unittest.TestCase):
    def snapshot(self, level=3, leaf=0x200000 | 0x403):
        pages = bytearray(4 * 4096)
        struct.pack_into("<Q", pages, 0, TOP + 8192 | 3)
        struct.pack_into("<Q", pages, 4096, TOP + 8192 | 3)
        struct.pack_into("<Q", pages, 8192, TOP + 12288 | 3)
        struct.pack_into("<Q", pages, {1: 0, 2: 8192, 3: 12288}[level], leaf)
        return pages

    def test_leaf_attributes_and_both_roots(self):
        pages = self.snapshot(leaf=0x200000 | 0xcff | (1 << 52))
        for address in (0xabc, (1 << 64) - (1 << 38) + 0xabc):
            result = walk(pages, address)
            self.assertEqual(result["physical"], 0x200abc)
            self.assertEqual(result["ap"], 3)
            self.assertFalse(result["writable"])
            self.assertTrue(result["executable"])
            self.assertTrue(result["user_executable"])
            self.assertEqual(result["attr_index"], 7)
            self.assertEqual(result["shareability"], 0)
            self.assertTrue(result["not_global"])
            self.assertTrue(result["non_secure"])
            self.assertTrue(result["contiguous"])

    def test_block_and_page_boundaries(self):
        for level, size in ((1, 1 << 30), (2, 1 << 21), (3, 4096)):
            base = 1 << 30
            pages = self.snapshot(level, base | 0x400 | (3 if level == 3 else 1))
            for offset in (0, size - 1):
                self.assertEqual(walk(pages, offset)["physical"], base + offset)
            self.assertFalse(walk(pages, size)["mapped"])

    def test_table_restrictions_each_level(self):
        for slot in (0, 8192):
            for bit, field in ((59, "executable"), (60, "user_executable"),
                               (61, "user_accessible"), (62, "writable")):
                pages = self.snapshot(leaf=0x200000 | 0x443)
                self.assertTrue(walk(pages, 0)[field])
                word = struct.unpack_from("<Q", pages, slot)[0]
                struct.pack_into("<Q", pages, slot, word | (1 << bit))
                self.assertFalse(walk(pages, 0)[field])

    def test_leaf_execute_and_access_permissions(self):
        for ap in range(4):
            result = walk(self.snapshot(leaf=0x200000 | 0x403 | ap << 6), 0)
            self.assertEqual(result["writable"], ap < 2)
            self.assertEqual(result["user_accessible"], bool(ap & 1))
        for bit, field in ((53, "executable"), (54, "user_executable")):
            result = walk(self.snapshot(leaf=0x200000 | 0x443 | 1 << bit), 0)
            self.assertFalse(result[field])
        result = walk(self.snapshot(leaf=0x200003), 0)
        self.assertTrue(result["mapped"])
        self.assertFalse(result["access_flag"])
        self.assertFalse(result["executable"])
        self.assertFalse(result["writable"])

    def test_corrupt_descriptors_deny_all_permissions(self):
        corruptions = ((0, 0), (0, 2), (0, TOP + 8192 | 7),
                       (0, (1 << 40) | 3), (0, TOP + 16384 | 3),
                       (0, TOP - 4096 | 3), (0, TOP | 3),
                       (8192, TOP + 8192 | 3), (8192, 0x201401),
                       (12288, 0x200401), (12288, 0x200503),
                       (12288, 0x200403 | 1 << 48),
                       (12288, 0x200403 | 1 << 51))
        for slot, value in corruptions:
            with self.subTest(slot=slot, value=hex(value)):
                pages = self.snapshot()
                struct.pack_into("<Q", pages, slot, value)
                result = walk(pages, 0)
                for field in ("mapped", "writable", "executable", "user_accessible",
                              "user_writable", "user_executable"):
                    self.assertFalse(result[field])
                self.assertIsNone(result["physical"])

    def test_geometry_and_canonical_boundaries(self):
        pages = self.snapshot()
        for kwargs in ({"top": TOP + 1}, {"top": -4096}, {"top": 1 << 40},
                       {"tcr": TCR ^ 1}):
            with self.assertRaises(ValueError):
                walk(pages, 0, **kwargs)
        for bad in (b"", pages[:-1], pages[:4096]):
            with self.assertRaises(ValueError):
                walk(bad, 0)
        for address in (-1, 1 << 64, 1 << 38, (1 << 64) - (1 << 38) - 1):
            self.assertEqual(walk(pages, address)["reason"], "noncanonical-address")
        for address in ((1 << 38) - 1, (1 << 64) - 1):
            self.assertEqual(walk(pages, address)["reason"], "unmapped")


class PinnedActivationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tools.inspect_xnu import inspect
        from tools.mido_macho_symbols import macho_symbols
        from tools.mido_native4k_profile import KERNEL_SHA256
        from tools.mido_vm_physmap_complete_reference import CompletePhysmapReference

        cls.path = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", Path(__file__).resolve().parents[1] /
                                      "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"))
        if not cls.path.exists():
            raise unittest.SkipTest("Pinned kernel unavailable")
        kernel = cls.path.read_bytes()
        if hashlib.sha256(kernel).hexdigest() != KERNEL_SHA256:
            raise AssertionError("Pinned kernel SHA256 mismatch")
        cls.site = macho_symbols(kernel)["_arm_vm_init"] + 0x13e4
        cls.snapshots = []
        for count in (1, 2):
            reference = CompletePhysmapReference(inspect(kernel)["segments"], VIRTUAL, PHYSICAL, TOP, count)
            reference.physmap = VIRTUAL + TOP - PHYSICAL
            reference.end_kernel = VIRTUAL + 0xf6c000
            cls.snapshots.append(reference.expected("vm-physmap-before-ttbr"))

    def test_exact_final_permissions_and_no_mutation(self):
        self.assertEqual(self.site, 0xfffffff007446a34)
        expected = {"observer": (0x12400000, True, False, 3),
                    "stack": (0x11e9bff0, True, False, 3),
                    "vbar": (0x1142c000, False, True, 3),
                    "original-execution-site": (0x11646a34, False, True, 2)}
        for snapshot in self.snapshots:
            self.assertEqual(len(snapshot), 59 * 4096)
            mutable = bytearray(snapshot)
            report = audit(mutable, self.site)
            self.assertEqual(mutable, snapshot)
            self.assertEqual(report["blockers"], ["observer", "observer-low-identity"])
            self.assertFalse(report["immediate_switch_safe"])
            for name, values in expected.items():
                result = report["cases"][name]["translation"]
                self.assertEqual(tuple(result[key] for key in
                                       ("physical", "writable", "executable", "leaf_level")), values)
                self.assertFalse(result["user_accessible"])
                self.assertTrue(result["access_flag"])
            low = report["cases"]["observer-low-identity"]["translation"]
            self.assertFalse(low["mapped"])
            self.assertEqual(low["trace"][0]["table"], TOP)

    def test_final_snapshot_corruption_and_truncation(self):
        for snapshot in self.snapshots:
            result = walk(snapshot, 0xfffffff008200000)
            self.assertEqual(walk(snapshot[:-8192], 0xfffffff008200000)["reason"],
                             "table-outside-snapshot")
            for trace in result["trace"][:-1]:
                pages = bytearray(snapshot)
                struct.pack_into("<Q", pages, trace["slot"] - TOP,
                                 TOP + len(snapshot) | 3)
                self.assertEqual(walk(pages, 0xfffffff008200000)["reason"], "table-outside-snapshot")

    def test_runner_matches_independent_input(self):
        report = run(self.path)
        self.assertEqual(report["snapshot_sha256"], hashlib.sha256(self.snapshots[0]).hexdigest())
        self.assertEqual(report["snapshot_pages"], 59)
        self.assertFalse(report["device_commands_executed"])

    def test_runner_rejects_unpinned_kernel(self):
        with patch.object(Path, "read_bytes", return_value=b"not the pinned kernel"):
            with self.assertRaisesRegex(ValueError, "pinned"):
                run(self.path)

    def test_final_mapping_boundaries(self):
        for snapshot in self.snapshots:
            for address, physical in ((0xfffffff007f6c000, 0x1216c000),
                                      (0xfffffff008200000, 0x12400000),
                                      (0xfffffff008200fff, 0x12400fff),
                                      (0xfffffff008400000, 0x11200000),
                                      (0xfffffff008403fff, 0x11203fff),
                                      (0xfffffff008601000, 0x12401000),
                                      (0xfffffff0093fffff, 0x131fffff)):
                result = walk(snapshot, address)
                self.assertTrue(result["mapped"])
                self.assertEqual(result["physical"], physical)
                self.assertTrue(result["writable"])
                self.assertFalse(result["executable"])
            for address in (0xfffffff008201000, 0xfffffff0083fffff,
                            0xfffffff008404000, 0xfffffff008600fff,
                            0xfffffff009400000, 0x12400000, 0x12400fff, 0x12401000):
                self.assertFalse(walk(snapshot, address)["mapped"])


if __name__ == "__main__":
    unittest.main()
