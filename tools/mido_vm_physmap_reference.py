"""Bounded native-4K physical-aperture preparation and first inactive mapping."""

from dataclasses import dataclass
import struct

from tools.mido_vm_dynamic_reference import DynamicReference


PHYSMAP_STAGES = {
    "vm-physmap-first-request": ("_arm_vm_init", 0x131c),
    "vm-physmap-first-entry": ("_arm_vm_physmap_slide", 0),
    "vm-physmap-first-map-call": ("_arm_vm_physmap_slide", 0x108),
    "vm-physmap-first-mapped": ("_arm_vm_init", 0x1320)}


@dataclass(frozen=True)
class PhysmapEntry:
    physical: int
    virtual: int
    length: int

    def encode(self):
        return struct.pack("<QQQ", self.physical, self.virtual, self.length)


def append_entry(entries, original, length, physmap, virtual, physical, memory_size):
    if (len(entries) >= 8 or original & 4095 or length <= 0
            or not physical <= physical + original - virtual
            or physical + original - virtual + length > physical + memory_size
            or physmap & 4095 or not 0 <= physmap < 1 << 64):
        raise ValueError("Unreviewed physical-aperture request")
    target_pa = physical + original - virtual
    candidate = entries[-1].virtual + entries[-1].length if entries else physmap
    target_va = candidate + ((target_pa - candidate) & 0x1fffff)
    rounded = (length + 4095) & ~4095
    if (target_va + rounded > 1 << 64 or target_va < (1 << 64) - (1 << 38)
            or target_pa + rounded > physical + memory_size):
        raise ValueError("Physical-aperture request exceeds reviewed address bounds")
    return PhysmapEntry(target_pa, target_va, rounded)


class PhysmapReference(DynamicReference):
    physmap = None

    def expected(self, checkpoint):
        if checkpoint == "vm-physmap-first-mapped":
            pages = bytearray(super().expected("vm-physmap-entry") + bytes(4096))
            link, value, leaves = self.first_descriptors()
            struct.pack_into("<Q", pages, link-self.top, value)
            for address, descriptor in leaves.items():
                struct.pack_into("<Q", pages, address-self.top, descriptor)
            return bytes(pages)
        if checkpoint in PHYSMAP_STAGES:
            return super().expected("vm-physmap-entry")
        return super().expected(checkpoint)

    def first_entry(self, physmap):
        return append_entry([], self.virtual, 0x4000, physmap, self.virtual,
                            self.physical, 0x2000000)

    def first_arguments(self, physmap):
        entry = self.first_entry(physmap)
        return (entry.virtual, entry.length, entry.virtual-self.virtual, 1, 0, 1, 3)

    def first_descriptors(self):
        if self.physmap is None:
            raise ValueError("Physmap geometry not observed")
        entry = self.first_entry(self.physmap)
        root = ((entry.virtual >> 30) & 255) - ((self.virtual >> 30) & 255)
        if not 0 <= root < 48 or entry.virtual & 0x1fffff:
            raise ValueError("First physmap mapping escaped preallocated roots")
        page = self.top + 56*4096
        root_page = 2 + root if root < self.l2_count else 8 + root
        link = self.top + root_page*4096 + ((entry.virtual >> 21) & 511)*8
        leaves = {page+index*8: (entry.physical+index*4096) | 0x0060000000000603
                  for index in range(4)}
        return link, page | 3, leaves

    def arguments(self, name):
        if name == "__PHYSMAP_FIRST":
            return self.first_arguments(self.physmap)
        return super().arguments(name)

    def accepts(self, address, length, value, pc, helper):
        if self.request != "__PHYSMAP_FIRST":
            return super().accepts(address, length, value, pc, helper)
        if length != 8:
            return False
        link, descriptor, leaves = self.first_descriptors()
        return ((pc == helper+0x128 and (address, value) == (link, descriptor))
                or (pc == helper+0x210 and leaves.get(address) == value))
