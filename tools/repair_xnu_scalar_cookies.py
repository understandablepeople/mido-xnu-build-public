"""Decode reviewed integer callback cookies through a pointer-sized integer."""

import hashlib


SOURCE_HASHES = {
    "bsd/kern/kern_sysctl.c": "b3a926749002076efb0e5dbf1043a86433608ed1c04e267d5657023e9e99ef15",
    "bsd/kern/kern_mib.c": "6d0fde2abbaee7234227ee9e523ad784812cf1d4caa8bae5ec301692c003f078",
    "bsd/kern/uipc_mbuf.c": "c3ae1c0ba51d9abfd42fa62cdbb342cd3898f2b22ebaca67ee623048748fc1fa",
    "osfmk/kern/thread_call.c": "f378ed75959e84b07ae1a0155c51dab4dc4846f6f876f452fc07264a70e4d0a7",
    "bsd/net/pktsched/pktsched_fq_codel.c": "11f3dc94a69e49539705c09e3a21bd88f965401928960b25c29d7d53c80fb582",
    "bsd/netinet6/frag6.c": "e3e595bb85570fffebe59f98cfd2a59a33a44ff249823ec9058bdb158cb688e3",
    "osfmk/kern/coalition.c": "a31331fae3ffb8bc910e19524980cb456960a7ac46d8bfcb47bed506ff855fca",
    "osfmk/kern/task.c": "be3afc0c2cccc612f672800858309c01968806116257005328cb19d2a5646dce",
    "osfmk/arm/model_dep.c": "5c197952859f2bed4dfe4c664c94e1a5054513ec288e5c400e9bedb47b4f9ac7",
    "pexpert/arm/pe_init.c": "828368f9415c9749f661563a714152d88f70ce639faae867c900dcfdbdf53b79",
    "iokit/Kernel/IONVRAMV3Handler.cpp": "2a3fa4b40221f5457941357bd74d6658712aef90aaf74ab6a2651cbe6a101ca2",
}

REPLACEMENTS = {
    "bsd/kern/kern_sysctl.c": (
        (b"(perfcontrol_callout_stat_t)arg1", b"(perfcontrol_callout_stat_t)(uintptr_t)arg1", 1),
        (b"int             oid = (int)arg1;", b"int             oid = (int)(uintptr_t)arg1;", 1)),
    "bsd/kern/kern_mib.c": ((b"int perflevel = (int)arg1;", b"int perflevel = (int)(uintptr_t)arg1;", 1),),
    "bsd/kern/uipc_mbuf.c": ((b"(mbuf_class_t)arg", b"(mbuf_class_t)(uintptr_t)arg", 7),),
    "osfmk/kern/thread_call.c": ((b"(thread_call_flavor_t) p1", b"(thread_call_flavor_t)(uintptr_t)p1", 1),),
    "bsd/net/pktsched/pktsched_fq_codel.c": ((b"fq_if_event(fqs, (cqev_t)arg);", b"fq_if_event(fqs, (cqev_t)(uintptr_t)arg);", 1),),
    "bsd/netinet6/frag6.c": ((b"return (int)m->m_pkthdr.pkt_hdr;", b"return (int)(uintptr_t)m->m_pkthdr.pkt_hdr;", 1),),
    "osfmk/kern/coalition.c": ((
        b"SENDING_NOTIFICATION__THIS_COALITION_IS_CAUSING_TOO_MUCH_IO((int)param0);",
        b"SENDING_NOTIFICATION__THIS_COALITION_IS_CAUSING_TOO_MUCH_IO((int)(uintptr_t)param0);", 1),),
    "osfmk/kern/task.c": ((
        b"SENDING_NOTIFICATION__THIS_PROCESS_IS_CAUSING_TOO_MUCH_IO((int)param0);",
        b"SENDING_NOTIFICATION__THIS_PROCESS_IS_CAUSING_TOO_MUCH_IO((int)(uintptr_t)param0);", 1),),
    "osfmk/arm/model_dep.c": ((b"(ppnum_t)NULL", b"(ppnum_t)0", 3),),
    "pexpert/arm/pe_init.c": ((b"'SHMC'", b"0x53484d43U", 1), (b"'BTRC'", b"0x42545243U", 1)),
    "iokit/Kernel/IONVRAMV3Handler.cpp": ((
        b"#define VARIABLE_STORE_SIGNATURE         'NVV3'",
        b"#define VARIABLE_STORE_SIGNATURE         0x4e565633U", 1),),
}


def repair_scalar_cookies(relative, data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != SOURCE_HASHES[relative]:
        raise ValueError("unexpected scalar cookie source: " + relative)
    for original, updated, count in REPLACEMENTS[relative]:
        if data.count(original) != count:
            raise ValueError("unexpected scalar cookie anchor: " + relative)
        data = data.replace(original, updated)
    return data


def stage_scalar_cookies(source):
    pending = []
    report = {}
    for relative, expected in SOURCE_HASHES.items():
        target = source / relative
        after = repair_scalar_cookies(relative, target.read_bytes())
        pending.append((target, after))
        report[relative] = {"original_sha256": expected,
                            "updated_sha256": hashlib.sha256(after).hexdigest()}
    for target, after in pending:
        target.write_bytes(after)
    return report
