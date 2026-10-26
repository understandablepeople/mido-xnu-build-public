"""Host-only Mach-O structural inspection; never authorizes a device boot."""

import argparse
import hashlib
import json
from pathlib import Path
import struct


ADDRESS_LIMIT = 1 << 64


def checked_end(start, size, limit, label):
    if start < 0 or size < 0 or start >= limit or size > limit - start:
        raise ValueError(f"{label}: range outside bounds")
    return start + size


def inspect(data):
    if len(data) < 32:
        raise ValueError("truncated Mach-O header")
    magic, cpu, subtype, filetype, count, command_bytes, flags, reserved = struct.unpack_from("<8I", data)
    if magic != 0xFEEDFACF:
        raise ValueError("expected a thin little-endian 64-bit Mach-O")
    if cpu != 0x0100000C or subtype & 0x00FFFFFF != 0:
        raise ValueError("expected baseline ARM64_ALL, not ARM64E or another CPU subtype")
    if filetype != 2:
        raise ValueError("expected MH_EXECUTE, not a fileset, object or dylib")
    if reserved != 0 or command_bytes % 8 or count > command_bytes // 8:
        raise ValueError("invalid load-command header")
    command_end = checked_end(32, command_bytes, len(data) + 1, "load commands")
    if command_end > len(data):
        raise ValueError("truncated load commands")
    cursor = 32
    segments = []
    entries = []
    blockers = []
    commands = []
    for command_index in range(count):
        if cursor + 8 > command_end:
            raise ValueError("missing load-command header")
        command, size = struct.unpack_from("<II", data, cursor)
        if size < 8 or size % 8 or size > command_end - cursor:
            raise ValueError("invalid load-command size")
        commands.append(f"0x{command:08x}")
        if command == 0x19:
            if size < 72:
                raise ValueError("truncated LC_SEGMENT_64")
            name_raw, address, memory_size, offset, file_size, maximum, initial, sections, segment_flags = struct.unpack_from("<16s4Q4I", data, cursor + 8)
            if size != 72 + sections * 80:
                raise ValueError("invalid segment section-table size")
            if file_size > memory_size or initial & ~maximum or maximum & ~7:
                raise ValueError("invalid segment sizes or protections")
            checked_end(address, memory_size, ADDRESS_LIMIT, "segment virtual memory")
            checked_end(offset, file_size, len(data) + 1, "segment file data")
            if offset + file_size > len(data):
                raise ValueError("truncated segment data")
            for previous in segments:
                if memory_size and previous["vmsize"] and address < previous["vmaddr"] + previous["vmsize"] and previous["vmaddr"] < address + memory_size:
                    raise ValueError("overlapping virtual segments")
                if file_size and previous["filesize"] and offset < previous["fileoff"] + previous["filesize"] and previous["fileoff"] < offset + file_size:
                    raise ValueError("overlapping file segments")
            name = name_raw.split(b"\0", 1)[0].decode("ascii", errors="strict")
            segments.append(dict(name=name, vmaddr=address, vmsize=memory_size, fileoff=offset, filesize=file_size, initprot=initial))
        elif command == 5:
            if size != 288:
                raise ValueError("expected exactly one ARM_THREAD_STATE64 in LC_UNIXTHREAD")
            flavor, words = struct.unpack_from("<II", data, cursor + 8)
            if (flavor, words) != (6, 68):
                raise ValueError("invalid ARM_THREAD_STATE64")
            entries.append(struct.unpack_from("<Q", data, cursor + 272)[0])
        elif command == 0x80000034:
            if size != 16:
                raise ValueError("invalid chained-fixups command")
            fixup_offset, fixup_size = struct.unpack_from("<II", data, cursor + 8)
            if not fixup_size or fixup_offset + fixup_size > len(data):
                raise ValueError("invalid chained-fixups payload bounds")
            blockers.append("chained fixups require a separate validated resolver")
        else:
            blockers.append(f"load command 0x{command:08x} has not been audited by this tool")
        cursor += size
    if cursor != command_end:
        raise ValueError("load-command count does not consume sizeofcmds")
    if not segments or len(entries) != 1:
        raise ValueError("expected segments and exactly one LC_UNIXTHREAD entry")
    entry = entries[0]
    if entry % 4 or not any(segment["initprot"] & 4 and segment["vmaddr"] <= entry < segment["vmaddr"] + segment["filesize"] for segment in segments):
        raise ValueError("entry must be aligned and in file-backed executable memory")
    return {
        "purpose": "structural inspection only; NOT a kernel identity or ISA audit",
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "entry_va": entry,
        "flags": flags,
        "commands": commands,
        "segments": segments,
        "blockers": list(dict.fromkeys(blockers + [
            "MIDO kernel configuration and instruction-set audit required",
            "Apple device tree and boot_args handoff not implemented",
            "physical RAM placement and reserved-memory map not approved",
            "GICv2, timer IRQ and early platform backend not implemented",
        ])),
        "boot_approved": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", type=Path)
    args = parser.parse_args()
    try:
        result = inspect(args.image.read_bytes())
    except (OSError, ValueError) as error:
        parser.exit(2, f"inspection failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
