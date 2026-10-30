"""Bounded physmap slide geometry, preserving the kernel's original entropy."""


def l2_count(virtual, physical, top, physmap, static_end, memory_size):
    slide = physmap - (virtual + top - physical)
    if (memory_size != 0x2000000 or not 0 <= slide < 0x40000000 or slide & 4095
            or static_end != physmap + memory_size + 0x1000000):
        raise ValueError("Unreviewed physmap slide geometry")
    count = (static_end - virtual + 0x3fffffff) >> 30
    if count not in (1, 2):
        raise ValueError("Unreviewed physmap L2 count")
    return count
