"""Statically scan a MIDO kernel Mach-O for AArch64 instructions a Cortex-A53 (ARMv8.0) lacks.

Looks at __TEXT_EXEC words only. Jump tables and literal pools can produce a few false
positives; hundreds of hits mean the compiler targeted a newer architecture. Usage:
    python -I tools/scan_unsupported_a53.py KERNEL.macho [--symbols nm.txt]
"""
import bisect
import collections
import struct
import sys


def segments(buf):
    n = struct.unpack_from('<I', buf, 16)[0]
    off = 32
    for _ in range(n):
        cmd, size = struct.unpack_from('<II', buf, off)
        if cmd == 0x19:
            name = buf[off + 8:off + 24].split(b'\0')[0].decode()
            vmaddr, vmsize, foff, fsize = struct.unpack_from('<QQQQ', buf, off + 24)
            yield name, vmaddr, foff, fsize
        off += size


CLASSES = [
    ('LSE ldadd/ldclr/ldset/...', 0x3f208c00, 0x38200000),
    ('LSE swp', 0x3f20fc00, 0x38208000),
    ('LSE cas', 0x3fa07c00, 0x08a07c00),
    ('LSE casp', 0xbfa07c00, 0x08207c00),
    ('LDAPR (RCpc)', 0x3fe0fc00, 0x38a0c000),
    ('PAC/BTI hint space pacia*', 0xfffffd1f, 0xd503211f),
]


def main():
    path = sys.argv[1]
    buf = open(path, 'rb').read()
    syms = []
    if '--symbols' in sys.argv:
        for line in open(sys.argv[sys.argv.index('--symbols') + 1], errors='replace'):
            p = line.split()
            if len(p) >= 3:
                try:
                    syms.append((int(p[0], 16), p[2]))
                except ValueError:
                    pass
        syms.sort()
    keys = [s[0] for s in syms]
    hits = collections.Counter()
    funcs = collections.Counter()
    for name, vmaddr, foff, fsize in segments(buf):
        if name != '__TEXT_EXEC':
            continue
        for i in range(0, fsize, 4):
            w = struct.unpack_from('<I', buf, foff + i)[0]
            for label, mask, val in CLASSES[:5]:
                if (w & mask) == val:
                    hits[label] += 1
                    if syms:
                        j = bisect.bisect_right(keys, vmaddr + i) - 1
                        funcs[syms[j][1]] += 1
    for label, count in hits.items():
        print(f'{count:6d}  {label}')
    print('total', sum(hits.values()))
    for name, count in funcs.most_common(15):
        print(f'   {count:4d} {name}')


main()
