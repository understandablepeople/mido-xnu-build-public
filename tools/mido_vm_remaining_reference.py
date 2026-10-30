"""Independent inactive mapping model, including stack guards and empty segments."""

import struct

from tools.mido_vm_executable_reference import ExecutableReference


REMAINING_CALLS = (
    (0x4a4, "__HIB"), (0x4cc, "__BOOTDATA"),
    (0x4f0, "intstack_low_guard"), (0x514, "intstack_high_guard"),
    (0x538, "excepstack_high_guard"), (0x560, "__KLD"),
    (0x588, "__KLDDATA"), (0x5b0, "__LINKEDIT"),
    (0x5d8, "__PLK_LINKEDIT"), (0x600, "__LAST"),
    (0x62c, "__LASTDATA_CONST"), (0x654, "__PRELINK_DATA"),
    (0x680, "__PLK_LLVM_COV"), (0x6a8, "__PRELINK_INFO"))

REMAINING_STAGES = {
    "vm-hibdata-mapped": (0x4a8, "__HIB"),
    "vm-bootdata-mapped": (0x4d0, "__BOOTDATA"),
    "vm-stack-guards-mapped": (0x53c, "excepstack_high_guard"),
    "vm-kld-mapped": (0x564, "__KLD"),
    "vm-klddata-mapped": (0x58c, "__KLDDATA"),
    "vm-linkedit-mapped": (0x5b4, "__LINKEDIT"),
    "vm-lastdata-mapped": (0x630, "__LASTDATA_CONST"),
    "vm-all-segments-mapped": (0x6ac, "__PRELINK_INFO")}


class RemainingReference(ExecutableReference):
    names = ExecutableReference.names + tuple(name for _, name in REMAINING_CALLS)

    def arguments(self, name):
        if name in ExecutableReference.names:
            return super().arguments(name)
        guards = {"intstack_low_guard": 0x34000, "intstack_high_guard": 0x3c000,
                  "excepstack_high_guard": 0x44000}
        if name in guards:
            start = self.segments["__BOOTDATA"]["vmaddr"] + guards[name]
            return (start, 0x4000, 0, 1, 2, 1, 0)
        if name not in self.names:
            raise ValueError("Unreviewed remaining mapping request")
        segment = self.segments.get(name)
        if segment is None:
            if name != "__HIB":
                raise ValueError("Missing reviewed segment")
            return (0, 0, 0, 1, 0, 1, 3)
        executable = name in ("__KLD", "__LAST")
        readonly = executable or name == "__KLDDATA"
        granule = 0 if name == "__BOOTDATA" else 1 if name in ("__LAST", "__LASTDATA_CONST") else 3
        return (segment["vmaddr"], segment["vmsize"], 0,
                0 if executable else 1, 2 if readonly else 0, 0 if executable else 1, granule)

    def mappings(self, name, limit=None):
        if self.arguments(name)[1] == 0:
            return
        yield from super().mappings(name, limit)

    def expected(self, checkpoint):
        if checkpoint not in REMAINING_STAGES:
            return super().expected(checkpoint)
        _, name = REMAINING_STAGES[checkpoint]
        layout, descriptors = self.state(name)
        pages = bytearray((2 + self.l2_count + len(layout)) * 4096)
        for index in range(self.l2_count):
            struct.pack_into("<Q", pages, 4096 + (((self.virtual >> 30) & 255) + index) * 8,
                             (self.top + 8192 + index * 4096) | 0x2000000000000003)
        for address, value in descriptors.items():
            struct.pack_into("<Q", pages, address - self.top, value)
        return bytes(pages)
