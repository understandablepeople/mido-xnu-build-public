import hashlib
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from tools.repair_xnu_network_gates import (SOURCE_HASHES, guard_block, repair_flow_extensions,
                                           repair_network_gates, repair_socket_operations,
                                           stage_network_gates, repair_pcb_filter_flag,
                                           repair_udp_policy_local, repair_raw_filter_destination,
                                           repair_ipv6_scope_locals, repair_ip_output_policy,
                                           repair_ip_input_flow_types)


def socket_fixture():
    tracker = b""
    for operation in (b"connect()", b"connectx()"):
        tracker += (b"\t\t\t\tif (necp_set_socket_domain_attributes(so, metadata.domain, metadata.domain_owner)) {\n"
                    b'\t\t\t\t\tprintf("' + operation + b' - failed necp_set_socket_domain_attributes");\n'
                    b"\t\t\t\t}\n")
    return (tracker + b"\t\tcase SO_MARK_CELLFALLBACK_UUID:\n\t\t{\n"
            b"\t\t\terror = nstat_userland_mark_rnf_override(args.flow_uuid,\n"
            b"\t\t\t    args.flow_cellfallback);\n\t\t\tbreak;\n\t\t}\n"
            b"\tif (SOCK_DOM(so) == PF_MULTIPATH) {\n\t\tmptcp_set_restrictions(so);\n\t}\n")


class NetworkGateRepairTests(unittest.TestCase):
    def test_every_profile_rejects_unreviewed_bytes(self):
        self.assertEqual(len(SOURCE_HASHES), 10)
        for relative in SOURCE_HASHES:
            with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, "network gate source"):
                repair_network_gates(relative, b"unreviewed")

    def test_socket_gates_preserve_enabled_operations_exactly(self):
        original = socket_fixture()
        result = repair_socket_operations(original)
        self.assertEqual(result.count(b"#if NECP\n"), 2)
        self.assertEqual(result.count(b"#if SKYWALK\n"), 1)
        self.assertEqual(result.count(b"#if MULTIPATH && MPTCP\n"), 1)
        self.assertEqual(re.sub(rb"^#(?:if[^\n]*|endif)\n", b"", result, flags=re.M), original)
        self.assertNotIn(b"#else", result)

    def test_socket_layout_changes_rejected(self):
        original = socket_fixture()
        for invalid in (original + original, original.replace(b"connectx()", b"other()"),
                        original.replace(b"args.flow_cellfallback", b"args.changed"),
                        original.replace(b"PF_MULTIPATH", b"PF_INET")):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                repair_socket_operations(invalid)

    def test_domain_extension_size_and_content_are_gated_together(self):
        original = (b"\tstruct nstat_domain_info *domain_info = NULL;\n"
                    b"\t\tcase NSTAT_EXTENDED_UPDATE_TYPE_DOMAIN:\n"
                    b"\t\t\treturn sizeof(nstat_domain_info);\n"
                    b"\tcase NSTAT_EXTENDED_UPDATE_TYPE_DOMAIN:\n"
                    b"\t\tdomain_info = buf;\n\t\tnecp_copy_inp_domain_info(inp, so, domain_info);\n"
                    b"\t\tsize = sizeof(nstat_domain_info);\n")
        result = repair_flow_extensions(original)
        self.assertEqual(result.count(b"#if NECP\n"), 3)
        self.assertEqual(re.sub(rb"^#(?:if[^\n]*|endif)\n", b"", result, flags=re.M), original)
        for invalid in (original + original, original.replace(b"return sizeof", b"return changed_sizeof")):
            with self.assertRaises(ValueError):
                repair_flow_extensions(invalid)

    def test_guard_requires_unique_ordered_boundaries(self):
        self.assertEqual(guard_block(b"before\nstart\nend\nafter", b"start\n", b"end\n", b"FEATURE"),
                         b"before\n#if FEATURE\nstart\nend\n#endif\nafter")
        for invalid in (b"start\nstart\nend\n", b"end\nstart\n", b"start\n"):
            with self.assertRaises(ValueError):
                guard_block(invalid, b"start\n", b"end\n", b"FEATURE")

    def test_pcb_filter_flag_matches_optional_socket_field(self):
        original = b"\tif (so->so_cfil != NULL) {\n\t\txso->xso_filter_flags |= XSOFF_CFIL;\n\t}\n"
        self.assertEqual(repair_pcb_filter_flag(original), b"#if CONTENT_FILTER\n" + original + b"#endif\n")
        for invalid in (b"", original + original):
            with self.assertRaises(ValueError):
                repair_pcb_filter_flag(invalid)

    def test_udp_local_follows_its_actual_necp_uses(self):
        original = b"#if IPSEC\n\t\t\tint skipit;\n#endif /* IPSEC */"
        self.assertEqual(repair_udp_policy_local(original), b"#if NECP\n\t\t\tint skipit;\n#endif")
        for invalid in (b"", original + original):
            with self.assertRaises(ValueError):
                repair_udp_policy_local(invalid)

    def test_raw_filter_destination_retains_connected_address_fallback(self):
        original = b"\t\tdst = cfil_faddr_use ? cfil_dst : inp->inp_faddr.s_addr;\n"
        self.assertEqual(repair_raw_filter_destination(original), b"#if CONTENT_FILTER\n" + original +
                         b"#else\n\t\tdst = inp->inp_faddr.s_addr;\n#endif\n")
        for invalid in (b"", original + original):
            with self.assertRaises(ValueError):
                repair_raw_filter_destination(invalid)

    def test_raw_ipv6_scope_locals_are_not_content_filter_state(self):
        declaration = b"\tuint32_t sifscope = IFSCOPE_NONE, difscope = IFSCOPE_NONE;\n"
        original = b"\tstruct sockaddr_in6 tmp;\n#if CONTENT_FILTER\n" + declaration + b"filter_state();\n#endif\n"
        expected = b"\tstruct sockaddr_in6 tmp;\n" + declaration + b"#if CONTENT_FILTER\nfilter_state();\n#endif\n"
        self.assertEqual(repair_ipv6_scope_locals(original), expected)
        for invalid in (b"", original + original):
            with self.assertRaises(ValueError):
                repair_ipv6_scope_locals(invalid)

    def test_ipsec_skip_label_is_available_to_independent_necp_users(self):
        original = b"#if IPSEC\nprocess_ipsec();\nskip_ipsec:\n#endif /* IPSEC */\n"
        include = b"#include <netinet6/nd6.h>\n"
        result = repair_ip_output_policy(include + original, False)
        self.assertIn(b"process_ipsec();\n#endif /* IPSEC */\n#if IPSEC || NECP\nskip_ipsec:\n#endif", result)
        self.assertIn(b"#include <netinet/ip6.h>\n" + include, result)
        for invalid in (b"", include + original + original, include + include + original):
            with self.assertRaises(ValueError):
                repair_ip_output_policy(invalid, False)

    def test_ipv6_reset_obeys_field_guard_without_changing_other_state(self):
        reset = b"\t\tbzero(&ipsec_state, sizeof(ipsec_state));\n"
        original = b"skip_ipsec:\n#endif /* IPSEC */\n\t\tbzero(&exthdrs, sizeof(exthdrs));\n" + reset
        result = repair_ip_output_policy(original, True)
        self.assertIn(b"bzero(&exthdrs, sizeof(exthdrs));\n#if IPSEC\n" + reset + b"#endif", result)
        for invalid in (original.replace(reset, b""), original + reset):
            with self.assertRaises(ValueError):
                repair_ip_output_policy(invalid, True)

    def test_ip_input_includes_real_flow_types_without_enabling_dummynet(self):
        original = b"#include <netinet/ip_icmp.h>\n#if DUMMYNET\n#include <netinet/ip_dummynet.h>\n#endif\n"
        result = repair_ip_input_flow_types(original)
        self.assertEqual(result, original.replace(b"#include <netinet/ip_icmp.h>\n",
                         b"#include <netinet/ip_icmp.h>\n#include <netinet/ip_flowid.h>\n"))
        for invalid in (b"", original + original, result):
            with self.assertRaises(ValueError):
                repair_ip_input_flow_types(invalid)

    def test_staging_validates_every_source_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for relative in ("first.c", "second.c"):
                (root / relative).write_bytes(b"original")
            profiles = {relative: hashlib.sha256(b"original").hexdigest()
                        for relative in ("first.c", "second.c")}
            with patch.dict(SOURCE_HASHES, profiles, clear=True):
                with patch("tools.repair_xnu_network_gates.repair_network_gates",
                           side_effect=[b"updated", ValueError("bad source")]):
                    with self.assertRaisesRegex(ValueError, "bad source"):
                        stage_network_gates(root)
            self.assertEqual((root / "first.c").read_bytes(), b"original")
