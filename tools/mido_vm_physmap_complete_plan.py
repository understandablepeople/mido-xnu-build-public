"""Exact remaining native-4K physmap checkpoints; offline planning only."""

import hashlib
import struct

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols
from tools.mido_native4k_profile import KERNEL_SHA256
from tools.mido_vm_checkpoint_plan import physmap_plan


COMPLETE_PHYSMAP_STAGES = {
    "vm-physmap-handoff-request": 0x1358,
    "vm-physmap-handoff-mapped": 0x135c,
    "vm-physmap-rest-request": 0x1384,
    "vm-physmap-rest-mapped": 0x1388,
    "vm-physmap-before-sort": 0x13c0,
    "vm-physmap-sorted": 0x13c4,
    "vm-physmap-before-publish": 0x13d4,
    "vm-physmap-published": 0x13d8,
    "vm-physmap-before-ttbr": 0x13e4,
}


def complete_physmap_plan(kernel):
    """Return caller-local boundaries, stopping before TTBR activation.

    Helper destinations establish call edges, not lexical execution order.
    """
    if hashlib.sha256(kernel).hexdigest() != KERNEL_SHA256:
        raise ValueError("Complete physmap plan requires exact reviewed native-4K kernel")
    physmap_plan(kernel)
    symbols = macho_symbols(kernel)
    segments = inspect(kernel)["segments"]
    calls = (
        ("_arm_vm_init", 0x131c, "_arm_vm_physmap_slide"),
        ("_arm_vm_init", 0x1330, "_phystokv"),
        ("_arm_vm_init", 0x1358, "_arm_vm_page_granular_prot"),
        ("_arm_vm_init", 0x1384, "_arm_vm_physmap_slide"),
        ("_arm_vm_physmap_slide", 0x108, "_arm_vm_page_granular_prot"),
        ("_arm_vm_init", 0x13c0, "_qsort.specialized.1"),
        ("_arm_vm_init", 0x13d4, "_memmove"),
        ("_arm_vm_init", 0x13e4, "_set_mmu_ttb_alternate"),
        ("_arm_vm_init", 0x13f4, "_set_mmu_ttb"),
    )
    for caller, displacement, callee in calls:
        address = symbols[caller] + displacement
        segment = next((segment for segment in segments
                        if segment["vmaddr"] <= address
                        and address + 4 <= segment["vmaddr"] + segment["filesize"]), None)
        if segment is None:
            raise ValueError("Reviewed complete physmap call is not file-backed")
        offset = segment["fileoff"] + address - segment["vmaddr"]
        if offset < 0 or offset + 4 > len(kernel):
            raise ValueError("Reviewed complete physmap call exceeds kernel bounds")
        word = struct.unpack_from("<I", kernel, offset)[0]
        immediate = word & 0x3ffffff
        if immediate & 0x2000000:
            immediate -= 0x4000000
        if word & 0xfc000000 != 0x94000000 or address + immediate * 4 != symbols[callee]:
            raise ValueError(f"Reviewed complete physmap BL differs: {caller}+{displacement:#x} -> {callee}")
    start = symbols["_arm_vm_init"]
    return {name: start + displacement for name, displacement in COMPLETE_PHYSMAP_STAGES.items()}
