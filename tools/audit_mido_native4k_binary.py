"""Offline table-builder audit of the exact full-provider native-4K cloud kernel."""

import argparse
import hashlib
import json
import struct
from pathlib import Path

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols

KERNEL_SHA256 = "9b67c800aaf870ab969fab329f0080bdb89eebc0635d199d14a693853e235187"
POOL_SIZE = 65536
PHYSICAL = 0x11200000
ARENA_SIZE = 0x2000000


def reference_tables(tables, header_pa, header_va, memory_size):
    expected = bytearray(POOL_SIZE)
    blocks = (memory_size - (header_pa - PHYSICAL)) >> 21
    if not 0 < blocks <= 16384:
        raise ValueError("Unsupported synthetic memory extent")
    next_page = 2
    for root, cursor in ((0, header_pa), (4096, header_va)):
        remaining = blocks
        mapped = 0
        while remaining:
            if next_page == 16:
                return bytes(expected), True
            table_offset = next_page * 4096
            next_page += 1
            root_slot = (cursor >> 30) & 255
            struct.pack_into("<Q", expected, root + root_slot * 8, (tables + table_offset) | 3)
            first_slot = (cursor >> 21) & 511
            count = min(remaining, 512 - first_slot)
            for index in range(count):
                descriptor = ((header_pa & -2097152) + (mapped + index) * 2097152) | 0x601
                struct.pack_into("<Q", expected, table_offset + (first_slot + index) * 8, descriptor)
            remaining -= count
            mapped += count
            cursor += count * 2097152
    return bytes(expected), False


def audit(kernel, memory_size=ARENA_SIZE):
    if hashlib.sha256(kernel).hexdigest() != KERNEL_SHA256:
        raise ValueError("Requires exact reviewed full-provider native-4K kernel")
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn import arm64_const as registers

    inspection = inspect(kernel)
    symbols = macho_symbols(kernel)
    segments = [segment for segment in inspection["segments"] if segment["vmsize"]]
    header = min(segment["vmaddr"] for segment in segments)
    virtual = header & -2097152
    header_pa = PHYSICAL + header - virtual
    tables = PHYSICAL + symbols["_bootstrap_pagetables"] - virtual
    start = PHYSICAL + symbols["_mido_checkpoint_args_loaded"] + 48 - virtual
    stop = PHYSICAL + symbols["common_start"] - virtual
    exhausted = stop - 12
    expected_tables, should_exhaust = reference_tables(tables, header_pa, header, memory_size)
    initial = bytearray(ARENA_SIZE)
    for segment in segments:
        offset = segment["vmaddr"] - virtual
        if not 0 <= offset <= ARENA_SIZE - segment["vmsize"]:
            raise ValueError("Segment outside bounded execution arena")
        initial[offset:offset + segment["filesize"]] = kernel[segment["fileoff"]:segment["fileoff"] + segment["filesize"]]
    table_offset = tables - PHYSICAL
    if not 0 <= table_offset <= ARENA_SIZE - POOL_SIZE:
        raise ValueError("Table pool outside execution arena")
    initial[table_offset:table_offset + POOL_SIZE] = bytes([165]) * POOL_SIZE
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.ctl_set_cpu_model(registers.UC_CPU_ARM64_A53)
    cpu.mem_map(PHYSICAL, ARENA_SIZE)
    cpu.mem_write(PHYSICAL, bytes(initial))
    cpu.reg_write(registers.UC_ARM64_REG_PSTATE, 0x3c5)
    cpu.cpr_write(3, 0, 1, 0, 0, 0xc00800)
    for name, value in (("X22", virtual), ("X23", PHYSICAL), ("X24", memory_size), ("X25", tables)):
        cpu.reg_write(getattr(registers, "UC_ARM64_REG_" + name), value)
    writes = []

    def instruction(engine, address, size, context):
        if address in (stop, exhausted):
            engine.emu_stop()
        elif size != 4 or not start <= address < stop:
            raise AssertionError("Execution escaped reviewed pre-MMU window")

    def write(engine, access, address, size, value, context):
        if not tables <= address < address + size <= tables + POOL_SIZE:
            raise AssertionError("Write outside sixteen-page pool")
        writes.append(address)

    cpu.hook_add(UC_HOOK_CODE, instruction)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write)
    cpu.emu_start(start, stop + 4, timeout=10000000, count=500000)
    expected_stop = exhausted if should_exhaust else stop
    if cpu.reg_read(registers.UC_ARM64_REG_PC) != expected_stop:
        raise AssertionError("Unexpected bootstrap stop or instruction budget exhausted")
    expected = bytearray(initial)
    expected[table_offset:table_offset + POOL_SIZE] = expected_tables
    if bytes(cpu.mem_read(PHYSICAL, ARENA_SIZE)) != expected:
        raise AssertionError("Reference tables or untouched arena bytes differ")
    if cpu.cpr_read(3, 0, 1, 0, 0) != 0xc00800:
        raise AssertionError("Table builder modified SCTLR")
    return dict(kernel_sha256=KERNEL_SHA256, synthetic_memory_size=memory_size,
                pool_bytes=POOL_SIZE, table_write_operations=len(writes),
                pool_exhaustion_stopped=should_exhaust, all_arena_bytes_verified=ARENA_SIZE,
                table_sha256=hashlib.sha256(expected_tables).hexdigest(),
                stop_pa=expected_stop, mmu_enabled=False, hardware_execution_proven=False,
                boot_approved=False, scope="Offline table builder only; not a boot image or userland test")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    kernel = args.kernel.read_bytes()
    results = [audit(kernel, extent) for extent in (ARENA_SIZE, 3 << 30, 8 << 30)]
    with args.output.open("x", encoding="utf-8") as destination:
        json.dump(results, destination, indent=2)
        destination.write("\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
