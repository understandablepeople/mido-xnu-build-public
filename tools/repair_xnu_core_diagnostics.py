"""Keep numeric ABI assertions and reject invalid hash bucket selectors."""

import hashlib
import re


SOURCE_HASHES = {
    "bsd/skywalk/mem/skmem_region.c": "197e5c41600bede3b7b0363944fc6ebef39d2143bea20c865e54d60583956d01",
    "bsd/skywalk/mem/skmem_arena.c": "0581a24332d627714620b6af20e1e48963432d4f60f170ab22e70932688de68e",
    "osfmk/kern/smr_hash.h": "1d0774bdfd6af86d4dfc2fda55f1713feac4e6031c6f4b1603e67ec75ffcbfa9",
}


def repair_numeric_enum_assertions(data, arena):
    if arena:
        pattern = rb"static_assert\((SKMEM_ARENA_TYPE_[A-Z_]+) == (SAR_TYPE_[A-Z_]+)\);"
        expected = 3
    else:
        pattern = rb"_CASSERT\((SREG_[A-Z_]+) == (SKMEM_REGION_[A-Z_]+)\);"
        expected = 27
    matches = list(re.finditer(pattern, data))
    if len(matches) != expected:
        raise ValueError("unexpected Skywalk numeric enum assertions")
    for match in reversed(matches):
        replacement = match.group(0).replace(match[1] + b" == " + match[2],
                                            b"(int)" + match[1] + b" == (int)" + match[2])
        data = data[:match.start()] + replacement + data[match.end():]
    return data


def repair_smr_bucket_selector(data):
    original = b"\tswitch (sel) {\n\tcase SMRSH_CUR:\n"
    include = b"#include <kern/counter.h>\n"
    if (data.count(original) != 1 or data.count(b"\tcase SMRSH_NEW:\n") != 1 or
            data.count(include) != 1 or b"#include <kern/debug.h>" in data):
        raise ValueError("unexpected SMR bucket selector")
    data = data.replace(include, include + b"#include <kern/debug.h>\n")
    return data.replace(original, b"\tswitch (sel) {\n\tdefault:\n"
                        b'\t\tpanic("invalid SMR hash bucket selector");\n\tcase SMRSH_CUR:\n')


def repair_core_diagnostics(relative, data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != SOURCE_HASHES[relative]:
        raise ValueError("unexpected core diagnostic source: " + relative)
    if relative.endswith("smr_hash.h"):
        return repair_smr_bucket_selector(data)
    return repair_numeric_enum_assertions(data, relative.endswith("skmem_arena.c"))


def stage_core_diagnostics(source):
    pending = []
    report = {}
    for relative, expected in SOURCE_HASHES.items():
        target = source / relative
        after = repair_core_diagnostics(relative, target.read_bytes())
        pending.append((target, after))
        report[relative] = {"original_sha256": expected,
                            "updated_sha256": hashlib.sha256(after).hexdigest()}
    for target, after in pending:
        target.write_bytes(after)
    return report
