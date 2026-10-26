"""Preserve packet class numeric ABI checks across distinct enum namespaces."""

import hashlib
import re


SOURCE_HASHES = {
    "bsd/skywalk/packet/pbufpool.c": "a47badd01b6faa24ede2ad3d4df5e142aba3bd75e6194c08cb9bb34dd64d786d",
    "bsd/skywalk/nexus/flowswitch/flow/flow_entry.c": "c3d3cbbac1387fd6c8d7e516423a9b74ced72cdffd92a32d65fdabd05e2fe222",
    "bsd/skywalk/nexus/netif/nx_netif.c": "5f651bcf5dde5bf6c386633ab04f074d83ed25618a1dbbac7ce2c66fc2721cbe",
}


def repair_class_assertions(data):
    pattern = rb"_CASSERT\((KPKT_(?:SC|TC)_[A-Z_]+) == ((?:MBUF|PKT)_(?:SC|TC)_[A-Z_]+)\);"
    matches = list(re.finditer(pattern, data))
    if len(matches) != 34:
        raise ValueError("unexpected packet class ABI assertion count")
    for match in reversed(matches):
        replacement = b"_CASSERT((int)" + match[1] + b" == (int)" + match[2] + b");"
        data = data[:match.start()] + replacement + data[match.end():]
    return data


def repair_packet_classes(relative, data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != SOURCE_HASHES[relative]:
        raise ValueError("unexpected packet class source: " + relative)
    if relative.endswith("pbufpool.c"):
        return repair_class_assertions(data)
    if relative.endswith("flow_entry.c"):
        original = b"sf->sf_svc_class = fe->fe_svc_class;"
        updated = b"sf->sf_svc_class = (packet_svc_class_t)fe->fe_svc_class;"
    else:
        original = b"nqi->nqi_svc = nq->nq_svc;"
        updated = b"nqi->nqi_svc = (packet_svc_class_t)nq->nq_svc;"
    if data.count(original) != 1:
        raise ValueError("unexpected packet service class export")
    return data.replace(original, updated)


def stage_packet_classes(source):
    pending = []
    report = {}
    for relative, expected in SOURCE_HASHES.items():
        target = source / relative
        after = repair_packet_classes(relative, target.read_bytes())
        pending.append((target, after))
        report[relative] = {"original_sha256": expected,
                            "updated_sha256": hashlib.sha256(after).hexdigest()}
    for target, after in pending:
        target.write_bytes(after)
    return report
