"""Exact inactive dynamic-root allocations before physmap construction."""

import struct

from tools.mido_vm_postmap_reference import PostmapReference


DYNAMIC_STAGES = {
    "vm-dynamic-entry": 0x1614,
    "vm-dynamic-before-first-link": 0x1680,
    "vm-dynamic-before-first-clear": 0x1684,
    "vm-dynamic-first-cleared": 0x1688,
    "vm-dynamic-roots-ready": 0x12d4,
    "vm-user-tbi-checked": 0x12f4,
    "vm-physmap-before-scratch-clear": 0x1300,
    "vm-physmap-entry": 0x1304}


class DynamicReference(PostmapReference):
    def __init__(self, segments, virtual, physical, top, l2_count=1):
        super().__init__(segments, virtual, physical, top, l2_count)
        self.dynamic_slots = tuple(range(192 + l2_count, 240))
        self.dynamic_links = None

    def links(self):
        if self.dynamic_links is None:
            first = self.top + len(super().expected("vm-lowglobals-cleared"))
            self.dynamic_links = {self.top + 4096 + slot * 8:
                                  (first + index * 4096) | 0x3800000000000003
                                  for index, slot in enumerate(self.dynamic_slots)}
        return self.dynamic_links

    def accepts_dynamic_link(self, address, length, value, pc, arm_vm_init):
        return (pc == arm_vm_init + 0x1680 and length == 8
                and self.links().get(address) == value)

    def expected(self, checkpoint):
        if checkpoint not in DYNAMIC_STAGES:
            return super().expected(checkpoint)
        base = super().expected("vm-lowglobals-cleared")
        if checkpoint in ("vm-dynamic-entry", "vm-dynamic-before-first-link"):
            return base
        count = 1 if checkpoint in ("vm-dynamic-before-first-clear", "vm-dynamic-first-cleared") else len(self.dynamic_slots)
        pages = bytearray(base + bytes(count * 4096))
        for address, value in list(self.links().items())[:count]:
            struct.pack_into("<Q", pages, address - self.top, value)
        if checkpoint == "vm-dynamic-before-first-clear":
            pages[-4096:] = bytes([165]) * 4096
        if count == len(self.dynamic_slots) and len(pages) != 56 * 4096:
            raise ValueError("Dynamic roots escaped the exact 56-page model")
        return bytes(pages)
