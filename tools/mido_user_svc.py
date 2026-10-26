"""Deliver a proven Darwin EL0 SVC to the native kernel vector, not a syscall result."""

try:
    from tools.mido_mmu_fault import walk_lower
except ModuleNotFoundError:
    from mido_mmu_fault import walk_lower


def enter_user_svc(cpu, read_physical, instruction_pc):
    from unicorn import arm64_const as registers

    state = cpu.reg_read(registers.UC_ARM64_REG_PSTATE)
    vector = cpu.reg_read(registers.UC_ARM64_REG_VBAR_EL1)
    stack = cpu.reg_read(registers.UC_ARM64_REG_SP_EL1)
    if (state & 15 or instruction_pc & 3 or not stack or not vector or vector & 0x7ff or
            cpu.reg_read(registers.UC_ARM64_REG_PC) != instruction_pc + 4 or
            not cpu.cpr_read(3, 0, 1, 0, 0) & 1):
        raise ValueError("unsupported user SVC boundary")
    mapping = walk_lower(read_physical, cpu.cpr_read(3, 0, 2, 0, 2),
                         cpu.cpr_read(3, 0, 2, 0, 0), instruction_pc)
    if (mapping["status"] != "mapped" or not mapping["access_flag"] or
            not mapping["access_permissions"] & 1 or
            mapping["levels"][-1]["descriptor"] & (1 << 54) or
            bytes(read_physical(mapping["physical"], 4)) != bytes.fromhex("011000d4")):
        raise ValueError("user SVC differs from the mapped original Darwin syscall instruction")
    interrupted_stack = cpu.reg_read(registers.UC_ARM64_REG_SP)
    syndrome = (0x15 << 26) | (1 << 25) | 0x80
    cpu.reg_write(registers.UC_ARM64_REG_ELR_EL1, instruction_pc + 4)
    cpu.reg_write(registers.UC_ARM64_REG_ESR_EL1, syndrome)
    cpu.reg_write(registers.UC_ARM64_REG_SP_EL0, interrupted_stack)
    cpu.reg_write(registers.UC_ARM64_REG_PSTATE, (state & ~0x30001f) | 0x3c5)
    cpu.cpr_write(3, 0, 4, 0, 0, state)
    cpu.reg_write(registers.UC_ARM64_REG_SP, stack)
    cpu.reg_write(registers.UC_ARM64_REG_PC, vector + 0x400)
    return dict(instruction_pc=instruction_pc, return_pc=instruction_pc + 4, esr=syndrome,
                vector_entry=vector + 0x400, syscall_result_emulated=False)
