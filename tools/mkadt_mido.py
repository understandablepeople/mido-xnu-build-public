#!/usr/bin/env python3
"""Build the minimal Apple Device Tree that the MIDO xnu needs to boot.

mido = Xiaomi Redmi Note 4X (MSM8953, 8x Cortex-A53, GICv2, 4K pages). Derived
from tools/mkadt.py (sweet). Every address comes from mido/HARDWARE.md.

  mkadt_mido.py OUT.adt [--phys-base 0x20000000] [--mem-size 0x40000000]
                        [--product research/ipsw/d21ap.adt] [--no-product]
                        [--sdhc] [--seed-hex HEX] [--dump]

Identity is an iPhone 8 Plus (iPhone10,2 / D21AP, has a Home button); the
/product node is copied from the real D21AP device tree (Apple artifact, kept
out of git). Produce research/ipsw/d21ap.adt with tools/extract_d21ap.py.
"""
import argparse, hashlib, os, struct, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402

# Defaults: first XNU arena in the free low bank (HARDWARE.md: 0x10000000-0x80000000 untouched).
PHYS_BASE = 0x20000000
MEM_SIZE = 0x40000000
PANIC_LOG_SIZE = 0x100000	# carved from the top, exposed as /pram + embedded-panic-log-size
SOC_BASE = 0x01000000		# /arm-io children are relative to this; must not be 0

# GICv2 (qcom,msm-qgic2) [HW]
GICD, GICD_SIZE = 0x0b000000, 0x1000
GICC, GICC_SIZE = 0x0b002000, 0x1000
VTIMER_INTID = 20		# PPI 4 (virtual) -> 16 + 4
# Framebuffer left by lk2nd [HW]: 24bpp, byte order B,G,R
FB, FB_W, FB_H, FB_STRIDE, FB_DEPTH = 0x90001000, 1080, 1920, 3240, 24
FB_SIZE = FB_STRIDE * FB_H	# 0x5EEC00
CANVAS_W, CANVAS_H = 1242, 2208	# iPhone 8 Plus @3x (414x736 pt)
DISPLAY_SCALE = 3
# eMMC host (sdhci@7824900) [DTB]
SDHC, SDHC_SIZE = 0x07824900, 0x500
TIMEBASE = 19200000
CPU_HZ = 2016000000		# descriptive only
ECID = int.from_bytes(b'MIDO', 'big') << 32 | 1	# synthetic: 'MIDO' + 1 (not the phone's)

BOOT_MANIFEST_HASH = hashlib.sha384(b'mido boot manifest').digest()
D21AP_ADT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '../research/ipsw/d21ap.adt')

u32 = lambda *v: struct.pack('<%dI' % len(v), *v)
u64 = lambda *v: struct.pack('<%dQ' % len(v), *v)
cstr = lambda s: s.encode() + b'\0'


def d21ap_product(path=D21AP_ADT):
    """/product properties of the real D21AP tree, without syscfg placeholders
    (flag bit set) and node bookkeeping. Returns None if the file is absent.
    The camera/facetime/maps/haptics/audio child nodes are not copied (as in sweet)."""
    if not path or not os.path.exists(path):
        print(f'warning: {path} missing, no /product node', file=sys.stderr)
        return None
    with open(path, 'rb') as f:
        root, _ = adt.parse(f.read())
    for c in root.children:
        if c.prop('name') == b'product\0':
            return [(k, v) for k, f, v in c.props if not f and k not in ('name', 'AAPL,phandle')]
    raise SystemExit(f'{path}: no /product node')


def node(name, props=(), children=()):
    n = adt.Node()
    n.props = [('name', 0, cstr(name))] + [(k, 0, v) for k, v in props]
    n.children = list(children)
    return n


def build(seed=None, phys_base=PHYS_BASE, mem_size=MEM_SIZE, sdhc=False, product_path=D21AP_ADT):
    assert phys_base % 0x200000 == 0 and mem_size % 0x1000 == 0 and mem_size > 4 * PANIC_LOG_SIZE
    panic_base = phys_base + mem_size - PANIC_LOG_SIZE
    mem_size -= PANIC_LOG_SIZE
    seed = seed if seed is not None else os.urandom(64)
    phandle = iter(range(1, 1000))
    ph = lambda: ('AAPL,phandle', u32(next(phandle)))

    chosen = node('chosen', [
        ph(),
        ('dram-base', u64(phys_base)),
        ('dram-size', u64(mem_size)),
        ('random-seed', seed),
        ('debug-enabled', u32(1)),
        ('embedded-panic-log-size', u32(PANIC_LOG_SIZE)),
        ('firmware-version', cstr('mido-shim')),
        ('system-firmware-version', cstr('mido-shim')),
        # /sbin/mount -P 1 exits unless this exists. Fixed stand-in value.
        ('boot-manifest-hash', BOOT_MANIFEST_HASH),
        # libimg4 (cryptexd) aborts without it; real A11+ trees say sha2-384.
        ('crypto-hash-method', cstr('sha2-384')),
        # iPhone 8 Plus: 1242x2208 canvas @3x = 414x736 points. Scale 0 would
        # make SpringBoard's display mode invalid.
        ('display-scale', u32(DISPLAY_SCALE)),
        # IOPlatformUUID derives from these; synthetic ECID 'MIDO'+1, chip-id of the A11.
        ('unique-chip-id', struct.pack('<Q', ECID)),
        ('chip-id', u32(0x8015)),
        # Security status of a dev-fused, undemoted board (tuple 0,0,1,1).
        ('certificate-production-status', u32(0)),
        ('effective-production-status-ap', u32(0)),
        ('certificate-security-mode', u32(1)),
        ('effective-security-mode-sep', u32(1)),
    ], [node('memory-map', [ph()]),
        # Local boot policy (kern_csr.c): SIP relaxed, unsealed root.
        node('asmb', [ph(), ('lp-sip0', u64(0x6f)), ('lp-sip1', u32(1))])])

    # 8x Cortex-A53 in two clusters of four. reg = real MPIDR Aff1:Aff0 =
    # (cluster<<8)|core (HARDWARE.md: 0x000-0x003, 0x100-0x103).
    cpu_nodes = []
    for idx in range(8):
        cluster, core = idx >> 2, idx & 3
        cpu_nodes.append(node(f'cpu{idx}', [
            ph(),
            ('device_type', cstr('cpu')),
            ('compatible', cstr('arm,cortex-a53') + cstr('ARM,v8')),
            ('reg', u32((cluster << 8) | core)),
            ('cpu-id', u32(idx)),		# descriptive: XNU assigns IDs by DT order
            ('cluster-id', u32(cluster)),
            ('cluster-type', u32(0)),		# homogeneous CLUSTER_TYPE_SMP
            ('die-cluster-id', u32(0)),
            ('cluster-core-id', u32(core)),
            ('l2-cache-id', u32(cluster)),	# one L2 per cluster
            ('l3-cache-id', u32(0)),
            ('state', cstr('running' if idx == 0 else 'stopped')),
            ('timebase-frequency', u32(TIMEBASE)),
            ('clock-frequency', u32(CPU_HZ)),
            ('bus-frequency', u32(100000000)),
            ('memory-frequency', u32(933000000)),
            ('peripheral-frequency', u32(TIMEBASE)),
            ('fixed-frequency', u32(TIMEBASE)),
        ]))
    cpus = node('cpus', [ph(), ('#address-cells', u32(1)), ('#size-cells', u32(0))], cpu_nodes)

    gic = node('gic', [
        ph(),
        ('compatible', cstr('arm,gic-v2')),
        ('interrupt-controller', b''),
        ('virtual-timer-intid', u32(VTIMER_INTID)),
        # u64 pairs relative to soc_base: GICD, GICC
        ('reg', u64(GICD - SOC_BASE, GICD_SIZE, GICC - SOC_BASE, GICC_SIZE)),
    ])
    arm_io = node('arm-io', [
        ph(),
        ('device_type', cstr('mido-io')),
        ('compatible', cstr('mido-io') + cstr('arm-io')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
        ('ranges', u64(0, SOC_BASE, 0x100000000 - SOC_BASE)),
    ], [gic,
        # No PMU: watchdogd checks IODeviceTree:/arm-io/wdt for no-pmu.
        node('wdt', [ph(), ('no-pmu', u32(1))]),
        node('disp0', [
            ph(),
            ('device_type', cstr('display-subsystem')),
            ('compatible', cstr('mido,display')),
            ('canvas-width', u32(CANVAS_W)),
            ('canvas-height', u32(CANVAS_H)),
        ])])

    fbcon = node('mido-fbcon', [
        ph(),
        ('reg', u64(FB, FB_SIZE)),
        ('width', u32(FB_W)),
        ('height', u32(FB_H)),
        ('stride', u32(FB_STRIDE)),
        ('depth', u32(FB_DEPTH)),	# 24bpp, memory byte order B,G,R
    ])

    defaults = node('defaults', [ph(), ('no-effaceable-storage', u32(1))])

    # MobileGestalt HomeButtonType = /buttons home-button-type (D21AP has a Home button -> 0).
    buttons = node('buttons', [
        ph(),
        ('button-names', cstr('volup') + cstr('voldown') + cstr('hold')),
        ('home-button-type', u32(0)),
        ('opposed-power-vol-buttons', u32(1)),
    ])

    product_props = d21ap_product(product_path) if product_path else None
    product = [node('product', [ph()] + product_props)] if product_props else []

    pram = node('pram', [ph(), ('reg', u64(panic_base) + u64(PANIC_LOG_SIZE))])

    extra = []
    if sdhc:	# optional eMMC host node for the future root-device driver
        extra.append(node('mido-sdhc', [ph(), ('compatible', cstr('qcom,sdhci-msm-v4')),
                                        ('reg', u64(SDHC, SDHC_SIZE))]))

    return node('device-tree', [
        ph(),
        ('compatible', cstr('D21AP') + cstr('iPhone10,2') + cstr('xiaomi,mido') + cstr('qcom,msm8953') + cstr('AppleARM')),
        ('model', cstr('iPhone10,2')),
        ('target-type', cstr('D21')),
        ('target-sub-type', cstr('D21AP')),
        ('manufacturer', cstr('Apple Inc.')),
        ('#address-cells', u32(2)),
        ('#size-cells', u32(2)),
    ], [chosen, defaults, cpus, arm_io, fbcon, buttons, pram] + product + extra)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--phys-base', type=lambda s: int(s, 0), default=PHYS_BASE)
    ap.add_argument('--mem-size', type=lambda s: int(s, 0), default=MEM_SIZE)
    ap.add_argument('--product', default=D21AP_ADT, help='raw D21AP ADT to copy /product from')
    ap.add_argument('--no-product', action='store_true')
    ap.add_argument('--sdhc', action='store_true', help='add the optional mido-sdhc node')
    ap.add_argument('--seed-hex', help='64-byte random-seed as hex (default: os.urandom)')
    ap.add_argument('--dump', action='store_true')
    a = ap.parse_args()
    root = build(bytes.fromhex(a.seed_hex) if a.seed_hex else None, a.phys_base, a.mem_size, a.sdhc,
                 None if a.no_product else a.product)
    blob = adt.serialize(root)
    with open(a.out, 'xb') as f:
        f.write(blob)
    if a.dump:
        adt.dump(adt.parse(blob)[0])
    print(f'{a.out}: {len(blob)} bytes', file=sys.stderr)
