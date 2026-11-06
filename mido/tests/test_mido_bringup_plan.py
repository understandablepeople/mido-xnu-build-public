import importlib.util
from pathlib import Path
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location("mido_bringup_plan", ROOT / "tools/mido_bringup_plan.py")
PLAN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLAN)


class BringupPlanTests(unittest.TestCase):
    def supply(self, minimum, maximum=384, sets=1, units="rpm-level"):
        return {"role": "test", "resource": "smpa", "resource_id": 2, "sets": sets,
                "voltage_units": units, "minimum": minimum, "maximum": maximum}

    def test_shared_floor_never_reduces_existing_gpu_vote(self):
        votes = PLAN.aggregate_supplies([self.supply(256)], [self.supply(192)])
        self.assertEqual(len(votes), 1)
        self.assertEqual(votes[0]["minimum"], 256)
        votes = PLAN.aggregate_supplies([self.supply(256)], [self.supply(320)])
        self.assertEqual(votes[0]["minimum"], 320)

    def test_active_and_sleep_sets_are_aggregated_separately(self):
        votes = PLAN.aggregate_supplies([self.supply(256, sets=3), self.supply(320)])
        self.assertEqual([(vote["set"], vote["minimum"]) for vote in votes], [(1, 320), (2, 256)])

    def test_conflicting_units_limits_or_sets_rejected(self):
        cases = [[self.supply(256), self.supply(1800000, 1800000, units="microvolt")],
                 [self.supply(256), self.supply(192, 192)], [self.supply(0)],
                 [self.supply(384, 256)], [self.supply(256, sets=2)]]
        for supplies in cases:
            with self.subTest(supplies=supplies), self.assertRaises(ValueError):
                PLAN.aggregate_supplies(supplies)

    def test_reservation_overlap_edges_and_invalid_extents(self):
        self.assertTrue(PLAN.check_reservation(0x8000, 0x2000, [("before", 0x6000, 0x2000), ("after", 0xa000, 1)]))
        for occupied in [[("inside", 0x8000, 1)], [("tail", 0x9fff, 2)], [("cover", 0x7000, 0x4000)]]:
            with self.assertRaises(ValueError):
                PLAN.check_reservation(0x8000, 0x2000, occupied)
        for base, size in [(1, 4096), (4096, 0), (0xfffff000, 8192), (4096, 1)]:
            with self.assertRaises(ValueError):
                PLAN.check_reservation(base, size, [])

    def payload(self):
        payload = bytearray(4096)
        payload[:8] = b"SWEETXNU"
        struct.pack_into("<II7Q", payload, 8, 1, 1, 0x100000, 0x100100,
                         800, 128, 0x102000, 0x20000000, 0x100000)
        struct.pack_into("<4Q", payload, 680, 0x100000, 4096, 1000, 128)
        return payload

    def test_payload_arena_and_invalid_tables(self):
        payload = self.payload()
        self.assertEqual(PLAN.payload_ranges(payload), [("XNU arena including boot data", 0x20000000, 0x100000)])
        for offset, value in [(8, 2), (12, 0), (32, 4097), (48, 0x200000), (680, 0x80000), (696, 4097), (704, 4097)]:
            bad = self.payload()
            struct.pack_into("<I" if offset < 16 else "<Q", bad, offset, value)
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                PLAN.payload_ranges(bad)
