"""Read-only modeled TTBR dependencies; never runtime or boot approval."""

import hashlib

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols
from tools.mido_native4k_profile import reference_tables
from tools.mido_vm_activation_audit import PHYSICAL, TOP, VIRTUAL, walk
from tools.mido_vm_activation_plan import activation_plan
from tools.mido_vm_geometry import l2_count
from tools.mido_vm_physmap_complete_reference import CompletePhysmapReference


ISLAND = 0xfffffff007b4ff00
STACK = 0xfffffff007c9bff0
VBAR = 0xfffffff00722c000
OBSERVER = 0xfffffff008200000
RECORD = 0x12400900
GEOMETRIES = (("count1-slide0", 1, 0),
              ("count2-maxslide", 2, 0x3ffff000),
              ("count1-boundary37000000", 1, 0x37000000))


def _span(snapshot, address, length, physical, writable, executable, top=TOP):
    """Check every covered page and both endpoints with exact permissions."""
    if (not isinstance(length, int) or length <= 0
            or not 0 <= address < address + length <= 1 << 64
            or not 0 <= physical < physical + length <= 1 << 40):
        raise ValueError("Dependency span exceeds address bounds")
    addresses = sorted({address, address + length - 1,
                        *range((address + 4096) & -4096, address + length, 4096)})
    samples = []
    for current in addresses:
        result = walk(snapshot, current, top=top)
        if (not result["mapped"] or not result.get("access_flag", False)
                or result["physical"] != physical + current - address
                or result["writable"] != writable or result["executable"] != executable
                or result["user_accessible"]):
            raise ValueError(f"Dependency mapping/permissions differ at {current:#x}")
        samples.append(dict(address=current, translation=result))
    return dict(address=address, end=address + length, bytes=length,
                physical=physical, writable=writable, executable=executable,
                passed=True, samples=samples)


def _final(snapshot, execution):
    if len(snapshot) < 8192 or len(snapshot) % 4096:
        raise ValueError("Incomplete final snapshot bounds")
    if any(snapshot[:4096]):
        raise ValueError("Final TTBR0 page must contain 512 zero descriptors")
    low = walk(snapshot, RECORD)
    if low["mapped"] or low["reason"] != "unmapped":
        raise ValueError("Low identity record must be unmapped")
    cases = {}
    for name, address, size, writable, executable in (
            ("original-execution", execution, 4, False, True),
            ("island", ISLAND, 256, False, True),
            ("stack", STACK, 16, True, False),
            ("vbar", VBAR, 2048, False, True),
            ("native-observer", OBSERVER, 4, True, False)):
        cases[name] = _span(snapshot, address, size, PHYSICAL + address - VIRTUAL,
                            writable, executable)
    return dict(ttbr0_zero_descriptors=512, low_record=low, cases=cases,
                snapshot_pages=len(snapshot) // 4096,
                snapshot_sha256=hashlib.sha256(snapshot).hexdigest())


def audit(kernel):
    """Verify pinned kernel and three geometries; raise on any mismatch."""
    plan = activation_plan(kernel)
    execution = plan["stages"]["vm-after-activation-sync"]
    segments = inspect(kernel)["segments"]
    symbols = macho_symbols(kernel)
    bootstrap = reference_tables(kernel, PHYSICAL, VIRTUAL, 0x2000000)
    bootstrap_top = PHYSICAL + symbols["_bootstrap_pagetables"] - VIRTUAL
    restored = dict(
        low_record=_span(bootstrap, RECORD, 8, RECORD, True, True, bootstrap_top),
        native_observer=_span(bootstrap, OBSERVER, 4, 0x12400000,
                              True, True, bootstrap_top))
    cases = {}
    for name, count, slide in GEOMETRIES:
        physmap = VIRTUAL + TOP - PHYSICAL + slide
        if l2_count(VIRTUAL, PHYSICAL, TOP, physmap,
                    physmap + 0x3000000, 0x2000000) != count:
            raise ValueError("Dependency geometry count differs")
        reference = CompletePhysmapReference(segments, VIRTUAL, PHYSICAL, TOP, count)
        reference.physmap = physmap
        reference.end_kernel = VIRTUAL + 0xf6c000
        snapshot = reference.expected("vm-physmap-before-ttbr")
        cases[name] = dict(l2_count=count, slide=slide, passed=True,
                          final=_final(snapshot, execution))
    return dict(kernel_sha256=plan["kernel_sha256"], offline_only=True,
                model_only=True, boot_approved=False, runtime_verified=False,
                tables_modified=False, device_commands_executed=False,
                passed=True, checkpoint=execution, activation=plan, cases=cases,
                bootstrap=dict(top=bootstrap_top, cases=restored,
                               snapshot_sha256=hashlib.sha256(bootstrap).hexdigest()),
                native_observer_runnable_with_final_ttbr1=False,
                dependencies=["Low identity record requires restored bootstrap TTBR0",
                              "Native observer execution requires restored bootstrap TTBR1"],
                scope="Pre-setter model reused after verified setters and caller TLBI; "
                      "no runtime installation, restoration sequence, or boot authorization")
