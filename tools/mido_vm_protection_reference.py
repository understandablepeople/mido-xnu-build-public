"""Independent five-page reference for the first two inactive VM mappings."""

import struct


class ProtectionReference:
    def __init__(self, segments, virtual, physical, top):
        self.virtual = virtual
        self.physical = physical
        self.top = top
        self.segments = {segment["name"]: segment for segment in segments}
        self.request = None

    def arguments(self, name):
        segment = self.segments[name]
        if name == "__TEXT":
            return (segment["vmaddr"], segment["vmsize"], 0, 1, 2, 1, 3)
        if name == "__DATA_CONST":
            return (segment["vmaddr"], segment["vmsize"], 0, 1, 0, 1, 1)
        raise ValueError("Unreviewed protection request")

    def leaves(self, name):
        start, length, _, _, access, _, granule = self.arguments(name)
        end = start + length
        if start & 4095 or end & 4095 or not self.virtual <= start < end <= self.virtual + 0x400000:
            raise ValueError("Protection request escaped the first two L3 tables")
        descriptors = {}
        for address in range(start, end, 4096):
            physical = address - self.virtual + self.physical
            descriptor = physical | 0x0060000000000603 | (access << 6)
            if granule & 2 and address >= ((start + 65535) & ~65535) and ((address + 65536) & ~65535) <= end:
                if (address & 65535) != (physical & 65535):
                    raise ValueError("Contiguous hint VA/PA alignment differs")
                descriptor |= 1 << 52
            table = self.top + 12288 + ((address - self.virtual) >> 21) * 4096
            descriptors[table + ((address >> 12) & 511) * 8] = descriptor
        return descriptors

    def link(self, index=0):
        slot = ((self.virtual >> 21) & 511) + index
        return self.top + 8192 + slot * 8, (self.top + 12288 + index * 4096) | 3

    def accepts(self, address, length, value, pc, helper):
        if self.request is None or length != 8:
            return False
        if pc == helper + 0x128:
            return (address, value) in [self.link(index) for index in range(2 if self.request == "__DATA_CONST" else 1)]
        if pc == helper + 0x210:
            return self.leaves(self.request).get(address) == value
        return False

    def expected(self, checkpoint):
        count = 3 if checkpoint in ("vm-memory-map-lookup", "vm-before-text-map") else 4
        if checkpoint == "vm-data-const-mapped":
            count = 5
        pages = bytearray(count * 4096)
        struct.pack_into("<Q", pages, 4096 + ((self.virtual >> 30) & 255) * 8,
                         (self.top + 8192) | 0x2000000000000003)
        if checkpoint == "vm-before-l3-clear":
            pages[12288:] = bytes([165]) * 4096
        if checkpoint in ("vm-text-mapped", "vm-data-const-mapped"):
            address, value = self.link()
            struct.pack_into("<Q", pages, address - self.top, value)
            if checkpoint == "vm-data-const-mapped":
                address, value = self.link(1)
                struct.pack_into("<Q", pages, address - self.top, value)
            names = ("__TEXT", "__DATA_CONST") if checkpoint == "vm-data-const-mapped" else ("__TEXT",)
            for name in names:
                for address, value in self.leaves(name).items():
                    struct.pack_into("<Q", pages, address - self.top, value)
        return bytes(pages)
