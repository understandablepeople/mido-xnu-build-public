"""Bounded defined-symbol extraction from an inspected ARM64 Mach-O kernel."""

import struct

try:
    from tools.inspect_xnu import inspect
except ModuleNotFoundError:
    from inspect_xnu import inspect


def macho_symbols(kernel):
    inspection = inspect(kernel)
    cursor = 32
    for _ in inspection["commands"]:
        kind, length = struct.unpack_from("<II", kernel, cursor)
        if kind == 2:
            if length != 24:
                raise ValueError("Invalid symbol-table command size")
            symbol_offset, count, string_offset, string_size = struct.unpack_from("<4I", kernel, cursor + 8)
            if count > 1000000 or symbol_offset + count * 16 > len(kernel) or string_offset + string_size > len(kernel):
                raise ValueError("Invalid symbol-table bounds")
            strings = kernel[string_offset:string_offset + string_size]
            result = {}
            for index in range(count):
                name, kind, section, _, value = struct.unpack_from("<IBBHQ", kernel, symbol_offset + index * 16)
                if not section or kind & 0xe0 or kind & 0xe != 0xe:
                    continue
                end = strings.find(b"\0", name)
                if name >= len(strings) or end < 0:
                    raise ValueError("Invalid symbol string")
                result[strings[name:end].decode("ascii")] = value
            return result
        cursor += length
    raise ValueError("Kernel has no symbol table for the early-entry check")
