"""Exact inactive-table model through physical-aperture publication."""

import struct
from types import MappingProxyType

from tools.mido_vm_physmap_reference import PhysmapReference, append_entry


COMPLETE_PHYSMAP_STAGES = {
    "vm-physmap-handoff-request": ("_arm_vm_init", 0x1358),
    "vm-physmap-handoff-mapped": ("_arm_vm_init", 0x135c),
    "vm-physmap-rest-request": ("_arm_vm_init", 0x1384),
    "vm-physmap-rest-mapped": ("_arm_vm_init", 0x1388),
    "vm-physmap-before-sort": ("_arm_vm_init", 0x13c0),
    "vm-physmap-sorted": ("_arm_vm_init", 0x13c4),
    "vm-physmap-before-publish": ("_arm_vm_init", 0x13d4),
    "vm-physmap-published": ("_arm_vm_init", 0x13d8),
    "vm-physmap-before-ttbr": ("_arm_vm_init", 0x13e4)}


class CompletePhysmapReference(PhysmapReference):
    """Observe physmap/end_kernel before use; allocation_limit counts 4KiB pages."""

    end_kernel = None

    def __init__(self, segments, virtual, physical, top, l2_count=1):
        super().__init__(segments, virtual, physical, top, l2_count)
        self._complete_states = {}

    def handoff_arguments(self):
        end = self.virtual + self.top - self.physical
        last = max(segment["vmaddr"] + segment["vmsize"]
                   for segment in self.segments.values() if segment["vmsize"])
        if (self.end_kernel is None or self.end_kernel & 4095
                or not last <= self.end_kernel <= end or self.top & 4095
                or not self.physical < self.top < self.physical + 0x2000000):
            raise ValueError("Unreviewed end_kernel or handoff geometry")
        return (self.end_kernel, end - self.end_kernel, 0, 1, 0, 1, 3)

    def rest_entry(self):
        self.handoff_arguments()
        if self.physmap is None:
            raise ValueError("Physmap geometry not observed")
        return append_entry([self.first_entry(self.physmap)],
                            self.virtual + self.top - self.physical,
                            self.physical + 0x2000000 - self.top, self.physmap,
                            self.virtual, self.physical, 0x2000000)

    def arguments(self, name):
        if name == "__PHYSMAP_FIRST":
            start, length, offset, *protections = super().arguments(name)
            return (start, length, offset & 0xffffffffffffffff, *protections)
        if name == "__PHYSMAP_HANDOFF":
            return self.handoff_arguments()
        if name == "__PHYSMAP_REST":
            entry = self.rest_entry()
            return (entry.virtual, entry.length,
                    (entry.virtual - (self.virtual + self.top - self.physical)) & 0xffffffffffffffff,
                    1, 0, 1, 3)
        return super().arguments(name)

    def root_for(self, address, pages):
        if not (1 << 64) - (1 << 38) <= address < 1 << 64:
            raise ValueError("Mapping escaped reviewed canonical roots")
        descriptor = struct.unpack_from("<Q", pages, 4096 + ((address >> 30) & 255)*8)[0]
        root = descriptor & 0xfffffffff000
        if descriptor & 3 != 3 or not self.top + 8192 <= root < self.top + 56*4096:
            raise ValueError("Mapping escaped allocated L2 roots")
        return root

    def complete_state(self, through):
        key = (through, self.physmap, self.end_kernel, self.l2_count)
        if key not in self._complete_states:
            pages, writes, roots = self._build_complete_state(through)
            self._complete_states[key] = (pages, MappingProxyType(writes), frozenset(roots))
        return self._complete_states[key]

    def _build_complete_state(self, through):
        pages = bytearray(super().expected("vm-physmap-first-mapped"))
        writes, roots = {}, set()
        requests = ("__PHYSMAP_HANDOFF", "__PHYSMAP_REST")
        for name in requests[:requests.index(through) + 1]:
            writes, roots = {}, set()
            start, length, offset, _, _, _, _ = self.arguments(name)
            end = start + length
            if start & 4095 or end & 4095 or end > 1 << 64:
                raise ValueError("Unreviewed complete physmap interval")
            for group in range(start & ~0x1fffff, end, 0x200000):
                lower, upper = max(start, group), min(end, group + 0x200000)
                if lower == upper:
                    continue
                root = self.root_for(lower, pages)
                roots.add(root)
                link = root + ((group >> 21) & 511)*8
                old = struct.unpack_from("<Q", pages, link - self.top)[0]
                physical = (lower - self.virtual + self.physical - offset) & 0xffffffffffffffff
                if not self.physical <= physical < physical + upper - lower <= self.physical + 0x2000000:
                    raise ValueError("Mapping escaped physical arena")
                if lower == group and upper == group + 0x200000:
                    if physical & 0x1fffff or old:
                        raise ValueError("Block would replace an existing mapping")
                    value = physical | 0x0060000000000601
                    struct.pack_into("<Q", pages, link - self.top, value)
                    writes[link] = (value, "block")
                    continue
                if old:
                    table = old & 0xfffffffff000
                    if old & 3 != 3 or not self.top <= table < self.top + len(pages):
                        raise ValueError("Page mapping would replace a block")
                else:
                    table = self.top + len(pages)
                    pages.extend(bytes(4096))
                    struct.pack_into("<Q", pages, link - self.top, table | 3)
                    writes[link] = (table | 3, "link")
                for address in range(lower, upper, 4096):
                    page_physical = (address - self.virtual + self.physical - offset) & 0xffffffffffffffff
                    value = page_physical | 0x0060000000000603
                    if address >= ((start + 65535) & ~65535) and ((address + 65536) & ~65535) <= upper:
                        if (address & 65535) != (page_physical & 65535):
                            raise ValueError("Contiguous hint alignment differs")
                        value |= 1 << 52
                    destination = table + ((address >> 12) & 511)*8
                    if struct.unpack_from("<Q", pages, destination - self.top)[0]:
                        raise ValueError("Page would replace an existing mapping")
                    struct.pack_into("<Q", pages, destination - self.top, value)
                    writes[destination] = (value, "page")
        return bytes(pages), writes, roots

    def expected(self, checkpoint):
        if checkpoint not in COMPLETE_PHYSMAP_STAGES:
            return super().expected(checkpoint)
        if checkpoint == "vm-physmap-handoff-request":
            return super().expected("vm-physmap-first-mapped")
        request = "__PHYSMAP_HANDOFF" if checkpoint in (
            "vm-physmap-handoff-mapped", "vm-physmap-rest-request") else "__PHYSMAP_REST"
        return self.complete_state(request)[0]

    def allowed_l2_roots(self):
        if self.request in ("__PHYSMAP_HANDOFF", "__PHYSMAP_REST"):
            return self.complete_state(self.request)[2]
        if self.request is None:
            return set()
        start, length, *_ = self.arguments(self.request)
        pages = super().expected("vm-physmap-first-mapped")
        return {self.root_for(address, pages)
                for address in range(start, start + length, 4096)}

    def allocation_limit(self):
        return len(self.complete_state("__PHYSMAP_REST")[0]) // 4096

    def accepts(self, address, length, value, pc, helper):
        if self.request not in ("__PHYSMAP_HANDOFF", "__PHYSMAP_REST"):
            return super().accepts(address, length, value, pc, helper)
        if length != 8:
            return False
        _, writes, _ = self.complete_state(self.request)
        expected = writes.get(address)
        if expected is None or expected[0] != value:
            return False
        kind = expected[1]
        granular = helper - 0x300
        return ((kind == "link" and pc == helper + 0x128)
                or (kind == "page" and pc == helper + 0x210)
                or (kind == "block" and pc == granular + 0x200))
