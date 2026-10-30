"""Separate exact-binary loader profile for the full-provider native-4K kernel."""

import hashlib
import struct

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols

KERNEL_SHA256 = "9b67c800aaf870ab969fab329f0080bdb89eebc0635d199d14a693853e235187"
TABLE_WINDOW_SHA256 = "63feafc73d91ea0b111586f79295799314bf5fbb210d3022ab4bc949446fad9c"
PREFIX_SHA256 = "0d05acb5e8b2ccb91c1fd78875cec7871924b2b5c00c734d44a41963b84d987c"
MMU_WINDOW_SHA256 = "25706c0d4dcdb703187c853183c19abd45596b42c5f5f39a1c8e07257b1f1606"
PHYSICAL = 0x11200000
POOL_BYTES = 65536


def reference_tables(kernel, physical, virtual, memory_size):
    if hashlib.sha256(kernel).hexdigest() != KERNEL_SHA256:
        raise ValueError("Native-4K tables require exact reviewed kernel")
    segments = [segment for segment in inspect(kernel)["segments"] if segment["vmsize"]]
    header = min(segment["vmaddr"] for segment in segments)
    if (physical, virtual, memory_size) != (PHYSICAL, header & -2097152, 33554432):
        raise ValueError("Native-4K loader requires the bounded 32-MiB arena")
    symbols = macho_symbols(kernel)
    tables = physical + symbols["_bootstrap_pagetables"] - virtual
    header_pa = physical + header - virtual
    blocks = (memory_size - (header_pa - physical)) >> 21
    expected = bytearray(POOL_BYTES)
    for root_offset, table_offset, cursor in ((0, 8192, header_pa), (4096, 12288, header)):
        first_slot = (cursor >> 21) & 511
        if not 0 < blocks <= 512 - first_slot:
            raise ValueError("Bounded profile unexpectedly requires another L2 page")
        struct.pack_into("<Q", expected, root_offset + ((cursor >> 30) & 255) * 8, (tables + table_offset) | 3)
        for index in range(blocks):
            struct.pack_into("<Q", expected, table_offset + (first_slot + index) * 8,
                             ((header_pa & -2097152) + index * 2097152) | 0x601)
    return bytes(expected)


def review(kernel, native_tables=False, native_mmu=False):
    if hashlib.sha256(kernel).hexdigest() != KERNEL_SHA256:
        raise ValueError("Native-4K profile requires exact reviewed kernel")
    if native_mmu and not native_tables:
        raise ValueError("Native MMU requires native tables review")
    inspection = inspect(kernel)
    symbols = macho_symbols(kernel)
    segments = [segment for segment in inspection["segments"] if segment["vmsize"]]
    virtual = min(segment["vmaddr"] for segment in segments) & -2097152

    def read(address, size):
        matches = [segment for segment in segments
                   if segment["vmaddr"] <= address and address + size <= segment["vmaddr"] + segment["filesize"]]
        if len(matches) != 1:
            raise ValueError("Ambiguous native-4K instruction backing")
        segment = matches[0]
        offset = segment["fileoff"] + address - segment["vmaddr"]
        return kernel[offset:offset + size]

    cold = symbols["_start_first_cpu"]
    common = symbols["common_start"]
    prefix_end = symbols["_mido_checkpoint_args_loaded"] + 48
    if (hashlib.sha256(read(cold, prefix_end - cold)).hexdigest() != PREFIX_SHA256
            or hashlib.sha256(read(cold, common - cold)).hexdigest() != TABLE_WINDOW_SHA256
            or hashlib.sha256(read(common, 256)).hexdigest() != MMU_WINDOW_SHA256
            or read(inspection["entry_va"], 4) != struct.pack("<I", 0x14000000 | (((cold - inspection["entry_va"]) // 4) & 0x3ffffff))):
        raise ValueError("Native-4K reviewed startup instruction windows differ")
    boundary = symbols["_arm_init"] if native_mmu else common if native_tables else prefix_end
    values = dict(MIDO_EARLY_ENTRY_PA=PHYSICAL + inspection["entry_va"] - virtual,
                  MIDO_EARLY_STOP_PA=PHYSICAL + boundary - virtual,
                  MIDO_EARLY_TABLES_PA=PHYSICAL + symbols["_bootstrap_pagetables"] - virtual,
                  MIDO_EARLY_VIRT_BASE=virtual)
    header = "".join(f"#define {name} 0x{value:x}ULL\n" for name, value in values.items())
    report = dict(scope="Exact native-4K pre-MMU prefix only", kernel_sha256=KERNEL_SHA256,
                  entry_va=inspection["entry_va"], cold_start_va=cold, stop_va=boundary,
                  original_stop_word=struct.unpack("<I", read(boundary, 4))[0], values=values,
                  reviewed_prefix_sha256=TABLE_WINDOW_SHA256 if native_tables else PREFIX_SHA256,
                  profile="full-provider-native-4k", boot_approved=False, platform_memory_approved=False,
                  stops_before=["Original arm_init C body", "Unmasking interrupts", "Storage or userland"])
    if native_tables:
        expected = reference_tables(kernel, PHYSICAL, virtual, 33554432)
        header += "#define MIDO_NATIVE_TABLES 1\n#define MIDO_NATIVE_TABLE_WORDS 8192\n#define MIDO_NATIVE_REFERENCE_WORDS 2048\n"
        header += f"#define MIDO_NATIVE_STOP_WORD 0x{report['original_stop_word']:x}U\n"
        header += f"#define MIDO_NATIVE_STACK_VA 0x{symbols['_intstack_top']:x}ULL\n"
        if any(expected[16384:]):
            raise ValueError("Bounded native-4K reference has unexpected extra L2 allocations")
        header += "#define MIDO_NATIVE_REFERENCE {" + ",".join(f"0x{word:x}ULL" for word in struct.unpack("<2048Q", expected[:16384])) + "}\n"
        report.update(scope="Native-4K tables only; stop before MMU setup", native_tables=True,
                      bootstrap_pool_bytes=POOL_BYTES, expected_table_sha256=hashlib.sha256(expected).hexdigest(),
                      native_stack_va=symbols["_intstack_top"])
    if native_mmu:
        vector_site = common + 0x9c
        vectors = symbols["_LowExceptionVectorBase"]
        if (read(vector_site, 4) != struct.pack("<I", 0x90ffffe0)
                or any(read(vectors + slot * 128, 4) != struct.pack("<I", 0x14000000) for slot in range(16))):
            raise ValueError("Native-4K halt-vector patch differs")
        definitions = dict(MIDO_NATIVE_MMU=1, MIDO_MMU_SCTLR=0x34d4593d,
                           MIDO_MMU_TRAMPOLINE_PA=0x12400000, MIDO_MMU_ARGS_VA=virtual + 0x1000000,
                           MIDO_MMU_VECTOR_VA=vectors, MIDO_MMU_VECTOR_PATCH_PA=PHYSICAL + vector_site - virtual,
                           MIDO_MMU_TCR=148798842138, MIDO_MMU_MAIR=866947665630020863)
        header += "".join(f"#define {name} 0x{value:x}ULL\n" for name, value in definitions.items())
        report.update(native_mmu=True, scope="Native-4K MMU startup to bounded arm_init observer",
                      native_sctlr_expected=0x34d4593d, trampoline_pa=0x12400000,
                      trampoline_va=virtual + 0x1200000, requires_initial_sctlr=0xc00800,
                      original_mmu_window_sha256=MMU_WINDOW_SHA256,
                      halt_vector_patch=dict(physical_address=definitions["MIDO_MMU_VECTOR_PATCH_PA"],
                                             original_word=0x90ffffe0, replacement_word=0xf0ffffe0,
                                             native_vbar_va=vectors, halt_slots_verified=16))
    return header, report
