import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.repair_xnu_packet_classes import (SOURCE_HASHES, repair_class_assertions,
                                           repair_packet_classes, stage_packet_classes)


class PacketClassTests(unittest.TestCase):
    def repair_fixture(self, relative, data):
        digest = hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()
        with patch.dict(SOURCE_HASHES, {relative: digest}):
            return repair_packet_classes(relative, data)

    def test_all_sources_are_pinned(self):
        self.assertEqual(len(SOURCE_HASHES), 3)
        for relative in SOURCE_HASHES:
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "packet class source"):
                repair_packet_classes(relative, b"unreviewed")

    def test_numeric_assertions_retain_both_constants_and_equality(self):
        original = b"\n".join(b"_CASSERT(KPKT_SC_CLASS" + b"X" * index + b" == PKT_SC_CLASS" + b"X" * index + b");"
                              for index in range(34))
        original += b"\n_CASSERT(PKT_F_BACKGROUND == PKTF_SO_BACKGROUND);\n"
        updated = repair_class_assertions(original)
        self.assertEqual(updated.count(b"(int)"), 68)
        self.assertEqual(updated.replace(b"(int)", b""), original)
        self.assertTrue(updated.endswith(b"_CASSERT(PKT_F_BACKGROUND == PKTF_SO_BACKGROUND);\n"))
        self.assertEqual(self.repair_fixture("bsd/skywalk/packet/pbufpool.c", original), updated)

    def test_assertion_inventory_rejects_missing_duplicate_and_repaired_input(self):
        original = b"_CASSERT(KPKT_TC_CLASS == MBUF_TC_CLASS);\n" * 34
        for invalid in (b"", original + original, original.replace(b"KPKT_TC_CLASS", b"OTHER", 1), repair_class_assertions(original)):
            with self.assertRaisesRegex(ValueError, "assertion count"):
                repair_class_assertions(invalid)

    def test_exports_only_add_destination_enum_cast(self):
        for relative, statement in (
                ("bsd/skywalk/nexus/flowswitch/flow/flow_entry.c", b"sf->sf_svc_class = fe->fe_svc_class;"),
                ("bsd/skywalk/nexus/netif/nx_netif.c", b"nqi->nqi_svc = nq->nq_svc;")):
            original = b"before\n" + statement + b"\nafter\n"
            updated = self.repair_fixture(relative, original)
            self.assertEqual(updated.replace(b"(packet_svc_class_t)", b""), original)
            for invalid in (b"", original + original):
                with self.assertRaisesRegex(ValueError, "export"):
                    self.repair_fixture(relative, invalid)

    def test_line_endings_normalize_and_repair_is_not_repeated(self):
        relative = "bsd/skywalk/nexus/netif/nx_netif.c"
        original = b"nqi->nqi_svc = nq->nq_svc;\r\n"
        updated = self.repair_fixture(relative, original)
        self.assertNotIn(b"\r", updated)
        with self.assertRaisesRegex(ValueError, "packet class source"):
            repair_packet_classes(relative, updated)

    def test_stage_validates_all_inputs_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("first.c", "second.c"):
                (root / relative).write_bytes(b"original")
            with patch.dict(SOURCE_HASHES, dict.fromkeys(("first.c", "second.c"), "unused"), clear=True):
                with patch("tools.repair_xnu_packet_classes.repair_packet_classes",
                           side_effect=[b"updated", ValueError("bad source")]):
                    with self.assertRaises(ValueError):
                        stage_packet_classes(root)
            self.assertEqual((root / "first.c").read_bytes(), b"original")
