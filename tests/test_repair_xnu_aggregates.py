import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.repair_xnu_aggregates import (SOURCE_HASHES, repair_aggregate, repair_allocation_site,
                                        repair_power_states, repair_perf_control, stage_aggregate_repairs,
                                        repair_heap_view, repair_report_channels)


class AggregateRepairTests(unittest.TestCase):
    def test_unknown_source_rejected_for_every_profile(self):
        self.assertEqual(len(SOURCE_HASHES), 8)
        for relative in SOURCE_HASHES:
            with self.subTest(relative=relative):
                with self.assertRaisesRegex(ValueError, "aggregate repair source"):
                    repair_aggregate(relative, b"unreviewed")

    def test_allocation_site_preserves_refcount_and_handles_both_peak_layouts(self):
        data = (b"#define VM_ALLOC_SITE_TAG() ({ " + bytes((92,)) + b"\n"
                b"static vm_allocation_site_t site = { .refcount = 2, };\n")
        result = repair_allocation_site(data)
        self.assertEqual(result.count(b".refcount = 2"), 1)
        self.assertEqual(result.count(b"#if DEBUG || DEVELOPMENT"), 1)
        self.assertEqual(result.count(b".peak = 0"), 1)
        for field in (b"total", b"mapped", b"tag", b"flags", b"subtotalscount"):
            self.assertIn(b"." + field + b" = 0", result)
        self.assertIn(b".subtotals = {}", result)
        self.assertIn(b"#ifdef __cplusplus\n#define VM_ALLOC_SITE_SUBTOTALS_INITIALIZER", result)
        with self.assertRaisesRegex(ValueError, "allocation site"):
            repair_allocation_site(data + data)

    def test_power_state_repairs_are_limited_to_the_reviewed_table(self):
        state = b"{ .version = 1, .inputPowerRequirement = POWER }"
        data = b"before " + state + b"\nTABLE = {\n" + state + b",\n};\nafter " + state
        result = repair_power_states(data, b"TABLE = {", 1)
        self.assertTrue(result.startswith(b"before " + state))
        self.assertTrue(result.endswith(b"after " + state))
        self.assertEqual(result.count(b".staticPower = 0"), 1)
        self.assertIn(b".inputPowerRequirement = POWER,", result)
        for field in (b"stateOrder", b"powerToAttain", b"timeToAttain", b"settleUpTime",
                      b"timeToLower", b"settleDownTime", b"powerDomainBudget"):
            self.assertIn(b"." + field + b" = 0", result)
        with self.assertRaisesRegex(ValueError, "initializer count"):
            repair_power_states(data, b"TABLE = {", 2)

    def test_performance_defaults_keep_existing_callbacks_and_started_values(self):
        interface = b"callback_stays();\n\t\t};\n\n\t\tshared->interfaceLock = IOLockAlloc();\n"
        complete = (b"PerfControllerInterface::WorkState state{\n"
                    b".started = context->started,\n.driver_state = &clientData.driverState\n};\n")
        missing = b"PerfControllerInterface::WorkState state{\n.driver_state = &clientData.driverState\n};\n"
        data = interface + complete * 8 + missing
        result = repair_perf_control(data)
        self.assertEqual(result.count(b"callback_stays();"), 1)
        self.assertEqual(result.count(b".registerDriverDevice = nullptr"), 1)
        self.assertEqual(result.count(b".unregisterDriverDevice = nullptr"), 1)
        self.assertEqual(result.count(b".started = context->started"), 8)
        self.assertEqual(result.count(b".started = false"), 1)
        self.assertEqual(result.count(b".reserved = 0"), 9)
        self.assertLess(result.index(b".reserved = 0"), result.index(b".driver_state"))
        for invalid in (interface + complete * 9, interface + complete * 7 + missing,
                        data.replace(b".driver_state", b".reserved")):
            with self.assertRaises(ValueError):
                repair_perf_control(invalid)

    def test_heap_view_defaults_preserve_runtime_initialization_and_macro_continuations(self):
        continuation = bytes((32, 92, 10, 9))
        block = continuation.join((b"#define KALLOC_HEAP_DEFINE(var, name, heap_id)",
                                   b"SECURITY_READ_ONLY_LATE(struct kalloc_heap) var[1] = { {",
                                   b"    .kh_name = (name),", b"    .kh_heap_id = (heap_id),",
                                   b"} };", b"STARTUP_ARG(ZALLOC, STARTUP_RANK_LAST, kheap_startup_init, var)"))
        data = b"untouched\n" + block + b"\n\nafter\n"
        result = repair_heap_view(data)
        for field in (b"kh_stats = NULL", b"kh_tag = 0", b"kh_type_hash = 0",
                      b"kh_zstart = 0", b"kh_views = NULL"):
            self.assertEqual(result.count(b"." + field + b","), 1)
        self.assertIn(b".kh_name = (name),", result)
        self.assertIn(b".kh_heap_id = (heap_id),", result)
        self.assertTrue(result.endswith(b"kheap_startup_init, var)\n\nafter\n"))
        self.assertEqual(result.count(continuation), block.count(continuation) + 5)
        for invalid in (data + data, data.replace(b".kh_name", b".kh_stats"), result):
            with self.assertRaisesRegex(ValueError, "heap view"):
                repair_heap_view(invalid)

    def test_report_defaults_preserve_all_values_and_reject_partial_or_repeated_repairs(self):
        block = (b"IOReportChannelType channelType = {\n\t\t.categories = categories,\n"
                 b"\t\t.report_format = FORMAT,\n\t\t.nelements = nstates,\n"
                 b"\t\t.element_idx = 0\n\t};\n")
        result = repair_report_channels(b"before\n" + block * 2 + b"after\n")
        self.assertEqual(result.count(b".reserved = 0,"), 2)
        self.assertIn(b".report_format = FORMAT,\n\t\t.reserved = 0,", result)
        self.assertEqual(result.replace(b"\n\t\t.reserved = 0,", b""), b"before\n" + block * 2 + b"after\n")
        for invalid in (block, block * 3, result, (block * 2).replace(b".report_format", b".reserved")):
            with self.assertRaisesRegex(ValueError, "report channel"):
                repair_report_channels(invalid)

    def test_staging_validates_all_inputs_before_writing_any(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "first.c").write_bytes(b"original")
            (source / "second.c").write_bytes(b"bad")
            profiles = {"first.c": hashlib.sha256(b"original").hexdigest(), "second.c": "0" * 64}
            with patch.dict(SOURCE_HASHES, profiles, clear=True):
                with patch("tools.repair_xnu_aggregates.repair_aggregate", side_effect=[b"updated", ValueError("bad source")]):
                    with self.assertRaisesRegex(ValueError, "bad source"):
                        stage_aggregate_repairs(source)
            self.assertEqual((source / "first.c").read_bytes(), b"original")
