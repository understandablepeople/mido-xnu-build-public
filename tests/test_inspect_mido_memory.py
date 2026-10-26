from copy import deepcopy
import struct
import unittest

from tools.inspect_mido_memory import inspect_tree, inspect_blob


def cells(*values):
    return struct.pack(f">{len(values)}I", *values)


def tree():
    return {"reservations": [], "nodes": {
        "/": {"#address-cells": cells(2), "#size-cells": cells(2)},
        "/memory": {"device_type": b"memory\0", "reg": cells(0, 0x10000000, 0, 0x70000000)},
        "/reserved-memory": {"#address-cells": cells(2), "#size-cells": cells(2), "ranges": b""},
        "/reserved-memory/fixed": {"reg": cells(0, 0x20000000, 0, 0x100000), "no-map": b""},
        "/reserved-memory/pool": {"size": cells(0, 0x800000), "alignment": cells(0, 0x400000),
                                  "alloc-ranges": cells(0, 0x30000000, 0, 0x10000000), "reusable": b""},
    }}


class MemoryInventoryTests(unittest.TestCase):
    def test_static_dynamic_and_no_boot_approval(self):
        result = inspect_tree(tree())
        self.assertEqual(result["declared_ram_bytes"], 0x70000000)
        self.assertEqual(result["ram_banks"][0]["end_exclusive"], 0x80000000)
        self.assertEqual(result["fixed_reservations"][0]["start"], 0x20000000)
        self.assertEqual(len(result["fixed_reservations"]), 1)
        self.assertEqual(result["unresolved_reservations"][0]["requested_bytes"], 0x800000)
        self.assertIn("allocation_constraints_not_reservations", result["unresolved_reservations"][0])
        self.assertIsNone(result["recommended_load_address"])
        self.assertIsNone(result["usable_memory_ranges"])
        self.assertFalse(result["boot_approved"])
        self.assertFalse(result["platform_memory_approved"])

    def test_fdt_reservation_map_and_overlapping_exclusions(self):
        source = tree()
        source["reservations"] = [{"address": "0x20000000", "size": "0x200000"}]
        self.assertEqual(inspect_tree(source)["fixed_reserved_union_bytes"], 0x200000)

    def test_disabled_fixed_region_is_not_reclaimed(self):
        source = tree()
        source["nodes"]["/reserved-memory/fixed"]["status"] = b"disabled\0"
        result = inspect_tree(source)
        self.assertEqual(len(result["fixed_reservations"]), 1)
        self.assertEqual(len(result["inactive_reservation_nodes"]), 1)

    def test_vendor_zero_base_is_unresolved(self):
        source = tree()
        source["nodes"]["/reserved-memory/legacy"] = {
            "reg": cells(0, 0, 0, 0x1200000), "linux,reserve-contiguous-region": b""}
        result = inspect_tree(source)
        self.assertEqual(len(result["fixed_reservations"]), 1)
        self.assertTrue(any("vendor zero-base" in entry["reason"] for entry in result["unresolved_reservations"]))

    def test_ram_overlap_and_nested_memory_rejected(self):
        for path in ("/memory@10000000", "/soc/memory"):
            source = tree()
            source["nodes"][path] = deepcopy(source["nodes"]["/memory"])
            with self.subTest(path=path), self.assertRaises(ValueError):
                inspect_tree(source)

    def test_nonidentity_ranges_and_width_mismatch_rejected(self):
        for key, raw in (("ranges", cells(0)), ("#address-cells", cells(1)), ("#size-cells", cells(3))):
            source = tree()
            source["nodes"]["/reserved-memory"][key] = raw
            with self.subTest(key=key), self.assertRaises(ValueError):
                inspect_tree(source)

    def test_truncated_or_zero_ranges_rejected(self):
        for raw in (b"", cells(0, 1, 0), cells(0, 1, 0, 0), cells(0xffffffff, 0xfffffff0, 0, 32)):
            source = tree()
            source["nodes"]["/memory"]["reg"] = raw
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                inspect_tree(source)

    def test_dynamic_alignment_and_size_validation(self):
        for key, raw in (("alignment", cells(0, 3)), ("alignment", cells(0, 0)),
                         ("size", cells(0)), ("size", cells(0, 0)), ("alloc-ranges", cells(1))):
            source = tree()
            source["nodes"]["/reserved-memory/pool"][key] = raw
            with self.subTest(key=key, raw=raw), self.assertRaises(ValueError):
                inspect_tree(source)

    def test_no_map_reusable_contradiction_and_bad_boolean(self):
        for change in ({"reusable": b""}, {"no-map": cells(1)}):
            source = tree()
            source["nodes"]["/reserved-memory/fixed"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                inspect_tree(source)

    def test_outside_ram_is_recorded_not_relocated(self):
        source = tree()
        source["reservations"] = [{"address": "0x90000000", "size": "0x1000"}]
        result = inspect_tree(source)
        self.assertEqual(len(result["fixed_reservations_not_contained_in_one_bank"]), 1)
        self.assertFalse(result["platform_memory_approved"])

    def test_multiple_reg_tuples_and_32_bit_cells(self):
        source = tree()
        source["nodes"] = {
            "/": {"#address-cells": cells(1), "#size-cells": cells(1)},
            "/memory": {"device_type": b"memory\0", "reg": cells(0x10000000, 4096, 0x20000000, 8192)},
        }
        self.assertEqual(inspect_tree(source)["declared_ram_bytes"], 12288)

    def test_missing_or_disabled_ram_is_rejected(self):
        source = tree()
        source["nodes"]["/memory"]["status"] = b"disabled\0"
        with self.assertRaises(ValueError):
            inspect_tree(source)

    def test_bad_fdt_rejected(self):
        with self.assertRaises(ValueError):
            inspect_blob(b"not an FDT")


if __name__ == "__main__":
    unittest.main()
