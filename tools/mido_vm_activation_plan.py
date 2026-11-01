"""Pinned original activation control-flow plan; offline only, no table walks."""

import hashlib
import struct

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols
from tools.mido_native4k_profile import KERNEL_SHA256
from tools.mido_vm_physmap_complete_plan import complete_physmap_plan


ACTIVATION_STAGES = {
    "vm-before-ttbr1": 0x13e4,
    "vm-ttbr1-return": 0x13e8,
    "vm-before-ttbr0": 0x13f4,
    "vm-ttbr0-return": 0x13f8,
    "vm-after-activation-sync": 0x1404,
}
PINNED_SYMBOLS = {
    "_arm_vm_init": 0xfffffff007445650,
    "_set_mmu_ttb_alternate": 0xfffffff00722d838,
    "_set_mmu_ttb": 0xfffffff00722d848,
    "_cpu_ttep": 0xfffffff007162010,
    "_invalid_ttep": 0xfffffff007162008,
    "_phystokv": 0xfffffff007443ed0,
}
CALLER = (
    (0x13d8, 0x90ffe8f5, "adrp x21, 0xfffffff007162000"),
    (0x13dc, 0xf9400aa8, "ldr x8, [x21, #0x10]"),
    (0x13e0, 0x9240bd00, "and x0, x8, #0xffffffffffff"),
    (0x13e4, 0x97f79b81, "bl _set_mmu_ttb_alternate"),
    (0x13e8, 0x90ffe8f4, "adrp x20, 0xfffffff007162000"),
    (0x13ec, 0xf9400688, "ldr x8, [x20, #0x8]"),
    (0x13f0, 0x9240bd00, "and x0, x8, #0xffffffffffff"),
    (0x13f4, 0x97f79b81, "bl _set_mmu_ttb"),
    (0x13f8, 0xd508831f, "tlbi vmalle1is"),
    (0x13fc, 0xd5033b9f, "dsb ish"),
    (0x1400, 0xd5033fdf, "isb"),
    (0x1404, 0xf9400aa0, "ldr x0, [x21, #0x10]"),
    (0x1408, 0xf0ffe848, "adrp x8, 0xfffffff007151000"),
    (0x140c, 0xb9006d13, "str w19, [x8, #0x6c]"),
    (0x1410, 0x97fff51c, "bl _phystokv"),
)
SETTERS = {
    "_set_mmu_ttb_alternate": (
        (0, 0xd5033f9f, "dsb sy"),
        (4, 0xd5182020, "msr TTBR1_EL1, x0"),
        (8, 0xd5033fdf, "isb"),
        (12, 0xd65f03c0, "ret"),
    ),
    "_set_mmu_ttb": (
        (0, 0xd5033b9f, "dsb ish"),
        (4, 0xd5182000, "msr TTBR0_EL1, x0"),
        (8, 0xd5033fdf, "isb"),
        (12, 0xd65f03c0, "ret"),
    ),
}


def activation_plan(kernel):
    """Return verified call/return edges, not flattened lexical execution.

    Annotations reviewed with existing NDK llvm-objdump. Root symbols identify
    runtime storage slots, not resolved table addresses. No mapping validity
    or safe execution is implied. The bounded stop precedes root publication.
    """
    if hashlib.sha256(kernel).hexdigest() != KERNEL_SHA256:
        raise ValueError("Activation plan requires exact reviewed native-4K kernel")
    baseline = complete_physmap_plan(kernel)
    symbols = macho_symbols(kernel)
    if any(symbols.get(name) != address for name, address in PINNED_SYMBOLS.items()):
        raise ValueError("Reviewed activation symbols differ")
    start = symbols["_arm_vm_init"]
    if baseline["vm-physmap-before-ttbr"] != start + 0x13e4:
        raise ValueError("Reviewed activation boundary differs")
    segments = inspect(kernel)["segments"]

    def instructions(owner, listing):
        result = []
        for displacement, expected, assembly in listing:
            address = symbols[owner] + displacement
            matches = [segment for segment in segments
                       if segment["vmaddr"] <= address
                       and address + 4 <= segment["vmaddr"] + segment["filesize"]]
            if len(matches) != 1:
                raise ValueError("Activation instruction requires unique file backing")
            offset = matches[0]["fileoff"] + address - matches[0]["vmaddr"]
            if offset < 0 or offset + 4 > len(kernel):
                raise ValueError("Activation instruction exceeds kernel bounds")
            if struct.unpack_from("<I", kernel, offset)[0] != expected:
                raise ValueError(f"Reviewed activation bytes differ: {owner}+{displacement:#x}")
            result.append(dict(address=address, file_offset=offset,
                               bytes=struct.pack("<I", expected).hex(), assembly=assembly))
        return result

    caller = instructions("_arm_vm_init", CALLER)
    bodies = {name: instructions(name, listing) for name, listing in SETTERS.items()}
    calls = []
    for displacement, callee, register, root in (
            (0x13e4, "_set_mmu_ttb_alternate", "TTBR1_EL1", "_cpu_ttep"),
            (0x13f4, "_set_mmu_ttb", "TTBR0_EL1", "_invalid_ttep")):
        calls.append(dict(call=start + displacement, target=symbols[callee], symbol=callee,
                          return_instruction=symbols[callee] + 12,
                          return_site=start + displacement + 4, register=register,
                          root_symbol=root, root_slot=symbols[root], argument_register="x0",
                          argument="load64(root_slot) & 0x0000ffffffffffff",
                          runtime_root_value=None))
    return dict(kernel_sha256=KERNEL_SHA256, offline_only=True, boot_approved=False,
                entry=start + 0x13e4, operand_setup_start=start + 0x13d8,
                stages={name: start + displacement for name, displacement in ACTIVATION_STAGES.items()},
                caller=caller[:11], setter_bodies=bodies, calls=calls,
                caller_sync=[start + displacement for displacement in (0x13f8, 0x13fc, 0x1400)],
                stop=dict(address=start + 0x1404, exclusive=True,
                          reason="After caller synchronization; before post-activation root publication"),
                next_bounded_work=dict(instructions=caller[11:], call=start + 0x1410,
                                       target=symbols["_phystokv"], symbol="_phystokv",
                                       followed=False))
