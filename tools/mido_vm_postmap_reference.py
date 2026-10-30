"""Independent low-global table model before any TCR or TTBR change."""

import struct

from tools.mido_vm_remaining_reference import RemainingReference


POSTMAP_STAGES = {
    "vm-protection-returned": 0x1244,
    "vm-lowglobals-before-link": 0x12c0,
    "vm-lowglobals-before-clear": 0x12c4,
    "vm-lowglobals-cleared": 0x12c8}


class PostmapReference(RemainingReference):
    def expected(self, checkpoint):
        if checkpoint not in POSTMAP_STAGES:
            return super().expected(checkpoint)
        original = super().expected("vm-all-segments-mapped")
        if checkpoint in ("vm-protection-returned", "vm-lowglobals-before-link"):
            return original
        pages = bytearray(original + bytes(4096))
        new_page = self.top + len(original)
        struct.pack_into("<Q", pages, 8192, new_page | 0x1800000000000003)
        if checkpoint == "vm-lowglobals-before-clear":
            pages[-4096:] = bytes([165]) * 4096
        return bytes(pages)

    def accepts_lowglobal_link(self, address, length, value, pc, arm_vm_init):
        if pc != arm_vm_init + 0x12c0 or length != 8 or address != self.top + 8192:
            return False
        original = super().expected("vm-all-segments-mapped")
        return value == ((self.top + len(original)) | 0x1800000000000003)
