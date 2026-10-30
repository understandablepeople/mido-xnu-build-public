"""Exact native-4K checkpoints before VM allocation; offline only."""

import hashlib
import struct

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols
from tools.mido_native4k_profile import KERNEL_SHA256

CHECKPOINTS = ("vm-geometry", "vm-entropy-return", "vm-first-clear", "vm-first-clear-return")


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
