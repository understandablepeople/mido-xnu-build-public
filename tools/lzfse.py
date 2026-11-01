#!/usr/bin/env python3
"""Minimal pure-python LZFSE decoder (bvx$, bvx-, bvx2 blocks), stdlib only.

Written for tools/adt.py so an IM4P-wrapped DeviceTree can be unpacked without
the `lzfse` CLI. LZFSE v1 ('bvx1') and LZVN ('bvxn') blocks are not supported
and raise ValueError. All sizes are bounds-checked: the input is untrusted.
"""
import struct

MAX_OUT = 64 * 1024 * 1024

L_BITS = [0] * 16 + [2, 3, 5, 8]
M_BITS = [0] * 16 + [3, 5, 8, 11]
D_BITS = [b for b in range(16) for _ in range(4)]
FREQ_NBITS = [2, 3, 2, 5, 2, 3, 2, 8, 2, 3, 2, 5, 2, 3, 2, 14] * 2
FREQ_VALUE = [0, 2, 1, 4, 0, 3, 1, -1, 0, 2, 1, 5, 0, 3, 1, -1,
              0, 2, 1, 6, 0, 3, 1, -1, 0, 2, 1, 7, 0, 3, 1, -1]


def _bases(bits):
    out, v = [], 0
    for b in bits:
        out.append(v)
        v += 1 << b
    return out


L_BASE, M_BASE, D_BASE = _bases(L_BITS), _bases(M_BITS), _bases(D_BITS)


def _table(nstates, freq, vbits=None, vbase=None):
    """FSE decoder table; entries (symbol, k, delta) or value entries (total_bits, value_bits, delta, vbase)."""
    t = []
    total = 0
    for sym, f in enumerate(freq):
        if not f:
            continue
        total += f
        if total > nstates:
            raise ValueError('lzfse: bad frequency table')
        k = (nstates.bit_length() - 1) - (f.bit_length() - 1)	# clz(f) - clz(nstates)
        j0 = ((2 * nstates) >> k) - f
        for j in range(f):
            if j < j0:
                kk, delta = k, ((f + j) << k) - nstates
            else:
                kk, delta = k - 1, (j - j0) << (k - 1)
            if vbits is None:
                t.append((sym, kk, delta))
            else:
                t.append((kk + vbits[sym], vbits[sym], delta, vbase[sym]))
    return t


class _Bits:
    """Backward bit stream: valid bits are the top bits of the little-endian payload."""
    def __init__(self, data, n):
        self.v = int.from_bytes(data, 'little')
        self.pos = 8 * len(data) + n		# n in -7..0
        if self.pos < 0:
            raise ValueError('lzfse: stream too short')

    def pull(self, k):
        self.pos -= k
        if self.pos < 0:
            raise ValueError('lzfse: stream underrun')
        return (self.v >> self.pos) & ((1 << k) - 1)


def _freqs(buf, off, end):
    freq = []
    acc = nacc = 0
    for _ in range(20 + 20 + 64 + 256):
        while nacc + 8 <= 32 and off < end:
            acc |= buf[off] << nacc
            nacc += 8
            off += 1
        idx = acc & 31
        nbits, value = FREQ_NBITS[idx], FREQ_VALUE[idx]
        if value < 0:
            value = 8 + ((acc >> 4) & 0xf) if nbits == 8 else 24 + ((acc >> 4) & 0x3ff)
        if nbits > nacc:
            raise ValueError('lzfse: truncated frequency table')
        acc >>= nbits
        nacc -= nbits
        freq.append(value)
    return freq[:20], freq[20:40], freq[40:104], freq[104:]


def _block_v2(buf, off, out, limit):
    if off + 32 > len(buf):
        raise ValueError('lzfse: truncated block header')
    n_raw, v0, v1, v2 = struct.unpack_from('<IQQQ', buf, off + 4)
    f = lambda v, lo, n: (v >> lo) & ((1 << n) - 1)
    n_lit, n_lit_bytes, n_match = f(v0, 0, 20), f(v0, 20, 20), f(v0, 40, 20)
    lit_bits = f(v0, 60, 3) - 7
    lit_state = [f(v1, 0, 10), f(v1, 10, 10), f(v1, 20, 10), f(v1, 30, 10)]
    n_lmd_bytes, lmd_bits = f(v1, 40, 20), f(v1, 60, 3) - 7
    hdr = f(v2, 0, 32)
    l_state, m_state, d_state = f(v2, 32, 10), f(v2, 42, 10), f(v2, 52, 10)
    if hdr < 32 or off + hdr + n_lit_bytes + n_lmd_bytes > len(buf):
        raise ValueError('lzfse: truncated block')
    if len(out) + n_raw > limit or n_lit % 4:
        raise ValueError('lzfse: bad block size')
    lf, mf, df, litf = _freqs(buf, off + 32, off + hdr)
    lt = _table(64, lf, L_BITS, L_BASE)
    mt = _table(64, mf, M_BITS, M_BASE)
    dt = _table(256, df, D_BITS, D_BASE)
    litt = _table(1024, litf)
    try:
        bs = _Bits(buf[off + hdr:off + hdr + n_lit_bytes], lit_bits)
        lits = bytearray()
        for _ in range(n_lit // 4):
            for i in range(4):
                sym, k, delta = litt[lit_state[i]]
                lit_state[i] = delta + bs.pull(k)
                lits.append(sym)
        bs = _Bits(buf[off + hdr + n_lit_bytes:off + hdr + n_lit_bytes + n_lmd_bytes], lmd_bits)
        base = len(out)
        li = 0
        D = 0

        def val(state, table):
            tb, vb, delta, vbase = table[state]
            x = bs.pull(tb)
            return delta + (x >> vb), vbase + (x & ((1 << vb) - 1))

        for _ in range(n_match):
            l_state, L = val(l_state, lt)
            m_state, M = val(m_state, mt)
            d_state, nd = val(d_state, dt)
            if nd:
                D = nd
            if li + L > len(lits):
                raise ValueError('lzfse: literal overrun')
            out += lits[li:li + L]
            li += L
            if D == 0 or D > len(out) or len(out) + M - base > n_raw:
                raise ValueError('lzfse: bad match')
            for _ in range(M):
                out.append(out[-D])
    except IndexError:
        raise ValueError('lzfse: corrupt state')
    if len(out) - base != n_raw:
        raise ValueError('lzfse: block size mismatch')
    return off + hdr + n_lit_bytes + n_lmd_bytes


def decode(buf, limit=MAX_OUT):
    out = bytearray()
    off = 0
    while True:
        if off + 4 > len(buf):
            raise ValueError('lzfse: truncated stream')
        magic = bytes(buf[off:off + 4])
        if magic == b'bvx$':
            return bytes(out)
        if magic == b'bvx-':
            if off + 8 > len(buf):
                raise ValueError('lzfse: truncated raw block')
            n, = struct.unpack_from('<I', buf, off + 4)
            if off + 8 + n > len(buf) or len(out) + n > limit:
                raise ValueError('lzfse: bad raw block')
            out += buf[off + 8:off + 8 + n]
            off += 8 + n
        elif magic == b'bvx2':
            off = _block_v2(buf, off, out, limit)
        else:
            raise ValueError(f'lzfse: unsupported block {magic!r}')
