import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.repair_xnu_optional_defaults import (CONTINUATION, REPLACEMENTS, SERIAL_CONDITION,
                                              SOURCE_HASHES, repair_optional_defaults,
                                              stage_optional_defaults)


class OptionalDefaultTests(unittest.TestCase):
    def test_ipv6_pf_tag_local_is_not_hidden_by_dummynet(self):
        before, after = REPLACEMENTS["bsd/netinet6/ip6_forward.c"][1]
        declaration = b"\t\tstruct pf_mtag *pf_mtag;\n"
        self.assertTrue(after.startswith(declaration + b"#if DUMMYNET\n"))
        self.assertEqual(before.replace(declaration, b""), after.replace(declaration, b""))

    def test_ipv4_output_pf_gets_complete_firewall_argument_type(self):
        before, after = REPLACEMENTS["bsd/netinet/ip_output.c"][1]
        self.assertEqual(before, b"#if PF\n#include <net/pfvar.h>\n#endif /* PF */\n")
        self.assertEqual(after, b"#if PF\n#include <netinet/ip_flowid.h>\n"
                               b"#include <net/pfvar.h>\n#endif /* PF */\n")
        self.assertEqual(after.replace(b"#include <netinet/ip_flowid.h>\n", b""), before)

    def test_ipv4_pf_arguments_exist_without_dummynet(self):
        before, after = REPLACEMENTS["bsd/netinet/ip_input.c"][1]
        self.assertEqual(after.split(b"#if PF || DUMMYNET\n")[0],
                         b"\tboolean_t               delete = FALSE;\n#endif /* DUMMYNET */\n")
        declarations = (b"\tstruct ip_fw_args       args1;\n"
                        b"\tboolean_t               init = FALSE;\n")
        self.assertIn(declarations, before)
        self.assertIn(b"#if PF || DUMMYNET\n" + declarations + b"#endif /* PF || DUMMYNET */\n", after)

    def repair_fixture(self, relative, data):
        with patch.dict(SOURCE_HASHES, {relative: hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()}):
            return repair_optional_defaults(relative, data)

    def test_every_source_is_pinned(self):
        self.assertEqual(len(SOURCE_HASHES), 13)
        self.assertEqual(set(SOURCE_HASHES), set(REPLACEMENTS))
        for relative in SOURCE_HASHES:
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "optional default source"):
                repair_optional_defaults(relative, b"unreviewed")

    def test_all_profiles_preserve_unmatched_text(self):
        for relative, replacements in REPLACEMENTS.items():
            with self.subTest(relative=relative):
                original = b"before\n" + b"between\n".join(before for before, after in replacements) + b"after\n"
                expected = b"before\n" + b"between\n".join(after for before, after in replacements) + b"after\n"
                self.assertEqual(self.repair_fixture(relative, original), expected)
                self.assertEqual(self.repair_fixture(relative, original.replace(b"\n", b"\r\n")), expected)
                with self.assertRaisesRegex(ValueError, "optional default source"):
                    repair_optional_defaults(relative, expected)

    def test_missing_and_duplicate_anchors_fail_closed(self):
        for relative, replacements in REPLACEMENTS.items():
            original = b"between\n".join(before for before, after in replacements)
            for before, after in replacements:
                for invalid in (original.replace(before, b"missing"), original + before):
                    with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "anchor"):
                        self.repair_fixture(relative, invalid)

    def test_guards_preserve_declarations_and_label_fallthrough(self):
        features = {
            "iokit/Kernel/IOPolledInterface.cpp": b"CRYPTO",
            "bsd/kern/mach_loader.c": b"CONFIG_CODE_DECRYPTION",
            "bsd/netinet/ip_output.c": b"DUMMYNET",
            "bsd/netinet6/ip6_output.c": b"IPSEC",
        }
        for relative, feature in features.items():
            before, after = REPLACEMENTS[relative][0]
            self.assertEqual(after, b"#if " + feature + b"\n" + before + b"#endif\n")
        for before, after in REPLACEMENTS["pexpert/arm/pe_serial.c"]:
            self.assertEqual(after, b"#if " + SERIAL_CONDITION + b"\n" + before + b"#endif\n")
        for relative, label, feature in (
                ("bsd/kern/uipc_socket.c", b"done", b"CONTENT_FILTER"),
                ("bsd/netinet/ip_input.c", b"pass", b"IPSEC"),
                ("bsd/netinet6/ip6_forward.c", b"sent", b"PF")):
            before, after = REPLACEMENTS[relative][0]
            addition = b"#if " + feature + b"\n" + label + b":\n#endif\n"
            self.assertEqual(after.replace(addition, label + b":\n"), before)

    def test_explicit_aggregate_defaults_do_not_change_existing_values(self):
        before, after = REPLACEMENTS["libkern/c++/OSSerialize.cpp"][0]
        fields = (b"kmg_type_hash", b"kmg_atomic", b"kmg_submap", b"kmg_context")
        for field in fields:
            after = after.replace(b"\t\t." + field + b" = 0,\n", b"")
        self.assertEqual(after, before)
        before, after = REPLACEMENTS["osfmk/kern/smr.h"][0]
        after = after.replace(b"\t        .smr_pcpu = NULL," + CONTINUATION, b"")
        after = after.replace(b"\t        .smr_early = 0," + CONTINUATION, b"")
        self.assertEqual(after, before)
        before, after = REPLACEMENTS["osfmk/kern/smr_hash.h"][0]
        self.assertEqual(after.replace(b".smrht_obj_type = {}, ", b"") + b" " * 22, before)
        before, after = REPLACEMENTS["osfmk/kern/smr_hash.h"][1]
        self.assertEqual(after.replace(b"\t\t.prev = NULL,\n\t\t.link = NULL,\n", b""), before)

    def test_optional_trace_reads_and_fse_parent_follow_real_consumers(self):
        for before, after in REPLACEMENTS["bsd/skywalk/nexus/nexus_traffic_rule.c"]:
            self.assertEqual(after.replace(b" && CONFIG_DTRACE", b""), before)
        before, after = REPLACEMENTS["bsd/vfs/vfs_syscalls.c"][0]
        self.assertEqual(before, b"\tvnode_t vp, pvp, dvp, lvp;\n")
        self.assertEqual(after, b"\tvnode_t vp, dvp, lvp;\n#if CONFIG_FSE\n\tvnode_t pvp;\n#endif\n")

    def test_staging_validates_all_sources_before_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("first.c", "second.c"):
                (root / relative).write_bytes(b"original")
            with patch.dict(SOURCE_HASHES, dict.fromkeys(("first.c", "second.c"), "unused"), clear=True):
                with patch("tools.repair_xnu_optional_defaults.repair_optional_defaults",
                           side_effect=[b"updated", ValueError("bad source")]):
                    with self.assertRaises(ValueError):
                        stage_optional_defaults(root)
            self.assertEqual((root / "first.c").read_bytes(), b"original")
