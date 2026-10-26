import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.repair_xnu_trace_formats import (SOURCE_HASHES, TRACE_MACROS, integer_check,
                                          macro_bounds, repair_analytics_queue_failure,
                                          repair_necp_trace_formats, repair_trace_formats,
                                          repair_trace_macro, stage_trace_formats)


def trace_fixture(name):
    formats = {
        "SOCKET": b"drop-all order %d Application %d Real Application %d BoundInterface %d policy_id %d skip_policy_id %d",
        "SOCKET_RESULT": b"drop-all order %d Application %d Real Application %d BoundInterface %d policy id=%d session_order=%d policy_order=%d",
        "IP": b"drop-all order %d BoundInterface %d socket policy id %d socket skip id %d",
        "IP_RESULT": b"drop-all order %d BoundInterface %d policy id=%d session_order=%d policy_order=%d",
        "POLICY": b"policy id=%d session_order=%d policy_order=%d cond_policy_id %d skip_session_order %d skip_order %d",
        "CONDITION3": b"%d %X %d %X %d %X %d %X %d %X %d %X",
    }
    arguments = b", values"
    if name == "SOCKET":
        arguments = b", policy_id, skip_policy_id"
    elif name == "CONDITION3":
        arguments = b", val1, val1, val2, val2, val3, val3, input1, input1, input2, input2, input3, input3"
    return (b"#define NECP_DATA_TRACE_LOG_" + name.encode() + b"(parameters) \\\n"
            b"    if (debug) { \\\n    NECPDATATRACELOG(LOG_ERR, \"" + formats[name] + b"\"" + arguments + b"); \\\n    }\n")


class TraceFormatTests(unittest.TestCase):
    def test_sources_fail_closed(self):
        self.assertEqual(len(SOURCE_HASHES), 2)
        for relative in SOURCE_HASHES:
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "trace repair source"):
                repair_trace_formats(relative, b"unreviewed")

    def test_macro_boundaries_preserve_unrelated_source_and_log_call_counts(self):
        original = b"policy_decision();\n" + b"".join(trace_fixture(name) for name in TRACE_MACROS) + b"return_policy();\n"
        repaired = repair_necp_trace_formats(original)
        self.assertTrue(repaired.startswith(b"policy_decision();\n"))
        self.assertTrue(repaired.endswith(b"return_policy();\n"))
        self.assertEqual(repaired.count(b"NECPDATATRACELOG("), 6)
        self.assertEqual(repaired.count(b"if (debug)"), 6)

    def test_condition_trace_has_explicit_signed_and_unsigned_pairs_without_narrowing(self):
        original = trace_fixture("CONDITION3")
        repaired = repair_trace_macro("CONDITION3", original)
        self.assertEqual(repaired.count(b"_Static_assert"), 6)
        for name in ("val1", "val2", "val3", "input1", "input2", "input3"):
            self.assertIn(integer_check(name), repaired)
            self.assertIn(("(int)(" + name + "), (unsigned int)(" + name + ")").encode(), repaired)
        self.assertEqual(repaired.count(b"%d %X"), 6)

    def test_socket_policy_literals_have_checked_unsigned_conversion(self):
        repaired = repair_trace_macro("SOCKET", trace_fixture("SOCKET"))
        self.assertEqual(repaired.count(b"_Static_assert"), 2)
        self.assertIn(b"(unsigned int)(policy_id), (unsigned int)(skip_policy_id)", repaired)
        self.assertNotIn(b"%d", repaired)

    def test_incompatible_macro_layout_is_rejected(self):
        original = trace_fixture("SOCKET")
        for invalid in (b"", original + original, original.replace(b"NECP_DATA_TRACE_LOG_SOCKET", b"OTHER")):
            with self.assertRaises(ValueError):
                macro_bounds(invalid, "SOCKET")
        with self.assertRaisesRegex(ValueError, "unterminated"):
            macro_bounds(b"#define NECP_DATA_TRACE_LOG_SOCKET(parameters) \\\n", "SOCKET")
        for invalid in (original.replace(b"NECPDATATRACELOG", b"other"),
                        original.replace(b"drop-all order %d", b"drop-all order %x")):
            with self.assertRaises(ValueError):
                repair_trace_macro("SOCKET", invalid)

    def test_analytics_checks_failure_and_keeps_original_queue_call(self):
        original = (b"#include <kern/mpsc_queue.h>\n\tkern_return_t result;\n"
                    b"\tresult = create_queue(\n\t    \"daemon.core-analytics-events\", MPSC_DAEMON_INIT_NONE);\n")
        repaired = repair_analytics_queue_failure(original)
        self.assertIn(b"#include <kern/debug.h>", repaired)
        self.assertEqual(repaired.count(b"create_queue("), 1)
        self.assertIn(b"if (result != KERN_SUCCESS)", repaired)
        self.assertIn(b'panic("telemetry_init: core analytics daemon creation failed");', repaired)
        for invalid in (b"", original + original, repaired):
            with self.assertRaises(ValueError):
                repair_analytics_queue_failure(invalid)

    def test_staging_validates_all_inputs_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("first.c", "second.c"):
                (root / relative).write_bytes(b"original")
            profiles = {relative: hashlib.sha256(b"original").hexdigest()
                        for relative in ("first.c", "second.c")}
            with patch.dict(SOURCE_HASHES, profiles, clear=True):
                with patch("tools.repair_xnu_trace_formats.repair_trace_formats",
                           side_effect=[b"updated", ValueError("bad input")]):
                    with self.assertRaises(ValueError):
                        stage_trace_formats(root)
            self.assertEqual((root / "first.c").read_bytes(), b"original")
