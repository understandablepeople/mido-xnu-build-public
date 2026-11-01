"""Offline final-table audit; never authorization to activate TTBRs.

Independent decoding for the reviewed TCR: 38-bit untagged VAs, 4KiB pages,
40-bit PAs, no descriptor extensions. Permissions include AF and hierarchical
AP/PXN/UXN, not SCTLR, PAN, MAIR, security state or actual TTBR installation.
"""

import argparse
import hashlib
import json
from pathlib import Path
import struct


TCR = 0x22a51a251a
TOP = 0x12401000
VIRTUAL = 0xfffffff007000000
PHYSICAL = 0x11200000
PA_MASK = ((1 << 40) - 1) & ~4095
PAGE_SIZE = 4096


def walk(snapshot, address, top=TOP, tcr=TCR):
    """Translate using TTBR0 at top and TTBR1 at top+4096.

    Invalid geometry raises ValueError. Failed walks return mapped=False and
    deny all permissions. Every referenced table must be wholly in snapshot.
    """
    snapshot = bytes(snapshot)
    if (tcr != TCR or top < 0 or top & 4095 or len(snapshot) < 8192
            or len(snapshot) % PAGE_SIZE or top + len(snapshot) > 1 << 40):
        raise ValueError("Requires reviewed 4KiB/38-bit/40-bit-PA snapshot geometry")
    trace = []

    def denied(reason):
        return dict(mapped=False, reason=reason, physical=None, writable=False,
                    executable=False, user_accessible=False, user_writable=False,
                    user_executable=False, trace=trace)

    if not isinstance(address, int) or not 0 <= address < 1 << 64:
        return denied("noncanonical-address")
    if address < 1 << 38:
        root = 0
    elif address >= (1 << 64) - (1 << 38):
        root = 1
    else:
        return denied("noncanonical-address")
    table = top + root * PAGE_SIZE
    visited = set()
    readonly = nouser = pxn = uxn = False
    for level, shift in ((1, 30), (2, 21), (3, 12)):
        if not top <= table <= top + len(snapshot) - PAGE_SIZE:
            return denied("table-outside-snapshot")
        if table in visited:
            return denied("cyclic-table-reference")
        visited.add(table)
        index = (address >> shift) & (255 if level == 1 else 511)
        slot = table + index * 8
        descriptor = struct.unpack_from("<Q", snapshot, slot - top)[0]
        kind = descriptor & 3
        trace.append(dict(level=level, table=table, index=index, slot=slot,
                          descriptor=descriptor))
        if not descriptor & 1:
            return denied("unmapped" if descriptor == 0 else "invalid-descriptor")
        if level < 3 and kind == 3:
            if descriptor & ~(PA_MASK | 3 | (31 << 59)):
                return denied("malformed-table-descriptor")
            trace[-1].update(kind="table", next_table=descriptor & PA_MASK,
                             ap_table=(descriptor >> 61) & 3,
                             pxn_table=bool(descriptor & (1 << 59)),
                             uxn_table=bool(descriptor & (1 << 60)),
                             ns_table=bool(descriptor & (1 << 63)))
            readonly |= bool(descriptor & (1 << 62))
            nouser |= bool(descriptor & (1 << 61))
            uxn |= bool(descriptor & (1 << 60))
            pxn |= bool(descriptor & (1 << 59))
            table = descriptor & PA_MASK
            continue
        if level == 3 and kind != 3:
            return denied("invalid-page-descriptor")
        size = 1 << shift
        if descriptor & ~(PA_MASK | 0xfff | (7 << 52)) or descriptor & PA_MASK & (size - 1):
            return denied("malformed-leaf-descriptor")
        shareability = (descriptor >> 8) & 3
        if shareability == 1:
            return denied("reserved-shareability")
        access = (descriptor >> 6) & 3
        af = bool(descriptor & (1 << 10))
        user = not nouser and bool(access & 1)
        write = af and not readonly and not bool(access & 2)
        trace[-1]["kind"] = "page" if level == 3 else "block"
        return dict(mapped=True, physical=(descriptor & PA_MASK) | (address & (size - 1)),
                    root=root, leaf_level=level, mapping_size=size,
                    writable=write, executable=af and not pxn and not bool(descriptor & (1 << 53)),
                    user_accessible=af and user, user_writable=user and write,
                    user_executable=af and user and not uxn and not bool(descriptor & (1 << 54)),
                    access_flag=af, ap=access, attr_index=(descriptor >> 2) & 7,
                    pxn=bool(descriptor & (1 << 53)), uxn=bool(descriptor & (1 << 54)),
                    shareability=shareability, non_secure=bool(descriptor & (1 << 5)),
                    not_global=bool(descriptor & (1 << 11)),
                    contiguous=bool(descriptor & (1 << 52)), trace=trace)
    raise AssertionError("No terminal descriptor")


def audit(snapshot, execution_site, top=TOP):
    """Audit the five live addresses without modifying table bytes."""
    requests = {"observer": (0xfffffff008200000, "execute"),
                "observer-low-identity": (0x12400000, "execute"),
                "stack": (0xfffffff007c9bff0, "write"),
                "vbar": (0xfffffff00722c000, "execute"),
                "original-execution-site": (execution_site, "execute")}
    cases = {}
    for name, (address, requirement) in requests.items():
        translation = walk(snapshot, address, top)
        available = translation["writable" if requirement == "write" else "executable"]
        cases[name] = dict(address=address, requirement=requirement,
                           available=available, translation=translation)
    return dict(checkpoint="vm-physmap-before-ttbr", snapshot_pages=len(snapshot) // PAGE_SIZE,
                snapshot_sha256=hashlib.sha256(snapshot).hexdigest(), cases=cases,
                model_only=True, immediate_switch_safe=False,
                hardware_execution_proven=False, device_commands_executed=False,
                blockers=[name for name, case in cases.items() if not case["available"]])


def run(kernel_path, output=None):
    """Build the pinned final model as input; decoding remains independent."""
    from tools.inspect_xnu import inspect
    from tools.mido_macho_symbols import macho_symbols
    from tools.mido_native4k_profile import KERNEL_SHA256
    from tools.mido_vm_physmap_complete_reference import CompletePhysmapReference

    kernel = Path(kernel_path).read_bytes()
    digest = hashlib.sha256(kernel).hexdigest()
    if digest != KERNEL_SHA256:
        raise ValueError("Kernel does not match pinned native-4K SHA256")
    reference = CompletePhysmapReference(inspect(kernel)["segments"], VIRTUAL, PHYSICAL, TOP)
    reference.physmap = VIRTUAL + TOP - PHYSICAL
    reference.end_kernel = VIRTUAL + 0xf6c000
    snapshot = reference.expected("vm-physmap-before-ttbr")
    if len(snapshot) != 59 * PAGE_SIZE:
        raise ValueError("Expected exact 59-page final snapshot")
    report = audit(snapshot, macho_symbols(kernel)["_arm_vm_init"] + 0x13e4)
    report["kernel_sha256"] = digest
    if output is not None:
        Path(output).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    print(json.dumps(run(arguments.kernel, arguments.output), indent=2))
