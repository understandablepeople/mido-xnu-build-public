import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.repair_xnu_network_types import (SOURCE_HASHES, repair_local_flags,
                                          repair_network_types, stage_network_types)


class NetworkTypeTests(unittest.TestCase):
    def repair_fixture(self, relative, original):
        with patch.dict(SOURCE_HASHES, {relative: hashlib.sha256(original).hexdigest()}):
            return repair_network_types(relative, original)

    def test_rejects_unreviewed_sources(self):
        self.assertEqual(len(SOURCE_HASHES), 5)
        for relative in SOURCE_HASHES:
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "network type source"):
                repair_network_types(relative, b"unreviewed")

    def test_callback_uses_declared_enum_without_pointer_casts(self):
        original = (b"net_filter_event_callback(struct eventhandler_entry_arg arg0 __unused,\n"
                    b"    uint32_t state)\n{ body(state); }\n")
        relative = "bsd/skywalk/lib/net_filter_event.c"
        updated = self.repair_fixture(relative, original)
        self.assertEqual(updated.replace(b"enum net_filter_event_subsystems", b"uint32_t"), original)
        for invalid in (b"", original + original):
            with self.assertRaisesRegex(ValueError, "anchor"):
                self.repair_fixture(relative, invalid)

    def test_no_argument_definitions_have_full_prototypes(self):
        relative = "bsd/skywalk/lib/cuckoo_hashtable_test.c"
        original = b"".join(b"static void\ncht_concurrent_" + suffix + b"()\n{ body(); }\n"
                            for suffix in (b"ops_begin", b"ops_done", b"add_check", b"del_check", b"duo_check"))
        updated = self.repair_fixture(relative, original)
        self.assertEqual(updated.count(b"(void)"), 5)
        self.assertEqual(updated.replace(b"(void)", b"()"), original)
        with self.assertRaises(ValueError):
            self.repair_fixture(relative, original.replace(b"ops_begin", b"unknown"))

    def test_opaque_ipsec_request_is_declared_at_file_scope(self):
        original = b"struct secasvar;\nextern size_t esp_hdrsiz(struct ipsecrequest *);\n"
        updated = self.repair_fixture("bsd/netinet6/esp.h", original)
        self.assertEqual(updated.replace(b"struct ipsecrequest;\n", b""), original)
        self.assertLess(updated.index(b"struct ipsecrequest;"), updated.index(b"extern"))

    def test_only_local_flag_storage_changes(self):
        for ipv6, count in ((False, 9), (True, 6)):
            name = b"ip6obf" if ipv6 else b"ipobf"
            fields = b"".join(b"\t\t\tboolean_t flag" + b"x" * index + b" : 1;\n"
                              for index in range(count))
            original = (b"boolean_t untouched;\n\tunion {\n\t\tstruct {\n" + fields +
                        b"\t\t};\n\t\tuint32_t raw;\n\t} " + name + b" = { .raw = 0 };")
            updated = repair_local_flags(original, ipv6)
            self.assertEqual(updated.count(b"unsigned int "), count)
            self.assertEqual(updated.replace(b"unsigned int ", b"boolean_t "), original)
            for invalid in (b"", original + original, original.replace(b"boolean_t flag :", b"int flag :")):
                with self.assertRaises(ValueError):
                    repair_local_flags(invalid, ipv6)

    def test_staging_is_atomic_on_validation_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("first.c", "second.c"):
                (root / relative).write_bytes(b"original")
            profiles = dict.fromkeys(("first.c", "second.c"), "unused")
            with patch.dict(SOURCE_HASHES, profiles, clear=True):
                with patch("tools.repair_xnu_network_types.repair_network_types",
                           side_effect=[b"updated", ValueError("bad source")]):
                    with self.assertRaises(ValueError):
                        stage_network_types(root)
            self.assertEqual((root / "first.c").read_bytes(), b"original")
