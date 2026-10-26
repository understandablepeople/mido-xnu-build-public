"""Read-only evidence from native EL1 upper-address translation tables."""

import struct


def walk_upper(read_physical, tcr, ttbr1, address):
    granule = {2: 12, 1: 14}.get((tcr >> 30) & 3)
    bits = 64 - ((tcr >> 16) & 63)
    if granule is None or not 25 <= bits <= 48 or address >> 63 != 1:
        raise ValueError("unsupported upper-address translation geometry")
    result = {"address": address, "tcr": tcr, "ttbr1": ttbr1,
              "page_shift": granule, "address_bits": bits, "levels": []}
    if tcr & (1 << 23):
        return dict(result, status="walk-disabled")
    index_bits = granule - 3
    levels = (bits - granule + index_bits - 1) // index_bits
    first = 4 - levels
    root_bits = bits - granule - (levels - 1) * index_bits
    physical_mask = (1 << 48) - 1
    table = ttbr1 & physical_mask & ~((1 << max(3, root_bits + 3)) - 1)
    for level in range(first, 4):
        shift = granule + (3 - level) * index_bits
        mask = (1 << (root_bits if level == first else index_bits)) - 1
        location = table + ((address >> shift) & mask) * 8
        descriptor = struct.unpack("<Q", read_physical(location, 8))[0]
        result["levels"].append({"level": level, "location": location, "descriptor": descriptor})
        kind = descriptor & 3
        if kind in (0, 2):
            return dict(result, status="invalid-descriptor", fault_level=level)
        if level == 3 or kind == 1:
            if (level == 3 and kind != 3) or level == 0:
                return dict(result, status="reserved-descriptor", fault_level=level)
            physical = (descriptor & physical_mask & ~((1 << shift) - 1)) | (address & ((1 << shift) - 1))
            return dict(result, status="mapped", physical=physical,
                        access_flag=bool(descriptor & (1 << 10)),
                        access_permissions=(descriptor >> 6) & 3,
                        attribute_index=(descriptor >> 2) & 7)
        table = descriptor & physical_mask & ~((1 << granule) - 1)
    raise ValueError("unresolved translation geometry")


def enter_store_translation_abort(cpu, read_physical, instruction):
    from unicorn import arm64_const as registers

    state = cpu.reg_read(registers.UC_ARM64_REG_PSTATE)
    origin = cpu.reg_read(registers.UC_ARM64_REG_PC)
    vector = cpu.reg_read(registers.UC_ARM64_REG_VBAR_EL1)
    stack = cpu.reg_read(registers.UC_ARM64_REG_SP_EL1)
    if (state & 15 != 4 or not stack or vector & 0x7ff or not vector or
            instruction & 0xffc00000 != 0xb9000000 or not cpu.cpr_read(3, 0, 1, 0, 0) & 1):
        raise ValueError("unsupported synchronous exception; expected EL1t STR W translation fault")
    base = (instruction >> 5) & 31
    if base == 31:
        address = cpu.reg_read(registers.UC_ARM64_REG_SP)
    else:
        address = cpu.reg_read(getattr(registers, f"UC_ARM64_REG_X{base}"))
    address = (address + ((instruction >> 10) & 4095) * 4) & ((1 << 64) - 1)
    if address & 3:
        raise ValueError("unaligned store is outside the modeled translation-fault contract")
    walk = walk_upper(read_physical, cpu.cpr_read(3, 0, 2, 0, 2),
                      cpu.cpr_read(3, 0, 2, 0, 1), address)
    if walk["status"] != "invalid-descriptor":
        raise ValueError("synchronous exception is not a proven native translation fault")
    syndrome = ((0x25 << 26) | (1 << 25) | (1 << 24) | (2 << 22) |
                ((instruction & 31) << 16) | (1 << 6) | (4 + walk["fault_level"]))
    interrupted_stack = cpu.reg_read(registers.UC_ARM64_REG_SP)
    cpu.cpr_write(3, 0, 4, 0, 0, state)
    cpu.reg_write(registers.UC_ARM64_REG_ELR_EL1, origin)
    cpu.reg_write(registers.UC_ARM64_REG_ESR_EL1, syndrome)
    cpu.reg_write(registers.UC_ARM64_REG_FAR_EL1, address)
    cpu.reg_write(registers.UC_ARM64_REG_SP_EL0, interrupted_stack)
    cpu.reg_write(registers.UC_ARM64_REG_PSTATE, (state & ~0x30001f) | 0x3c5)
    cpu.reg_write(registers.UC_ARM64_REG_SP, stack)
    cpu.reg_write(registers.UC_ARM64_REG_PC, vector)
    return {"interrupted_pc": origin, "interrupted_pstate": state, "vector_entry": vector,
            "far": address, "esr": syndrome, "instruction": instruction, "translation": walk,
            "scope": "modeled architectural data abort; native handler must resolve and retry store"}
