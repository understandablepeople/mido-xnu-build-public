"""Read-only walk of the pinned inactive TTBR1 snapshot; never activation approval."""

import argparse
import hashlib
import json
from pathlib import Path
import struct

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols
from tools.mido_vm_checkpoint_plan import postmap_plan
from tools.mido_vm_postmap_reference import PostmapReference


TCR = 0x22a51a251a
VIRTUAL = 0xfffffff007000000
PHYSICAL = 0x11200000
TOP = 0x12401000


def walk(snapshot, address, top=TOP, tcr=TCR):
    if tcr != TCR or len(snapshot) % 4096 or len(snapshot) < 12288 or top & 4095:
        raise ValueError("Requires the reviewed 4KiB/38-bit TTBR1 snapshot")
    if not 0 <= address < 1 << 64 or address < (1 << 64) - (1 << 38):
        return dict(mapped=False, reason="outside-reviewed-ttbr1-range")
    table = top + 4096
    readonly = noexecute = nouser = False
    trace = []
    for level, shift, mask in ((1, 30, 255), (2, 21, 511), (3, 12, 511)):
        offset = table - top + ((address >> shift) & mask) * 8
        if not 0 <= offset <= len(snapshot) - 8:
            return dict(mapped=False, reason="table-outside-snapshot", trace=trace)
        descriptor = struct.unpack_from("<Q", snapshot, offset)[0]
        trace.append(dict(level=level, table=table, descriptor=descriptor))
        kind = descriptor & 3
        if kind == 0 or kind == 2 or level == 3 and kind != 3:
            return dict(mapped=False, reason="invalid-descriptor", trace=trace)
        if level < 3 and kind == 3:
            readonly |= bool(descriptor & (1 << 62))
            nouser |= bool(descriptor & (1 << 61))
            noexecute |= bool(descriptor & (1 << 59))
            table = descriptor & 0x0000fffffffff000
            continue
        size = 1 << shift
        physical = (descriptor & 0x0000fffffffff000 & -size) | (address & (size - 1))
        return dict(mapped=True, physical=physical, leaf_level=level,
                    writable=not readonly and not bool(descriptor & (1 << 7)),
                    executable=not noexecute and not bool(descriptor & (1 << 53)),
                    user_accessible=not nouser and bool(descriptor & (1 << 6)),
                    access_flag=bool(descriptor & (1 << 10)), trace=trace)
    raise AssertionError("Missing terminal translation descriptor")


def run(kernel_path, output):
    kernel = kernel_path.read_bytes()
    postmap_plan(kernel)
    symbols = macho_symbols(kernel)
    segments = inspect(kernel)["segments"]
    requests = {
        "continuation-code": (symbols["_arm_vm_init"] + 0x12c8, "execute"),
        "exception-vector": (0xfffffff00722c000, "execute"),
        "live-stack": (0xfffffff007c9b000, "write"),
        "return-observer": (0xfffffff008200000, "execute"),
        "original-boot-args": (0xfffffff008000000, "read"),
        "low-globals": (0xfffffff000000000, "read")}
    for name in ("_intstack_low_guard", "_intstack_high_guard", "_excepstack_high_guard"):
        for offset in range(0, 16384, 4096):
            requests[f"{name}-page-{offset // 4096}"] = (symbols[name] + offset, "readonly-nx")
    cases = {}
    for count in (1, 2):
        snapshot = PostmapReference(segments, VIRTUAL, PHYSICAL, TOP, count).expected("vm-lowglobals-cleared")
        geometry = {}
        for name, (address, requirement) in requests.items():
            result = walk(snapshot, address)
            allowed = result["mapped"] and result.get("access_flag", False)
            if requirement == "execute":
                allowed = allowed and result.get("executable", False)
            elif requirement == "write":
                allowed = allowed and result.get("writable", False)
            elif requirement == "readonly-nx":
                allowed = allowed and not result.get("writable", True) and not result.get("executable", True)
            expected_available = name not in ("return-observer", "original-boot-args", "low-globals")
            if bool(allowed) != expected_available:
                raise AssertionError(f"Unexpected snapshot translation: {count}/{name}")
            if result["mapped"] and result["physical"] != address - VIRTUAL + PHYSICAL:
                raise AssertionError(f"Unexpected physical destination: {count}/{name}")
            geometry[name] = dict(address=address, requirement=requirement, available=bool(allowed),
                                  expected_available=expected_available, passed=True, translation=result)
        cases[str(count)] = geometry
    report = dict(scope="Independent model snapshot walk, not original-kernel execution or final TTBR readiness",
                  kernel_sha256=hashlib.sha256(kernel).hexdigest(), cases=cases,
                  passed=sum(case["passed"] for group in cases.values() for case in group.values()),
                  total=sum(len(group) for group in cases.values()), model_only=True,
                  immediate_switch_safe=False, hardware_execution_proven=False,
                  blockers=["Return observer is not mapped in this pre-physmap snapshot",
                            "Original boot_args alias is not mapped in this pre-physmap snapshot",
                            "Low-global L3 exists but its entries are still invalid",
                            "Original dynamic-table and physmap initialization has not been validated"],
                  device_commands_executed=False)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.kernel, args.output)
    print(f"PASS {report['passed']}/{report['total']} expected snapshot outcomes; immediate TTBR switch NOT approved")
