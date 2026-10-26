"""Read required symbols from isolated ARM64 ELF fixtures."""

import struct


def symbols_from_elf(blob, required):
    if blob[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", blob, 18)[0] != 183:
        raise ValueError("Expected little-endian ELF64 AArch64")
    offset = struct.unpack_from("<Q", blob, 40)[0]
    entry_size, count = struct.unpack_from("<HH", blob, 58)
    if entry_size != 64 or count > 64 or offset + count * entry_size > len(blob):
        raise ValueError("Invalid section table")
    sections = [struct.unpack_from("<IIQQQQIIQQ", blob, offset + index * entry_size) for index in range(count)]
    symbols = {}
    for section in sections:
        if section[1] != 2:
            continue
        if section[6] >= len(sections) or section[9] != 24 or section[5] % 24:
            raise ValueError("Invalid symbol table")
        names_section = sections[section[6]]
        names = blob[names_section[4]:names_section[4] + names_section[5]]
        if section[4] + section[5] > len(blob):
            raise ValueError("Truncated symbol table")
        for position in range(section[4], section[4] + section[5], 24):
            name, _, _, _, value, _ = struct.unpack_from("<IBBHQQ", blob, position)
            end = names.find(b"\0", name)
            if end < 0:
                raise ValueError("Invalid symbol name")
            symbols[names[name:end].decode("ascii")] = value
    for name in required:
        if name not in symbols:
            raise ValueError("Missing payload symbol")
    return symbols
