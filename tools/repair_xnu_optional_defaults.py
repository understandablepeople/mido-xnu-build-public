"""Preserve aggregate zero defaults and scope optional state to its consumers."""

import hashlib


SOURCE_HASHES = {
    "libkern/c++/OSSerialize.cpp": "bc27e91ff329794da52149000d8e76682c3a7906870d4eb0197e1b52e3dd54b9",
    "osfmk/kern/smr.h": "8f441d2337ee55eee5b844f32d49c8e7a0bf943c63df6ce31f40def8187b4b34",
    "osfmk/kern/smr_hash.h": "426af3a2e888e2aeeb94aa792f8cd2f49bc310683ceb84b2cb5ddcc8b0f85c4c",
    "iokit/Kernel/IOPolledInterface.cpp": "2164f8693b7ae4545c09d960ed7e4f7dcd06ae97f1b49c7395c847d7cd1b2f31",
    "bsd/kern/mach_loader.c": "58a36847003e7eaf0bc5e2cc76cd206e0152ec601253888504a2a9f65dec7486",
    "pexpert/arm/pe_serial.c": "4996c053b03650c5457973d2731038bca9b7d064473cadc182bb5597d66e0fa2",
    "bsd/netinet/ip_output.c": "a9d8e5f3bdce694f33b29af7338c6ad6216e3c745dd09da48995edd95d30dcce",
    "bsd/netinet6/ip6_output.c": "c8171e00c3a15c3356246379e5578c1985493d71df59f95052d2ca9da928d1e1",
    "bsd/kern/uipc_socket.c": "e1318e54516046895c75d318880f8f3c66540d06e28f87dc25d9c0a551499742",
    "bsd/netinet/ip_input.c": "373456d2a1a7c9e66d890ead31533c217540cb2f030d45934520eb57488c3574",
    "bsd/netinet6/ip6_forward.c": "f24d07c0fabdfea55944a9963127e7e30eceb9e1ef8f39fdc2593bbe5a4c444e",
    "bsd/skywalk/nexus/nexus_traffic_rule.c": "ed7a44846ae33f39883814c4af0a5daa2b9d6a231f000a202d1ec55d14fef59d",
    "bsd/vfs/vfs_syscalls.c": "b8ad0d3863422fe0aef8ab0455d8902e6c6e312b9700852be3faddfb632dad12",
}


def guarded(original, condition):
    return b"#if " + condition + b"\n" + original + b"#endif\n"


CONTINUATION = bytes((32, 92, 10))
SERIAL_CONDITION = (b"defined(PI3_UART) || defined(VMAPPLE_UART) || "
                    b"defined(DOCKCHANNEL_UART) || defined(APPLE_UART)")

REPLACEMENTS = {
    "libkern/c++/OSSerialize.cpp": ((
        b"\t\t.kmg_tag     = IOMemoryTag(kernel_map),\n",
        b"\t\t.kmg_tag     = IOMemoryTag(kernel_map),\n"
        b"\t\t.kmg_type_hash = 0,\n\t\t.kmg_atomic = 0,\n"
        b"\t\t.kmg_submap = 0,\n\t\t.kmg_context = 0,\n"),),
    "osfmk/kern/smr.h": (
        (b"\t        .smr_flags = (flags)," + CONTINUATION,
         b"\t        .smr_pcpu = NULL," + CONTINUATION +
         b"\t        .smr_flags = (flags)," + CONTINUATION +
         b"\t        .smr_early = 0," + CONTINUATION),),
    "osfmk/kern/smr_hash.h": (
        (b"\t} name = { .smrht = {" + b" " * 22,
         b"\t} name = { .smrht_obj_type = {}, .smrht = {"),
        (b"\t\t.hd_last = array.smrh_array + smr_hash_size(array),\n",
         b"\t\t.hd_last = array.smrh_array + smr_hash_size(array),\n"
         b"\t\t.prev = NULL,\n\t\t.link = NULL,\n")),
    "iokit/Kernel/IOPolledInterface.cpp": ((
        b"\t\t\tuint32_t lastReadLength = vars->lastRead;\n",
        guarded(b"\t\t\tuint32_t lastReadLength = vars->lastRead;\n", b"CRYPTO")),),
    "bsd/kern/mach_loader.c": ((
        b"\tint                     spawn = (imgp->ip_flags & IMGPF_SPAWN);\n",
        guarded(b"\tint                     spawn = (imgp->ip_flags & IMGPF_SPAWN);\n",
                b"CONFIG_CODE_DECRYPTION")),),
    "pexpert/arm/pe_serial.c": (
        (b"\tDTEntry         entryP = NULL;\n\tuint32_t        prop_size;\n",
         guarded(b"\tDTEntry         entryP = NULL;\n\tuint32_t        prop_size;\n", SERIAL_CONDITION)),
        (b"\tuintptr_t const *reg_prop;\n",
         guarded(b"\tuintptr_t const *reg_prop;\n", SERIAL_CONDITION))),
    "bsd/netinet/ip_output.c": ((
        b"\tstruct pf_rule *dn_pf_rule = NULL;\n",
        guarded(b"\tstruct pf_rule *dn_pf_rule = NULL;\n", b"DUMMYNET")), (
        b"#if PF\n#include <net/pfvar.h>\n#endif /* PF */\n",
        b"#if PF\n#include <netinet/ip_flowid.h>\n#include <net/pfvar.h>\n#endif /* PF */\n")),
    "bsd/netinet6/ip6_output.c": ((
        b"\tstruct ip6_rthdr *rh;\n",
        guarded(b"\tstruct ip6_rthdr *rh;\n", b"IPSEC")),),
    "bsd/kern/uipc_socket.c": ((
        b"\terror = soshutdownlock_final(so, how);\n\ndone:\n",
        b"\terror = soshutdownlock_final(so, how);\n\n" + guarded(b"done:\n", b"CONTENT_FILTER")),),
    "bsd/netinet/ip_input.c": ((
        b"\npass:\n\t/*\n\t * Process options",
        b"\n" + guarded(b"pass:\n", b"IPSEC") + b"\t/*\n\t * Process options"), (
        b"\tboolean_t               delete = FALSE;\n"
        b"\tstruct ip_fw_args       args1;\n"
        b"\tboolean_t               init = FALSE;\n#endif /* DUMMYNET */\n",
        b"\tboolean_t               delete = FALSE;\n#endif /* DUMMYNET */\n"
        b"#if PF || DUMMYNET\n\tstruct ip_fw_args       args1;\n"
        b"\tboolean_t               init = FALSE;\n#endif /* PF || DUMMYNET */\n")),
    "bsd/netinet6/ip6_forward.c": ((
        b"\nsent:\n", b"\n" + guarded(b"sent:\n", b"PF")), (
        b"#if DUMMYNET\n\t\tstruct ip_fw_args args;\n\t\tstruct pf_mtag *pf_mtag;\n",
        b"\t\tstruct pf_mtag *pf_mtag;\n#if DUMMYNET\n\t\tstruct ip_fw_args args;\n")),
    "bsd/skywalk/nexus/nexus_traffic_rule.c": tuple(
        (name + b"(struct nxctl_traffic_rule *ntr)\n{\n#if (DEVELOPMENT || DEBUG)\n",
         name + b"(struct nxctl_traffic_rule *ntr)\n{\n#if (DEVELOPMENT || DEBUG) && CONFIG_DTRACE\n")
        for name in (b"retain_traffic_rule", b"release_traffic_rule")),
    "bsd/vfs/vfs_syscalls.c": ((
        b"\tvnode_t vp, pvp, dvp, lvp;\n",
        b"\tvnode_t vp, dvp, lvp;\n" + guarded(b"\tvnode_t pvp;\n", b"CONFIG_FSE")),),
}


def repair_optional_defaults(relative, data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != SOURCE_HASHES[relative]:
        raise ValueError("unexpected optional default source: " + relative)
    for original, updated in REPLACEMENTS[relative]:
        if data.count(original) != 1:
            raise ValueError("unexpected optional default anchor: " + relative)
        data = data.replace(original, updated)
    return data


def stage_optional_defaults(source):
    pending = []
    report = {}
    for relative, expected in SOURCE_HASHES.items():
        target = source / relative
        after = repair_optional_defaults(relative, target.read_bytes())
        pending.append((target, after))
        report[relative] = {"original_sha256": expected,
                            "updated_sha256": hashlib.sha256(after).hexdigest()}
    for target, after in pending:
        target.write_bytes(after)
    return report
