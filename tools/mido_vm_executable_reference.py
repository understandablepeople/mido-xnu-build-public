"""Independent inactive L2-block/L3-page model through TEXT_EXEC and DATA."""

import struct

from tools.mido_vm_protection_reference import ProtectionReference


class ExecutableReference(ProtectionReference):
    names = ("__TEXT", "__DATA_CONST", "__TEXT_EXEC", "__DATA")

    def __init__(self, segments, virtual, physical, top, l2_count=1):
        super().__init__(segments, virtual, physical, top, l2_count)
        self.states = {}

    def arguments(self, name):
        if name in ("__TEXT", "__DATA_CONST"):
            return super().arguments(name)
        segment = self.segments[name]
        if name == "__TEXT_EXEC":
            return (segment["vmaddr"], segment["vmsize"], 0, 0, 2, 0, 3)
        if name == "__DATA":
            return (segment["vmaddr"], segment["vmsize"], 0, 1, 0, 1, 3)
        raise ValueError("Unreviewed executable mapping request")

    def mappings(self, name, limit=None):
        start, length, _, block_xn, access, page_xn, granule = self.arguments(name)
        end = start + length
        if start & 4095 or end & 4095 or not self.virtual <= start < end <= self.virtual + 0x2000000:
            raise ValueError("Executable mapping escaped contained arena")
        effective_end = min(end, limit) if limit is not None else end
        for group in range(start & ~0x1fffff, effective_end, 0x200000):
            lower, upper = max(start, group), min(effective_end, group + 0x200000)
            if lower == group and upper == group + 0x200000 and granule & 1:
                physical = group - self.virtual + self.physical
                if physical & 0x1fffff:
                    raise ValueError("Unaligned physical block")
                yield group, physical | 0x0040000000000601 | (block_xn << 53) | (access << 6), True
            else:
                for address in range(lower, upper, 4096):
                    physical = address - self.virtual + self.physical
                    value = physical | 0x0040000000000603 | (page_xn << 53) | (access << 6)
                    if granule & 2 and address >= ((start + 65535) & ~65535) and ((address + 65536) & ~65535) <= end:
                        if (address & 65535) != (physical & 65535):
                            raise ValueError("Contiguous hint alignment differs")
                        value |= 1 << 52
                    yield address, value, False

    def state(self, name, limit=None):
        if (name, limit) in self.states:
            return self.states[name, limit]
        layout, descriptors = {}, {}
        for current in self.names[:self.names.index(name) + 1]:
            for address, value, block in self.mappings(current, limit if current == name else None):
                group = (address - self.virtual) >> 21
                slot = (address >> 21) & 511
                if block:
                    if group in layout:
                        raise ValueError("Block would replace an existing L3 table")
                    destination = self.top + 8192 + slot * 8
                else:
                    if group not in layout:
                        layout[group] = self.l3_base + len(layout) * 4096
                    descriptors[self.top + 8192 + slot * 8] = layout[group] | 3
                    destination = layout[group] + ((address >> 12) & 511) * 8
                descriptors[destination] = value
        self.states[name, limit] = (layout, descriptors)
        return layout, descriptors

    def accepts(self, address, length, value, pc, helper):
        if self.request is None or length != 8:
            return False
        layout, descriptors = self.state(self.request)
        granular = helper - 0x300
        if pc == helper + 0x128:
            return address in (self.top + 8192 + (((self.virtual + group * 0x200000) >> 21) & 511) * 8
                               for group in layout) and descriptors.get(address) == value
        if pc == helper + 0x210:
            return address >= self.l3_base and descriptors.get(address) == value
        if pc == granular + 0x200:
            return self.top + 8192 <= address < self.top + 12288 and value & 3 == 1 and descriptors.get(address) == value
        if pc in (granular + 0x260, granular + 0x26c):
            return descriptors.get(address) == value
        return False

    def expected(self, checkpoint):
        first_block = (self.segments["__TEXT_EXEC"]["vmaddr"] + 0x1fffff) & ~0x1fffff
        stages = {
            "vm-before-executable-map": ("__DATA_CONST", None),
            "vm-before-executable-block": ("__TEXT_EXEC", first_block),
            "vm-first-executable-block": ("__TEXT_EXEC", first_block + 0x200000),
            "vm-executable-mapped": ("__TEXT_EXEC", None),
            "vm-data-mapped": ("__DATA", None)}
        if checkpoint not in stages:
            return super().expected(checkpoint)
        name, limit = stages[checkpoint]
        layout, descriptors = self.state(name, limit)
        pages = bytearray((2 + self.l2_count + len(layout)) * 4096)
        for index in range(self.l2_count):
            struct.pack_into("<Q", pages, 4096 + (((self.virtual >> 30) & 255) + index) * 8,
                             (self.top + 8192 + index*4096) | 0x2000000000000003)
        for address, value in descriptors.items():
            struct.pack_into("<Q", pages, address - self.top, value)
        return bytes(pages)
