"""Tests for the mido XNU shim pipeline (stdlib unittest + Unicorn).

  python -I -m unittest discover -s mido/tests -v        (from the repo root)

Nothing here touches a device. Set MIDO_SIM_PNG=<dir> to also render the
simulated framebuffer of the successful boot to <dir>/shim-sim.png.
"""
import os, struct, sys, tempfile, unittest, zlib
from pathlib import Path

import fixtures as F
import adt, mkadt_mido, mkpayload, pack_mido_boot

SHIM_DIR = Path(F.ROOT) / 'mido' / 'shim'
PHYS_BASE, MEM_SIZE = 0x20000000, 0x4000000		# small arena for the simulator
SHIM_AT, DTB_AT, RD_AT, FB = 0x10080000, 0x13400000, 0x13600000, 0x90001000
DRAM_SIZE = MEM_SIZE - 0x100000		# the ADT carves the 1 MiB panic log off the top
MARKER = PHYS_BASE + 0x100000
VIRT_BASE = F.TEXT_VA & ~0x1fffff
ENTRY_PA = PHYS_BASE + (F.TEXT_VA + 0x800 - VIRT_BASE)

_tmp = tempfile.TemporaryDirectory()
SHIM = None


def setUpModule():
    global SHIM
    sys.path.insert(0, str(SHIM_DIR))
    import build
    if not Path(F.NDK).exists():
        raise unittest.SkipTest('NDK not installed')
    SHIM = build.build(Path(_tmp.name) / 'shim', Path(F.NDK)).read_bytes()


def tearDownModule():
    _tmp.cleanup()


def make_payload(phys_base=PHYS_BASE, mem_size=MEM_SIZE, with_fixups=True, tag='k'):
    d = Path(_tmp.name)
    blob, entry = F.make_macho(MARKER, with_fixups=with_fixups)
    (d / f'{tag}.macho').write_bytes(blob)
    tree = adt.serialize(mkadt_mido.build(seed=bytes(64), phys_base=phys_base, mem_size=mem_size,
                                          product_path=None))
    (d / f'{tag}.adt').write_bytes(tree)
    payload, info = mkpayload.build(str(d / f'{tag}.macho'), str(d / f'{tag}.adt'), 'debug=0x14e serial=3')
    return payload, info, tree, blob, entry


u32 = lambda v: struct.unpack('<%dI' % (len(v) // 4), v)
u64s = lambda v: struct.unpack('<%dQ' % (len(v) // 8), v)


class AdtTests(unittest.TestCase):
    def setUp(self):
        self.blob = adt.serialize(mkadt_mido.build(seed=bytes(range(64)), product_path=None, sdhc=True))
        self.root, end = adt.parse(self.blob)
        self.assertEqual(end, len(self.blob))
        self.kid = {c.name: c for c in self.root.children}

    def test_roundtrip_and_root(self):
        self.assertEqual(adt.serialize(self.root), self.blob)
        self.assertEqual(self.root.prop('compatible'),
                         b'D21AP\0iPhone10,2\0xiaomi,mido\0qcom,msm8953\0AppleARM\0')
        self.assertEqual(self.root.prop('model'), b'iPhone10,2\0')
        self.assertEqual(self.root.prop('target-type'), b'D21\0')
        self.assertEqual(self.root.prop('target-sub-type'), b'D21AP\0')

    def test_cpus(self):
        cpus = self.kid['cpus'].children
        self.assertEqual(len(cpus), 8)
        self.assertEqual([u32(c.prop('reg'))[0] for c in cpus], [0, 1, 2, 3, 0x100, 0x101, 0x102, 0x103])
        for c in cpus:
            self.assertEqual(c.prop('compatible').split(b'\0')[0], b'arm,cortex-a53')
            self.assertEqual(u32(c.prop('timebase-frequency'))[0], 19200000)
        self.assertEqual(u32(cpus[5].prop('cluster-id'))[0], 1)
        self.assertEqual(u32(cpus[5].prop('cluster-core-id'))[0], 1)

    def test_gic_fb_display(self):
        io = {c.name: c for c in self.kid['arm-io'].children}
        self.assertEqual(u64s(io['gic'].prop('reg')), (0x0b000000 - 0x01000000, 0x1000, 0x0b002000 - 0x01000000, 0x1000))
        self.assertEqual(u32(io['gic'].prop('virtual-timer-intid'))[0], 20)
        fb = self.kid['mido-fbcon']
        self.assertEqual(u64s(fb.prop('reg')), (0x90001000, 0x5EEC00))
        self.assertEqual([u32(fb.prop(k))[0] for k in ('width', 'height', 'stride', 'depth')], [1080, 1920, 3240, 24])
        d = io['disp0']
        self.assertEqual((u32(d.prop('canvas-width'))[0], u32(d.prop('canvas-height'))[0]), (1242, 2208))
        self.assertEqual(u32(self.kid['buttons'].prop('home-button-type'))[0], 0)
        self.assertEqual(u32(io['wdt'].prop('no-pmu'))[0], 1)
        self.assertNotIn('sweet-ufs', self.kid)
        self.assertEqual(u64s(self.kid['mido-sdhc'].prop('reg')), (0x07824900, 0x500))

    def test_no_sdhc_by_default(self):
        root = mkadt_mido.build(seed=bytes(64), product_path=None)
        self.assertNotIn('mido-sdhc', [c.name for c in root.children])

    def test_chosen(self):
        ch = self.kid['chosen']
        for k in ('random-seed', 'boot-manifest-hash', 'crypto-hash-method', 'display-scale', 'unique-chip-id',
                  'chip-id', 'certificate-production-status', 'effective-production-status-ap',
                  'certificate-security-mode', 'effective-security-mode-sep'):
            self.assertIsNotNone(ch.prop(k), k)
        self.assertEqual(u32(ch.prop('display-scale'))[0], 3)
        self.assertEqual(u32(ch.prop('chip-id'))[0], 0x8015)
        self.assertEqual(u64s(ch.prop('unique-chip-id'))[0] >> 32, int.from_bytes(b'MIDO', 'big'))
        base, size = u64s(ch.prop('dram-base'))[0], u64s(ch.prop('dram-size'))[0]
        self.assertEqual((base, size), (0x20000000, 0x40000000 - 0x100000))
        self.assertEqual(u64s(self.kid['pram'].prop('reg')), (base + size, 0x100000))
        self.assertEqual(u32(ch.prop('embedded-panic-log-size'))[0], 0x100000)
        kids = {c.name: c for c in ch.children}
        self.assertEqual(u64s(kids['asmb'].prop('lp-sip0'))[0], 0x6f)
        self.assertEqual(u32(self.kid['defaults'].prop('no-effaceable-storage'))[0], 1)

    def test_args_validated(self):
        with self.assertRaises(AssertionError):
            mkadt_mido.build(phys_base=0x20001000, product_path=None)

    @unittest.skipUnless((Path(F.ROOT) / 'research/ipsw/d21ap.adt').exists(), 'D21AP ADT not extracted')
    def test_product_from_d21ap(self):
        root, _ = adt.parse(adt.serialize(mkadt_mido.build(seed=bytes(64))))
        prod = next(c for c in root.children if c.name == 'product')
        self.assertEqual(prod.prop('product-name'), b'iPhone 8 Plus\0')
        self.assertIsNone(prod.prop('cover-glass'))	# syscfg placeholder dropped


class Im4pTests(unittest.TestCase):
    @unittest.skipUnless((Path(F.ROOT) / 'research/ipsw/DeviceTree.d21ap.im4p').exists(), 'IM4P not extracted')
    def test_lzfse_im4p_to_adt(self):
        raw = adt.load(str(Path(F.ROOT) / 'research/ipsw/DeviceTree.d21ap.im4p'))
        root, end = adt.parse(raw)
        self.assertEqual(end, len(raw))
        self.assertEqual(root.prop('compatible').split(b'\0')[0], b'D21AP')

    def test_lzfse_raw_block_and_garbage(self):
        import lzfse
        self.assertEqual(lzfse.decode(b'bvx-' + struct.pack('<I', 3) + b'abc' + b'bvx$'), b'abc')
        for bad in (b'', b'bvx2', b'bvx2' + bytes(40), b'zzzz'):
            with self.assertRaises(ValueError):
                lzfse.decode(bad)


class PayloadTests(unittest.TestCase):
    def test_header(self):
        payload, info, tree, macho, entry = make_payload()
        self.assertEqual(payload[:8], b'SWEETXNU')
        self.assertEqual(struct.unpack_from('<II', payload, 8), (1, 2))
        virt_base, entry_va, adt_off, adt_size, kend, pb, ms = struct.unpack_from('<7Q', payload, 0x10)
        self.assertEqual(virt_base, VIRT_BASE)
        self.assertEqual(entry_va, entry)
        self.assertEqual((pb, ms), (PHYS_BASE, DRAM_SIZE))
        self.assertEqual(kend, F.TEXT_VA + 0x3000)		# end of __DATA, 4K aligned
        self.assertEqual(payload[adt_off:adt_off + adt_size], tree)
        self.assertEqual(info['fixups'], 2)
        seg1 = struct.unpack_from('<4Q', payload, 0x2a8 + 32)
        data = payload[seg1[2]:seg1[2] + seg1[3]]	# chained rebases became plain pointers
        self.assertEqual(struct.unpack_from('<QQ', data, 0x10), (F.TEXT_VA + 0x800, F.TEXT_VA + 0x900))
        pack_mido_boot.validate_payload(payload)

    def test_ramdisk_rounds_to_4k(self):
        d = Path(_tmp.name)
        make_payload(tag='r')
        (d / 'r.img').write_bytes(b'x' * 5000)
        payload, info = mkpayload.build(str(d / 'r.macho'), str(d / 'r.adt'), '', str(d / 'r.img'))
        kend = struct.unpack_from('<Q', payload, 0x30)[0]
        self.assertEqual(kend, F.TEXT_VA + 0x3000 + 0x2000)

    def test_unaligned_dram_rejected(self):
        d = Path(_tmp.name)
        make_payload(tag='u')
        root, _ = adt.parse((d / 'u.adt').read_bytes())
        ch = next(c for c in root.children if c.name == 'chosen')
        ch.props = [(k, f, struct.pack('<Q', PHYS_BASE + 0x1000) if k == 'dram-base' else v) for k, f, v in ch.props]
        (d / 'u.adt').write_bytes(adt.serialize(root))
        with self.assertRaises(AssertionError):
            mkpayload.build(str(d / 'u.macho'), str(d / 'u.adt'), '')


class PackTests(unittest.TestCase):
    def test_image(self):
        payload = make_payload()[0]
        img = pack_mido_boot.make_image(SHIM, pack_mido_boot.make_tree(), payload)
        hdr, parts = pack_mido_boot.parse_boot(img)
        self.assertEqual(parts['ramdisk'], payload)
        self.assertEqual(parts['kernel'][:len(SHIM)], SHIM)
        self.assertEqual((hdr['kernel_address'], hdr['ramdisk_address'], hdr['tags_address'], hdr['page_size']),
                         ('0x10080000', '0x13600000', '0x13400000', 2048))
        # exact validated 64-byte header layout of mido/m1
        self.assertEqual(struct.unpack_from('<I', SHIM, 0)[0], 0x14000010)
        self.assertEqual(struct.unpack_from('<QQQ', SHIM, 8), (0x80000, len(SHIM), 0))
        self.assertEqual(struct.unpack_from('<I', SHIM, 44)[0], len(SHIM))
        self.assertEqual(SHIM[56:60], b'ARM\x64')

    def test_rejects_bad_inputs(self):
        payload = make_payload()[0]
        with self.assertRaises(ValueError):
            pack_mido_boot.make_image(SHIM[:-16], pack_mido_boot.make_tree(), payload)
        with self.assertRaises(ValueError):
            pack_mido_boot.make_image(SHIM, pack_mido_boot.make_tree(), b'NOTAPAYLOAD' * 100)


# ---- Unicorn simulation ----
def png(raw, w=1080, h=1920, stride=3240):
    rows = b''.join(b'\x00' + b''.join(raw[y * stride + x * 3:y * stride + x * 3 + 3][::-1] for x in range(w))
                    for y in range(h))
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows, 6)) + chunk(b'IEND', b''))


def simulate(payload, dtb, stop, count=400_000_000):
    """Run the shim at EL1 with x0 = DTB. Returns (uc, reached) where reached = pc hit `stop`."""
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_INTR, UcError
    from unicorn.arm64_const import UC_ARM64_REG_PSTATE, UC_ARM64_REG_X0, UC_ARM64_REG_PC
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    uc.mem_map(0x10000000, 0x04000000)
    uc.mem_map(PHYS_BASE, MEM_SIZE)
    uc.mem_map(FB, (3240 * 1920 + 0xfff) & ~0xfff)
    uc.mem_write(SHIM_AT, SHIM)
    uc.mem_write(DTB_AT, dtb)
    uc.mem_write(RD_AT, payload)
    uc.reg_write(UC_ARM64_REG_PSTATE, 0x3C0 | (1 << 2) | 1)
    uc.cpr_write(3, 0, 1, 0, 0, 0)		# SCTLR_EL1: MMU/caches off
    uc.reg_write(UC_ARM64_REG_X0, DTB_AT)
    uc.hook_add(UC_HOOK_INTR, lambda u, n, d: u.reg_write(UC_ARM64_REG_PC, u.reg_read(UC_ARM64_REG_PC) + 4))
    try:
        uc.emu_start(SHIM_AT, stop, count=count)
    except UcError as e:
        raise AssertionError(f'unicorn: {e} pc={uc.reg_read(UC_ARM64_REG_PC):#x}')
    return uc, uc.reg_read(UC_ARM64_REG_PC) == stop


def q(uc, a):
    return struct.unpack('<Q', bytes(uc.mem_read(a, 8)))[0]


def boot(payload, dtb):
    return simulate(payload, dtb, ENTRY_PA + 4 * F.ENTRY_STOP_INDEX)


class SimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import unicorn  # noqa: F401
        except ImportError:
            raise unittest.SkipTest('unicorn not available')

    def check_success(self, uc, payload, tree):
        text_pa = PHYS_BASE + (F.TEXT_VA - VIRT_BASE)
        seg0 = struct.unpack_from('<4Q', payload, 0x2a8)
        seg1 = struct.unpack_from('<4Q', payload, 0x2a8 + 32)
        self.assertEqual(bytes(uc.mem_read(text_pa, 0x1000)), payload[seg0[2]:seg0[2] + 0x1000])
        self.assertEqual(bytes(uc.mem_read(text_pa + 0x1000, 0x1000)), payload[seg1[2]:seg1[2] + 0x1000])
        self.assertEqual(bytes(uc.mem_read(text_pa + 0x2000, 0x1000)), bytes(0x1000))	# vmsize > filesize zeroed
        kend_pa = text_pa + 0x3000
        adt_size = struct.unpack_from('<Q', payload, 0x28)[0]
        self.assertEqual(bytes(uc.mem_read(kend_pa, adt_size)), tree)
        ba_pa = q(uc, MARKER)		# the synthetic kernel stored its x0
        self.assertEqual(ba_pa, (kend_pa + adt_size + 0xfff) & ~0xfff)
        self.assertEqual(struct.unpack('<I', bytes(uc.mem_read(MARKER + 8, 4)))[0], 0x4d49004f)
        ba = bytes(uc.mem_read(ba_pa, 736))
        self.assertEqual(struct.unpack_from('<HH', ba, 0), (2, 2))
        self.assertEqual(struct.unpack_from('<4Q', ba, 8), (VIRT_BASE, PHYS_BASE, DRAM_SIZE, ba_pa + 0x1000))
        self.assertEqual(struct.unpack_from('<6Q', ba, 40), (FB, 1, 3240, 1080, 1920, 24))
        self.assertEqual(struct.unpack_from('<Q', ba, 96)[0], kend_pa - PHYS_BASE + VIRT_BASE)	# deviceTreeP: a VA
        self.assertEqual(struct.unpack_from('<I', ba, 104)[0], adt_size)
        self.assertEqual(ba[108:108 + 22], b'debug=0x14e serial=3\0\0'[:22])
        self.assertEqual(struct.unpack_from('<Q', ba, 728)[0], DRAM_SIZE)	# memSizeActual

    def test_boot_with_initrd_props(self):
        payload, info, tree, macho, entry = make_payload()
        uc, reached = boot(payload, F.fixture_dtb(initrd=(RD_AT, RD_AT + len(payload))))
        self.assertTrue(reached, 'did not reach the kernel entry')
        self.check_success(uc, payload, tree)
        px = bytes(uc.mem_read(FB + 3240 * 1000 + 3 * 500, 3))
        self.assertEqual(px, bytes([40, 24, 8]))		# console background, byte order B,G,R
        out = os.environ.get('MIDO_SIM_PNG')
        if out:
            Path(out, 'shim-sim.png').write_bytes(png(bytes(uc.mem_read(FB, 3240 * 1920))))

    def test_boot_with_64bit_initrd_props(self):
        payload, info, tree, macho, entry = make_payload()
        uc, reached = boot(payload, F.fixture_dtb(initrd=(RD_AT, RD_AT + len(payload)), initrd_len=8))
        self.assertTrue(reached)
        self.check_success(uc, payload, tree)

    def test_boot_with_fixed_address_fallback(self):
        payload, info, tree, macho, entry = make_payload()
        uc, reached = boot(payload, F.fixture_dtb(initrd=None))
        self.assertTrue(reached, 'fallback to 0x13600000 failed')
        self.check_success(uc, payload, tree)

    def test_refuses_bad_payloads(self):
        payload = make_payload()[0]
        cases = {}

        def mutate(name, off, fmt, value):
            bad = bytearray(payload)
            struct.pack_into(fmt, bad, off, value)
            cases[name] = bytes(bad)
        mutate('magic', 0, '<B', payload[0] ^ 1)
        mutate('phys_base unaligned', 0x38, '<Q', PHYS_BASE + 0x1000)
        mutate('entry outside image', 0x18, '<Q', F.TEXT_VA + 0x10000)
        mutate('file_off beyond payload', 0x2a8 + 16, '<Q', 0xfffffff0)
        mutate('nsegs', 0x0c, '<I', 99)
        mutate('arena outside free RAM', 0x38, '<Q', 0x80000000)
        dtb = F.fixture_dtb(initrd=(RD_AT, RD_AT + len(payload)))
        for name, p in cases.items():
            with self.subTest(name):
                uc, reached = simulate(p, dtb, stop=0x10000004, count=80_000_000)
                self.assertFalse(reached)
                self.assertEqual(bytes(uc.mem_read(MARKER, 16)), bytes(16), 'kernel entry ran')
                self.assertEqual(bytes(uc.mem_read(PHYS_BASE, 64)), bytes(64), 'segments were copied')

    def test_dtb_without_valid_framebuffer_draws_nothing(self):
        payload = make_payload()[0]
        dtb = F.fixture_dtb(initrd=(RD_AT, RD_AT + len(payload)), marker='something,else')
        uc, reached = simulate(payload, dtb, stop=0x10000004, count=2_000_000)
        self.assertFalse(reached)
        self.assertEqual(bytes(uc.mem_read(FB, 64)), bytes(64))
        self.assertEqual(bytes(uc.mem_read(MARKER, 16)), bytes(16))


if __name__ == '__main__':
    unittest.main()
