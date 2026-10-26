"""Keep optional network operations inside their genuine configuration gates."""

import hashlib
import re


SOURCE_HASHES = {
    "bsd/kern/uipc_socket.c": "ebb33fe7062835eeb02e34b2cb0d7538b70e413f098dde4b6674920d50a48778",
    "bsd/kern/socket_flows.c": "c018aaaccf012ef3ac42d1d480f8199be17f3f6789407dbae501eac83cf44001",
    "bsd/netinet/in_pcblist.c": "06acba4cc30f8b46c748d4c1e8ef66c0ed0d2d2100b1d46cb4b0afc37a5346f3",
    "bsd/netinet/udp_usrreq.c": "1603c87f58cc588e72ec855c8874a51d88eb6d10e9bb8a15dcf724cd4712b81e",
    "bsd/netinet/raw_ip.c": "d48af184313aa3f76769853e4d604596d4a2889d3ca8c73dcf75c9bfd36f7f9c",
    "bsd/netinet6/raw_ip6.c": "f52644ea1201b2c2662be0550296b406051334d95a3eaf65348a21852a57ce70",
    "bsd/netinet6/udp6_usrreq.c": "742aee57dd2053260e33768f51d5a9e4c0a1249db92ebd6c0c39317fedd9ed91",
    "bsd/netinet6/ip6_output.c": "5513726830d1216474d1ad7c5c8b4b9b00407e115a8605a9f085658fc294b85f",
    "bsd/netinet/ip_output.c": "8851a873827718c0e2db5dc61a261d2d67d6f5b86fd6fc6f6d43f311cf3fe559",
    "bsd/netinet/ip_input.c": "1deb7def7e4080a783777551f725bc3088bde7d6a57272b8e85c835344befd33",
}


def guard_block(data, start, end, condition):
    starts = list(re.finditer(rb"^" + re.escape(start), data, re.M))
    ends = list(re.finditer(rb"^" + re.escape(end), data, re.M))
    if len(starts) != 1 or len(ends) != 1 or ends[0].start() < starts[0].start():
        raise ValueError("unexpected optional network block")
    first = starts[0].start()
    last = ends[0].end()
    return (data[:first] + b"#if " + condition + b"\n" + data[first:last]
            + b"#endif\n" + data[last:])


def repair_socket_operations(data):
    for operation in (b"connect()", b"connectx()"):
        start = b"\t\t\t\tif (necp_set_socket_domain_attributes(so, metadata.domain, metadata.domain_owner)) {\n"
        end = b'\t\t\t\t\tprintf("' + operation + b' - failed necp_set_socket_domain_attributes");\n\t\t\t\t}\n'
        if data.count(start) != 2 and operation == b"connect()":
            raise ValueError("unexpected tracker domain attribute call count")
        if data.count(end) != 1:
            raise ValueError("unexpected tracker domain attribute diagnostic")
        last = data.index(end) + len(end)
        first = data.rfind(start, 0, last)
        if first < 0:
            raise ValueError("missing tracker domain attribute call")
        block = data[first:last]
        data = data[:first] + b"#if NECP\n" + block + b"#endif\n" + data[last:]
    data = guard_block(data, b"\t\tcase SO_MARK_CELLFALLBACK_UUID:\n",
                       b"\t\t\terror = nstat_userland_mark_rnf_override(args.flow_uuid,\n"
                       b"\t\t\t    args.flow_cellfallback);\n\t\t\tbreak;\n\t\t}\n", b"SKYWALK")
    return guard_block(data, b"\tif (SOCK_DOM(so) == PF_MULTIPATH) {\n\t\tmptcp_set_restrictions(so);\n",
                       b"\t\tmptcp_set_restrictions(so);\n\t}\n", b"MULTIPATH && MPTCP")


def repair_flow_extensions(data):
    data = guard_block(data, b"\tstruct nstat_domain_info *domain_info = NULL;\n",
                       b"\tstruct nstat_domain_info *domain_info = NULL;\n", b"NECP")
    data = guard_block(data, b"\t\tcase NSTAT_EXTENDED_UPDATE_TYPE_DOMAIN:\n",
                       b"\t\t\treturn sizeof(nstat_domain_info);\n", b"NECP")
    return guard_block(data, b"\tcase NSTAT_EXTENDED_UPDATE_TYPE_DOMAIN:\n",
                       b"\t\tsize = sizeof(nstat_domain_info);\n", b"NECP")


def repair_pcb_filter_flag(data):
    block = b"\tif (so->so_cfil != NULL) {\n\t\txso->xso_filter_flags |= XSOFF_CFIL;\n\t}\n"
    return guard_block(data, block, block, b"CONTENT_FILTER")


def repair_udp_policy_local(data):
    original = b"#if IPSEC\n\t\t\tint skipit;\n#endif /* IPSEC */"
    if data.count(original) != 1:
        raise ValueError("unexpected UDP policy local guard")
    return data.replace(original, b"#if NECP\n\t\t\tint skipit;\n#endif")


def repair_raw_filter_destination(data):
    original = b"\t\tdst = cfil_faddr_use ? cfil_dst : inp->inp_faddr.s_addr;\n"
    if data.count(original) != 1:
        raise ValueError("unexpected raw socket filter destination")
    return data.replace(original, b"#if CONTENT_FILTER\n" + original +
                        b"#else\n\t\tdst = inp->inp_faddr.s_addr;\n#endif\n")


def repair_ipv6_scope_locals(data):
    declaration = b"\tuint32_t sifscope = IFSCOPE_NONE, difscope = IFSCOPE_NONE;\n"
    anchor = b"\tstruct sockaddr_in6 tmp;\n#if CONTENT_FILTER\n"
    if data.count(declaration) != 1 or data.count(anchor) != 1:
        raise ValueError("unexpected raw IPv6 scope local layout")
    data = data.replace(declaration, b"")
    return data.replace(anchor, anchor.replace(b"#if CONTENT_FILTER\n", declaration + b"#if CONTENT_FILTER\n"))


def repair_ip_output_policy(data, ipv6):
    original = b"skip_ipsec:\n#endif /* IPSEC */"
    if data.count(original) != 1:
        raise ValueError("unexpected IPsec skip label layout")
    data = data.replace(original, b"#endif /* IPSEC */\n#if IPSEC || NECP\nskip_ipsec:\n#endif")
    if ipv6:
        reset = b"\t\tbzero(&ipsec_state, sizeof(ipsec_state));\n"
        if data.count(reset) != 1:
            raise ValueError("unexpected IPv6 IPsec state reset layout")
        return data.replace(reset, b"#if IPSEC\n" + reset + b"#endif\n")
    include = b"#include <netinet6/nd6.h>\n"
    if data.count(include) != 1 or b"#include <netinet/ip6.h>" in data:
        raise ValueError("unexpected IPv4 IPv6 MTU include layout")
    return data.replace(include, b"#include <netinet/ip6.h>\n" + include)


def repair_ip_input_flow_types(data):
    include = b"#include <netinet/ip_icmp.h>\n"
    if data.count(include) != 1 or b"#include <netinet/ip_flowid.h>" in data:
        raise ValueError("unexpected IPv4 input flow type include layout")
    return data.replace(include, include + b"#include <netinet/ip_flowid.h>\n")


def repair_network_gates(relative, data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != SOURCE_HASHES[relative]:
        raise ValueError("unexpected network gate source: " + relative)
    if relative == "bsd/kern/uipc_socket.c":
        return repair_socket_operations(data)
    if relative == "bsd/kern/socket_flows.c":
        return repair_flow_extensions(data)
    if relative == "bsd/netinet/in_pcblist.c":
        return repair_pcb_filter_flag(data)
    if relative in ("bsd/netinet/udp_usrreq.c", "bsd/netinet6/udp6_usrreq.c"):
        return repair_udp_policy_local(data)
    if relative == "bsd/netinet6/raw_ip6.c":
        return repair_ipv6_scope_locals(data)
    if relative in ("bsd/netinet/ip_output.c", "bsd/netinet6/ip6_output.c"):
        return repair_ip_output_policy(data, relative.endswith("/ip6_output.c"))
    if relative == "bsd/netinet/ip_input.c":
        return repair_ip_input_flow_types(data)
    return repair_raw_filter_destination(data)


def stage_network_gates(source):
    pending = []
    report = {}
    for relative, expected in SOURCE_HASHES.items():
        target = source / relative
        after = repair_network_gates(relative, target.read_bytes())
        pending.append((target, after))
        report[relative] = {"original_sha256": expected,
                            "updated_sha256": hashlib.sha256(after).hexdigest()}
    for target, after in pending:
        target.write_bytes(after)
    return report
