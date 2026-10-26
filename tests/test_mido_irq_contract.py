from copy import deepcopy
import struct
import unittest

from tools.mido_irq_contract import inspect_nodes


def cells(*values):
    return struct.pack(f">{len(values)}I", *values)


def nodes():
    return {
        "/": {"compatible": b"qcom,msm8953\0", "#address-cells": cells(2), "interrupt-parent": cells(1)},
        "/soc": {"#address-cells": cells(1), "#size-cells": cells(1), "ranges": cells(0, 0, 0, 0xFFFFFFFF)},
        "/soc/gic": {"compatible": b"qcom,msm-qgic2\0", "#interrupt-cells": cells(3), "phandle": cells(209),
                     "interrupt-parent": cells(209), "reg": cells(0x0B000000, 4096, 0x0B002000, 4096)},
        "/soc/mpm": {"compatible": b"qcom,mpm-gic\0", "#interrupt-cells": cells(3), "phandle": cells(1), "interrupt-parent": cells(209)},
        "/soc/timer": {"compatible": b"arm,armv8-timer\0", "clock-frequency": cells(19200000),
                       "interrupts": cells(1, 2, 0xFF08, 1, 3, 0xFF08, 1, 4, 0xFF08, 1, 1, 0xFF08)},
    }


class IrqContractTests(unittest.TestCase):
    def test_inherited_mpm_chain_and_timer_order(self):
        result = inspect_nodes(nodes())
        self.assertEqual(result["parent_route"], ["/soc/mpm", "/soc/gic"])
        self.assertEqual(result["virtual_timer_intid_candidate"], 20)
        self.assertEqual(result["dt_frequency_hz"], 19200000)
        self.assertFalse(result["hardware_route_verified"])
        self.assertFalse(result["boot_approved"])

    def test_direct_timer_parent(self):
        tree = nodes()
        tree["/soc/timer"]["interrupt-parent"] = cells(209)
        self.assertEqual(inspect_nodes(tree)["parent_route"], ["/soc/gic"])

    def test_unreviewed_bridge(self):
        tree = nodes()
        tree["/soc/mpm"]["compatible"] = b"unknown,bridge\0"
        with self.assertRaisesRegex(ValueError, "unreviewed intermediate"):
            inspect_nodes(tree)

    def test_parent_cycles_and_unresolved_links(self):
        for parent in (1, 12345):
            tree = nodes()
            tree["/soc/mpm"]["interrupt-parent"] = cells(parent)
            with self.subTest(parent=parent), self.assertRaises(ValueError):
                inspect_nodes(tree)

    def test_duplicate_or_inconsistent_phandles(self):
        for change in ({"phandle": cells(209)}, {"linux,phandle": cells(2)}, {"phandle": cells(0)}):
            tree = nodes()
            tree["/soc/mpm"].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                inspect_nodes(tree)

    def test_ambiguous_timer_nodes(self):
        tree = nodes()
        tree["/soc/other-timer"] = deepcopy(tree["/soc/timer"])
        with self.assertRaisesRegex(ValueError, "exactly one"):
            inspect_nodes(tree)

    def test_bad_ppi_or_trigger(self):
        for kind, number, flags in ((0, 4, 0xFF08), (1, 16, 0xFF08), (1, 4, 1), (1, 4, 0x10008)):
            tree = nodes()
            raw = bytearray(tree["/soc/timer"]["interrupts"])
            raw[24:36] = cells(kind, number, flags)
            tree["/soc/timer"]["interrupts"] = bytes(raw)
            with self.subTest(kind=kind, number=number, flags=flags), self.assertRaises(ValueError):
                inspect_nodes(tree)

    def test_wrong_order_or_truncated_interrupts(self):
        for change in ({"interrupt-names": b"virt\0phys\0"}, {"interrupts": cells(1, 4, 8)}):
            tree = nodes()
            tree["/soc/timer"].update(change)
            with self.assertRaises(ValueError):
                inspect_nodes(tree)

    def test_zero_frequency_or_disabled_node(self):
        for path, change in (("/soc/timer", {"clock-frequency": cells(0)}), ("/soc/mpm", {"status": b"disabled\0"})):
            tree = nodes()
            tree[path].update(change)
            with self.assertRaises(ValueError):
                inspect_nodes(tree)

    def test_unreviewed_bus_translation(self):
        tree = nodes()
        tree["/soc"]["ranges"] = b""
        with self.assertRaisesRegex(ValueError, "bus translation"):
            inspect_nodes(tree)

    def test_overlapping_or_short_register_windows(self):
        for register in (cells(0x0B000000, 4096, 0x0B000000, 4096), cells(0x0B000000, 128, 0x0B002000, 4096)):
            tree = nodes()
            tree["/soc/gic"]["reg"] = register
            with self.assertRaises(ValueError):
                inspect_nodes(tree)

    def test_foreign_device_or_interrupt_mapping(self):
        tree = nodes()
        tree["/"]["compatible"] = b"qcom,another-device\0"
        with self.assertRaises(ValueError):
            inspect_nodes(tree)
        tree = nodes()
        tree["/soc/mpm"]["interrupt-map"] = b""
        with self.assertRaises(ValueError):
            inspect_nodes(tree)


if __name__ == "__main__":
    unittest.main()
