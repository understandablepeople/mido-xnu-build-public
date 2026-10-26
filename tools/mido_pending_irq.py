"""Eligibility for one explicitly requested offline timer-vector diagnostic."""


def pending_timer_irq(model, counter, pstate):
    return bool(
        pstate & 0xf == 4 and not pstate & 0x80
        and model.timer_control & 3 == 1 and counter >= model.timer_compare
        and model.active_token is None
        and model.registers[1, 0x0c] == 1023
        and model.registers[0, 0] & 1 and model.registers[1, 0] & 1
        and model.registers[0, 0x80] & (1 << 20)
        and model.registers[0, 0x100] & (1 << 20)
        and (model.registers[0, 0x414] & 0xff) < model.registers[1, 4])


def pending_self_sgi(model, pstate):
    return bool(model.self_sgi and model.self_sgi_pending
        and pstate & 0xf == 4 and not pstate & 0x80
        and model.active_token is None and model.registers[1, 0x0c] == 1023
        and model.registers[0, 0] & 1 and model.registers[1, 0] & 1
        and model.registers[0, 0x80] & 1 and model.registers[0, 0x100] & 1
        and (model.registers[0, 0x400] & 0xff) < model.registers[1, 4])


def enter_timer_irq(cpu, model, counter=None):
    from unicorn import arm64_const as registers

    state = cpu.reg_read(registers.UC_ARM64_REG_PSTATE)
    if counter is None:
        counter = cpu.cpr_read(3, 3, 14, 0, 2)
    vector = cpu.reg_read(registers.UC_ARM64_REG_VBAR_EL1)
    stack = cpu.reg_read(registers.UC_ARM64_REG_SP_EL1)
    if not pending_timer_irq(model, counter, state) or vector & 0x7ff or not stack:
        raise ValueError("ineligible synthetic timer exception")
    return enter_irq(cpu, model, state, vector, stack, counter, 20)


def enter_self_sgi(cpu, model, counter):
    from unicorn import arm64_const as registers

    state = cpu.reg_read(registers.UC_ARM64_REG_PSTATE)
    vector = cpu.reg_read(registers.UC_ARM64_REG_VBAR_EL1)
    stack = cpu.reg_read(registers.UC_ARM64_REG_SP_EL1)
    if not pending_self_sgi(model, state) or vector & 0x7ff or not stack:
        raise ValueError("ineligible synthetic self-SGI exception")
    delivery = enter_irq(cpu, model, state, vector, stack, counter, 0)
    model.self_sgi_pending = False
    return delivery


def enter_irq(cpu, model, state, vector, stack, counter, interrupt_id):
    from unicorn import arm64_const as registers

    origin = cpu.reg_read(registers.UC_ARM64_REG_PC)
    interrupted_stack = cpu.reg_read(registers.UC_ARM64_REG_SP)
    model.registers[1, 0x0c] = interrupt_id
    cpu.cpr_write(3, 0, 4, 0, 0, state)
    cpu.reg_write(registers.UC_ARM64_REG_ELR_EL1, origin)
    cpu.reg_write(registers.UC_ARM64_REG_SP_EL0, interrupted_stack)
    cpu.reg_write(registers.UC_ARM64_REG_PSTATE, (state & ~0x30001f) | 0x3c5)
    cpu.reg_write(registers.UC_ARM64_REG_SP, stack)
    cpu.reg_write(registers.UC_ARM64_REG_PC, vector + 0x80)
    return dict(interrupted_pc=origin, interrupted_pstate=state, vector_entry=vector + 0x80,
                counter=counter, compare=model.timer_compare, interrupt_id=interrupt_id,
                scope="synthetic EL1-SP0 IRQ exception; no forced return or thread context")
