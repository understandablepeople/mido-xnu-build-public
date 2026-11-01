"""Shared helpers for the mido shim tests (stdlib only)."""
import os, struct, sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
TOOLS = os.path.join(ROOT, 'tools')
for p in (TOOLS, os.path.join(ROOT, 'mido', 'shim')):
    if p not in sys.path:
        sys.path.insert(0, p)
sys.path.insert(0, r'C:\Users\frant\Desktop\ios\artifacts\python-deps')   # Unicorn (available here only)

NDK = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Android', 'Sdk', 'ndk', '28.2.13676358')

LC_SEGMENT_64, LC_UNIXTHREAD, LC_DYLD_CHAINED_FIXUPS = 0x19, 0x5, 0x80000034
TEXT_VA = 0xfffffff007004000


def a32(code):
    return struct.pack('<%dI' % len(code), *code)


def movz(rd, imm, lsl=0):
    return 0xd2800000 | (lsl // 16) << 21 | imm << 5 | rd


def movk(rd, imm, lsl=0):
    return 0xf2800000 | (lsl // 16) << 21 | imm << 5 | rd


def str_x(rt, rn, off=0):
    return 0xf9000000 | (off // 8) << 10 | rn << 5 | rt


WFE = 0xd503205f
B_SELF = 0x14000000


def entry_code(marker_pa):
    """x0 (boot_args PA) -> [marker], 0x4D49444F ('MIDO') -> [marker+8], then wfe loop.
    Runs with the MMU off, so marker_pa is physical."""
    return [movz(1, marker_pa >> 16 & 0xffff, 16), movk(1, marker_pa & 0xffff, 0),
            str_x(0, 1, 0), movz(2, 0x4f, 0), movk(2, 0x4d49, 16),   # 0x4d49004f
            str_x(2, 1, 8),
            WFE,       # index 7: the emulator stops here
            B_SELF]


ENTRY_STOP_INDEX = 6


def make_macho(marker_pa, text_va=TEXT_VA, with_fixups=True):
    """Tiny arm64 kernel-like Mach-O: __TEXT (header + code), __DATA with two chained
    rebases (DYLD_CHAINED_PTR_64_OFFSET) and LC_UNIXTHREAD. Returns (bytes, entry_va)."""
    code = a32(entry_code(marker_pa))
    code_off = 0x800
    entry_va = text_va + code_off
    data_va = text_va + 0x1000
    fix_off = 0x2000

    def seg(name, vmaddr, vmsize, fileoff, filesize):
        return struct.pack('<II16sQQQQiiII', LC_SEGMENT_64, 72, name, vmaddr, vmsize, fileoff, filesize, 5, 5, 0, 0)

    cmds = [seg(b'__TEXT', text_va, 0x1000, 0, 0x1000), seg(b'__DATA', data_va, 0x2000, 0x1000, 0x1000)]
    regs = [0] * 33
    regs[32] = entry_va		# pc
    cmds.append(struct.pack('<IIII', LC_UNIXTHREAD, 16 + 68 * 4, 6, 68) + struct.pack('<33Q', *regs) + bytes(8))
    fix = b''
    if with_fixups:
        starts_in_image = struct.pack('<III', 2, 0, 12)		# seg 0 (__TEXT): none; seg 1 at +12
        starts_in_segment = struct.pack('<IHHQIH', 24, 0x1000, 6, 0x1000, 0, 1) + struct.pack('<H', 0x10)
        hdr = struct.pack('<7I', 0, 28, 0, 0, 0, 1, 0)
        fix = hdr + starts_in_image + starts_in_segment
        fix += bytes(-len(fix) & 7)
        cmds.append(struct.pack('<IIII', LC_DYLD_CHAINED_FIXUPS, 16, fix_off, len(fix)))
    header = struct.pack('<8I', 0xfeedfacf, 0x0100000c, 0, 2, len(cmds), sum(len(c) for c in cmds), 0, 0)
    blob = bytearray(fix_off + len(fix))
    blob[:32] = header
    off = 32
    for c in cmds:
        blob[off:off + len(c)] = c
        off += len(c)
    assert off <= code_off
    blob[code_off:code_off + len(code)] = code
    if with_fixups:
        blob[fix_off:fix_off + len(fix)] = fix
        # first DATA page: pointer at +0x10 (target offset 0x800, next = 2 strides of 4 bytes), +0x18 last (0x900)
        struct.pack_into('<Q', blob, 0x1010, 0x800 | (2 << 51))
        struct.pack_into('<Q', blob, 0x1018, 0x900)
    return bytes(blob), entry_va


# ---- DTB fixtures ----
def _fdt(nodes_fn):
    strings, structure, names = bytearray(), bytearray(), {}
    cell = lambda n: struct.pack('>I', n)

    def pad():
        structure.extend(bytes(-len(structure) % 4))

    class W:
        def begin(self, name):
            structure.extend(cell(1) + name.encode() + b'\0')
            pad()

        def end(self):
            structure.extend(cell(2))

        def prop(self, name, value):
            if name not in names:
                names[name] = len(strings)
                strings.extend(name.encode() + b'\0')
            structure.extend(struct.pack('>III', 3, len(value), names[name]) + value)
            pad()
    nodes_fn(W(), cell)
    structure.extend(cell(9))
    so = 56 + len(structure)
    total = so + len(strings)
    hdr = struct.pack('>10I', 0xD00DFEED, total, 56, so, 40, 17, 16, 0, len(strings), len(structure))
    return hdr + bytes(16) + structure + strings


def fixture_dtb(initrd=None, marker='mido,xnu-shim', initrd_len=4):
    """lk2nd-like DTB: marker root, /chosen with simple-framebuffer, reserved-memory
    cont-splash 0x90001000, and (optionally) linux,initrd-start/-end."""
    def nodes(w, cell):
        w.begin('')
        w.prop('compatible', marker.encode() + b'\0')
        w.begin('chosen')
        if initrd:
            w.prop('linux,initrd-start', cell(initrd[0]) if initrd_len == 4 else struct.pack('>Q', initrd[0]))
            w.prop('linux,initrd-end', cell(initrd[1]) if initrd_len == 4 else struct.pack('>Q', initrd[1]))
        w.begin('framebuffer@90001000')
        w.prop('compatible', b'simple-framebuffer\0')
        w.prop('width', cell(1080))
        w.prop('height', cell(1920))
        w.prop('stride', cell(3240))
        w.prop('memory-region', cell(1))
        w.prop('format', b'r8g8b8\0')
        w.prop('status', b'okay\0')
        w.end()
        w.end()
        w.begin('reserved-memory')
        w.begin('cont-splash@90001000')
        w.prop('phandle', cell(1))
        w.prop('reg', struct.pack('>QQ', 0x90001000, 3240 * 1920))
        w.end()
        w.end()
        w.end()
    return _fdt(nodes)
