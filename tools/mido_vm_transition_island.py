"""Locate original executable padding only; never patch or authorize execution."""

import hashlib
import struct

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols
from tools.mido_native4k_profile import KERNEL_SHA256, PHYSICAL


SEGMENT_RECORDS_SHA256 = "ec2fba9764ab0803158c89b0d533ceb5724e9b4bad3c2a3f9748d63484df80a4"
MINIMUM_BYTES = 128
PAGE_BYTES = 4096


def _select_padding(start, end):
    """Prefer the last 256 bytes; otherwise the first page boundary with 128."""
    if end - start >= 0x100 and (end - 0x100) % 4 == 0:
        return end - 0x100, 0x100
    aligned = (start + PAGE_BYTES - 1) & -PAGE_BYTES
    if aligned + MINIMUM_BYTES <= end:
        return aligned, MINIMUM_BYTES
    return None


def _b26_reachable(source, target):
    delta = target - source
    return source % 4 == 0 and target % 4 == 0 and -(1 << 27) <= delta < (1 << 27)


def transition_island(kernel):
    """Return an immutable-image planning report in the pinned loader model.

    PA uses the native-4K profile's physical arena and 2-MiB-aligned VA base.
    Executability means original Mach-O initprot only, not a page-table walk
    or proof of reachability under a runtime TTBR1. No code is emitted.
    """
    if hashlib.sha256(kernel).hexdigest() != KERNEL_SHA256:
        raise ValueError("Transition island requires exact reviewed native-4K kernel")
    inspection = inspect(kernel)
    symbols = macho_symbols(kernel)
    if symbols.get("_arm_vm_init") != 0xfffffff007445650:
        raise ValueError("Reviewed arm_vm_init symbol differs")
    sections = []
    segment_records = bytearray()
    symbol_values = set(symbols.values())
    cursor = 32
    for _ in inspection["commands"]:
        kind, length = struct.unpack_from("<II", kernel, cursor)
        if kind == 0x19:
            segment_records.extend(kernel[cursor:cursor + length])
            name, address, size, offset, file_size, _, _, count, _ = struct.unpack_from(
                "<16s4Q4I", kernel, cursor + 8)
            for index in range(count):
                record = cursor + 72 + index * 80
                section, owner, va, span, fileoff, _, _, _, flags, _, _, _ = struct.unpack_from(
                    "<16s16sQQ8I", kernel, record)
                if owner != name or not address <= va <= va + span <= address + size:
                    raise ValueError("Section outside owning segment")
                file_backed = flags & 0xff not in (1, 0xc, 0x12)
                if span and file_backed and (fileoff != offset + va - address
                                            or fileoff + span > offset + file_size):
                    raise ValueError("Section file backing differs")
                sections.append(dict(name=section.split(b"\0", 1)[0].decode("ascii"),
                                     segment=name.split(b"\0", 1)[0].decode("ascii"),
                                     va=va, end=va + span, fileoff=fileoff,
                                     size=span, file_backed=file_backed, record_offset=record))
        elif kind == 2:
            table, count, _, _ = struct.unpack_from("<4I", kernel, cursor + 8)
            symbol_values.update(struct.unpack_from("<Q", kernel, table + index * 16 + 8)[0]
                                 for index in range(count))
        cursor += length
    if hashlib.sha256(segment_records).hexdigest() != SEGMENT_RECORDS_SHA256:
        raise ValueError("Reviewed segment/section records differ")
    matches = [segment for segment in inspection["segments"] if segment["name"] == "__TEXT_EXEC"]
    if len(matches) != 1 or matches[0]["initprot"] != 5:
        raise ValueError("Expected original read/execute __TEXT_EXEC mapping")
    segment = matches[0]
    owned = [section for section in sections if section["segment"] == "__TEXT_EXEC"]
    if not owned:
        raise ValueError("Missing executable sections")
    final_end = max(section["end"] for section in owned)
    end = segment["vmaddr"] + segment["filesize"]
    padding_offset = segment["fileoff"] + final_end - segment["vmaddr"]
    if final_end > end or not 0 <= padding_offset <= segment["fileoff"] + segment["filesize"] <= len(kernel):
        raise ValueError("Trailing padding is not file-backed")
    if any(kernel[padding_offset:segment["fileoff"] + segment["filesize"]]):
        raise ValueError("Reviewed trailing padding is not all zero")
    source = symbols["_arm_vm_init"] + 0x13e8
    virtual_base = min(item["vmaddr"] for item in inspection["segments"] if item["vmsize"]) & -2097152
    report = dict(kernel_sha256=KERNEL_SHA256, offline_only=True, boot_approved=False,
                  executable_mapping="original Mach-O __TEXT_EXEC initprot=5; runtime tables unverified",
                  physical_base=PHYSICAL, virtual_base=virtual_base, branch_source_va=source,
                  final_section_end_va=final_end, segment_end_va=end,
                  padding_fileoff=padding_offset, padding_bytes=end - final_end,
                  sections=sections, found=False, candidate=None)
    selected = _select_padding(final_end, end)
    if selected is None:
        return dict(report, reason="No trailing zero-padding candidate supports 128 bytes")
    va, budget = selected
    fileoff = segment["fileoff"] + va - segment["vmaddr"]
    if (va % 4 or fileoff % 4 or budget < MINIMUM_BYTES
            or not segment["vmaddr"] <= va < va + budget <= end
            or not 0 <= fileoff < fileoff + budget <= len(kernel)):
        raise ValueError("Invalid island bounds or alignment")
    if any(section["size"] and (va < section["end"] and section["va"] < va + budget
           or section["file_backed"] and fileoff < section["fileoff"] + section["size"]
           and section["fileoff"] < fileoff + budget) for section in sections):
        raise ValueError("Island overlaps a Mach-O section")
    if any(va <= value < va + budget for value in symbol_values):
        return dict(report, reason="Symbol in proposed island")
    if not _b26_reachable(source, va):
        return dict(report, reason="Island is not B26 reachable")
    original = kernel[fileoff:fileoff + budget]
    if any(original):
        raise ValueError("Island bytes are not all zero")
    return dict(report, found=True, candidate=dict(
        va=va, pa=PHYSICAL + va - virtual_base, fileoff=fileoff, budget=budget,
        original_bytes=original.hex(), original_sha256=hashlib.sha256(original).hexdigest(),
        end_va=va + budget, branch_delta=va - source, b26_reachable=True))
