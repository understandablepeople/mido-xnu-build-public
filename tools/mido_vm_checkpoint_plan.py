"""Exact native-4K checkpoints before VM allocation; offline only."""

import hashlib
import struct

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols
from tools.mido_native4k_profile import KERNEL_SHA256

CHECKPOINTS = ("vm-geometry", "vm-entropy-return", "vm-first-clear", "vm-first-clear-return")
TABLE_CHECKPOINTS = ("vm-second-clear-return", "vm-first-l2-return", "vm-l2-pages-ready")
SEGMENT_CHECKPOINTS = ("vm-segments-discovered", "vm-before-protection")
PROTECTION_CHECKPOINTS = ("vm-memory-map-lookup", "vm-before-text-map", "vm-before-l3-clear",
                          "vm-after-l3-clear", "vm-text-mapped", "vm-data-const-mapped")
EXECUTABLE_CHECKPOINTS = ("vm-before-executable-map", "vm-before-executable-block", "vm-first-executable-block",
                          "vm-executable-mapped", "vm-data-mapped")


def plan(kernel):
    if hashlib.sha256(kernel).hexdigest() != KERNEL_SHA256:
        raise ValueError("VM checkpoint plan requires exact reviewed native-4K kernel")
    symbols = macho_symbols(kernel)
    start = symbols["_arm_vm_init"]
    segment = next(segment for segment in inspect(kernel)["segments"]
                   if segment["vmaddr"] <= start and start + 1200 <= segment["vmaddr"] + segment["filesize"])
    offset = segment["fileoff"] + start - segment["vmaddr"]
    calls = []
    for displacement in range(0, 1200, 4):
        word = struct.unpack_from("<I", kernel, offset + displacement)[0]
        if word & 0xfc000000 != 0x94000000:
            continue
        immediate = word & 0x3ffffff
        if immediate & 0x2000000:
            immediate -= 0x4000000
        calls.append((start + displacement, start + displacement + immediate * 4))
    random_calls = [address for address, destination in calls if destination == symbols["_early_random"]]
    clears = [address for address, destination in calls if destination == symbols["_bzero"]]
    if len(random_calls) != 1 or not clears or random_calls[0] >= clears[0]:
        raise ValueError("VM startup call ordering differs")
    return dict(zip(CHECKPOINTS, (random_calls[0], random_calls[0] + 4, clears[0], clears[0] + 4)))


def table_plan(kernel):
    baseline = plan(kernel)
    symbols = macho_symbols(kernel)
    start = symbols["_arm_vm_init"]
    segment = next(segment for segment in inspect(kernel)["segments"]
                   if segment["vmaddr"] <= start and start + 1024 <= segment["vmaddr"] + segment["filesize"])
    offset = segment["fileoff"] + start - segment["vmaddr"]
    for displacement in (0x208, 0x274, 0x308):
        word = struct.unpack_from("<I", kernel, offset + displacement)[0]
        immediate = word & 0x3ffffff
        if immediate & 0x2000000:
            immediate -= 0x4000000
        if word & 0xfc000000 != 0x94000000 or start + displacement + immediate * 4 != symbols["_bzero"]:
            raise ValueError("Reviewed VM table allocation/clear call differs")
    if baseline["vm-first-clear"] != start + 0x208:
        raise ValueError("First-page checkpoint no longer agrees")
    return dict(zip(TABLE_CHECKPOINTS, (start + 0x278, start + 0x30c, start + 0x368)))


def segment_plan(kernel):
    table_plan(kernel)
    symbols = macho_symbols(kernel)
    start = symbols["_arm_vm_init"]
    segment = next(segment for segment in inspect(kernel)["segments"]
                   if segment["vmaddr"] <= start and start + 0x1244 <= segment["vmaddr"] + segment["filesize"])
    offset = segment["fileoff"] + start - segment["vmaddr"]
    sites = ((0x1170, "_vm_set_page_size"), (0x1240, "_arm_vm_prot_init"))
    for displacement, name in sites:
        word = struct.unpack_from("<I", kernel, offset + displacement)[0]
        immediate = word & 0x3ffffff
        if immediate & 0x2000000:
            immediate -= 0x4000000
        if word & 0xfc000000 != 0x94000000 or start + displacement + immediate * 4 != symbols[name]:
            raise ValueError("Reviewed VM segment boundary call differs")
    return dict(zip(SEGMENT_CHECKPOINTS, (start + displacement for displacement, _ in sites)))


def protection_plan(kernel):
    segment_plan(kernel)
    symbols = macho_symbols(kernel)
    sites = ((symbols["_arm_vm_prot_init"] + 0x134, "_SecureDTLookupEntry", 4),
             (symbols["_arm_vm_prot_init"] + 0x404, "_arm_vm_page_granular_prot", 0),
             (symbols["_arm_vm_page_granular_helper"] + 0xf0, "_bzero", 0),
             (symbols["_arm_vm_page_granular_helper"] + 0xf0, "_bzero", 4),
             (symbols["_arm_vm_prot_init"] + 0x404, "_arm_vm_page_granular_prot", 4),
             (symbols["_arm_vm_prot_init"] + 0x42c, "_arm_vm_page_granular_prot", 4))
    for address, name, _ in sites:
        segment = next(segment for segment in inspect(kernel)["segments"]
                       if segment["vmaddr"] <= address < segment["vmaddr"] + segment["filesize"])
        word = struct.unpack_from("<I", kernel, segment["fileoff"] + address - segment["vmaddr"])[0]
        immediate = word & 0x3ffffff
        if immediate & 0x2000000:
            immediate -= 0x4000000
        if word & 0xfc000000 != 0x94000000 or address + immediate * 4 != symbols[name]:
            raise ValueError("Reviewed VM protection boundary call differs")
    return dict(zip(PROTECTION_CHECKPOINTS, (address + delta for address, _, delta in sites)))


def executable_plan(kernel):
    protection_plan(kernel)
    symbols = macho_symbols(kernel)
    start = symbols["_arm_vm_prot_init"]
    sites = ((start + 0x454, 0), (start + 0x454, 4), (start + 0x47c, 4))
    for address, _ in sites:
        segment = next(segment for segment in inspect(kernel)["segments"]
                       if segment["vmaddr"] <= address < segment["vmaddr"] + segment["filesize"])
        word = struct.unpack_from("<I", kernel, segment["fileoff"] + address - segment["vmaddr"])[0]
        immediate = word & 0x3ffffff
        if immediate & 0x2000000:
            immediate -= 0x4000000
        if word & 0xfc000000 != 0x94000000 or address + immediate * 4 != symbols["_arm_vm_page_granular_prot"]:
            raise ValueError("Reviewed executable mapping call differs")
    block = symbols["_arm_vm_page_granular_prot"] + 0x200
    segment = next(segment for segment in inspect(kernel)["segments"]
                   if segment["vmaddr"] <= block < segment["vmaddr"] + segment["filesize"])
    if struct.unpack_from("<I", kernel, segment["fileoff"] + block - segment["vmaddr"])[0] != 0xf9000388:
        raise ValueError("Reviewed executable block store differs")
    return dict(zip(EXECUTABLE_CHECKPOINTS, (sites[0][0], block, block + 4, sites[1][0] + 4, sites[2][0] + 4)))
