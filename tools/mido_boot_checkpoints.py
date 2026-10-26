"""Read-only direct-call evidence for native ARM64 boot checkpoints."""

import struct


def bl_target(address, instruction):
    if instruction & 0xfc000000 != 0x94000000:
        return None
    immediate = instruction & 0x03ffffff
    if immediate & 0x02000000:
        immediate -= 1 << 26
    return (address + immediate * 4) & ((1 << 64) - 1)


def call_sites(kernel, inspection, symbols, caller, target):
    if caller not in symbols or target not in symbols:
        raise ValueError("missing native checkpoint caller or target")
    start = symbols[caller]
    following = [address for address in symbols.values() if address > start]
    if not following:
        raise ValueError("unbounded checkpoint caller")
    end = min(following)
    segments = [segment for segment in inspection["segments"]
                if segment["initprot"] & 4 and segment["vmaddr"] <= start < end <=
                segment["vmaddr"] + segment["filesize"]]
    if len(segments) != 1 or start & 3 or end & 3:
        raise ValueError("checkpoint caller is not bounded executable ARM64 code")
    segment = segments[0]
    offset = segment["fileoff"] + start - segment["vmaddr"]
    if offset < 0 or offset + end - start > len(kernel):
        raise ValueError("truncated checkpoint caller")
    return [address for address in range(start, end, 4)
            if bl_target(address, struct.unpack_from("<I", kernel, offset + address - start)[0]) == symbols[target]]
