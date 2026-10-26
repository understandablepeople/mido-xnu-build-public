"""Repair reviewed network callback signatures and local unsigned flags."""

import hashlib
import re


SOURCE_HASHES = {
    "bsd/skywalk/lib/net_filter_event.c": "47eff77df6b3925767586a8167878b47e03b5f13933f0488917e5a79694ccd5e",
    "bsd/skywalk/lib/cuckoo_hashtable_test.c": "35701ef74f77952071023873f59cf130dfacdfc46e5d4cc88517a8651e3efc9e",
    "bsd/netinet6/esp.h": "c9adfe780b460fe0473e274fa1c02f474da8595485eaf5177345af6382827bff",
    "bsd/netinet/ip_output.c": "f2032288a5354ced8136de9fd2e7f68f861df2f4df2e7443626cdb0a9579c3a4",
    "bsd/netinet6/ip6_output.c": "324b2eb26eaee4325983648cd3a1132494f55bb9a850cfc97f17370ce983c6bb",
}


def replace_once(data, original, updated):
    if data.count(original) != 1:
        raise ValueError("unexpected network type anchor")
    return data.replace(original, updated)


def repair_local_flags(data, ipv6):
    name = b"ip6obf" if ipv6 else b"ipobf"
    pattern = rb"\tunion \{\n\t\tstruct \{\n(?P<fields>.*?)\n\t\t\};\n\t\tuint32_t raw;\n\t\} " + name + rb" = \{ \.raw = 0 \};"
    matches = list(re.finditer(pattern, data, re.DOTALL))
    if len(matches) != 1:
        raise ValueError("unexpected local output flag union")
    match = matches[0]
    fields = match["fields"]
    updated, count = re.subn(rb"\bboolean_t (?=[a-z_]+ : 1;)", b"unsigned int ", fields)
    if count != (6 if ipv6 else 9):
        raise ValueError("unexpected local output flag count")
    return data[:match.start("fields")] + updated + data[match.end("fields"):]


def repair_network_types(relative, data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != SOURCE_HASHES[relative]:
        raise ValueError("unexpected network type source: " + relative)
    if relative.endswith("net_filter_event.c"):
        return replace_once(data,
                            b"net_filter_event_callback(struct eventhandler_entry_arg arg0 __unused,\n    uint32_t state)",
                            b"net_filter_event_callback(struct eventhandler_entry_arg arg0 __unused,\n    enum net_filter_event_subsystems state)")
    if relative.endswith("cuckoo_hashtable_test.c"):
        for suffix in ("ops_begin", "ops_done", "add_check", "del_check", "duo_check"):
            name = ("cht_concurrent_" + suffix).encode()
            data = replace_once(data, b"\n" + name + b"()\n", b"\n" + name + b"(void)\n")
        return data
    if relative.endswith("esp.h"):
        return replace_once(data, b"struct secasvar;\n", b"struct secasvar;\nstruct ipsecrequest;\n")
    return repair_local_flags(data, relative.endswith("ip6_output.c"))


def stage_network_types(source):
    pending = []
    report = {}
    for relative, expected in SOURCE_HASHES.items():
        target = source / relative
        after = repair_network_types(relative, target.read_bytes())
        pending.append((target, after))
        report[relative] = {"original_sha256": expected,
                            "updated_sha256": hashlib.sha256(after).hexdigest()}
    for target, after in pending:
        target.write_bytes(after)
    return report
