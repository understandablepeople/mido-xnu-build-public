"""Synthetic vector delivery and separate handler diagnostics, never handset IRQ proof."""


def vector_diagnose(cpu, symbols, model, write_policy):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn import arm64_const as registers

    general = [getattr(registers, f"UC_ARM64_REG_X{index}") for index in range(31)]
    original = {register: cpu.reg_read(register) for register in general}
    pc = cpu.reg_read(registers.UC_ARM64_REG_PC)
    state = cpu.reg_read(registers.UC_ARM64_REG_PSTATE)
    stack = cpu.reg_read(registers.UC_ARM64_REG_SP)
    exception_stack = cpu.reg_read(registers.UC_ARM64_REG_SP_EL1)
    vector_base = cpu.reg_read(registers.UC_ARM64_REG_VBAR_EL1)
    if state & 15 != 4 or state & 0x80 or vector_base & 0x7ff or not exception_stack:
        raise ValueError("synthetic IRQ requires original unmasked EL1t and initialized VBAR/SP_EL1")
    outcome = dict(scope="one synthetic pending PPI 20 delivered through original EL1-SP0 IRQ vector",
                   vector_base=vector_base, vector_entry=vector_base + 0x80,
                   interrupted_pc=pc, interrupted_pstate=state,
                   returned=False, panic_observed=False, hardware_irq_delivery_proven=False)
    start = len(model.events)
    hooks = []

    def observe(engine, address, size, function):
        model.events.append(dict(operation="code", function=function))
        if function == "_panic":
            outcome["panic_observed"] = True
            engine.emu_stop()

    def returned(engine, address, size, context):
        outcome["returned"] = True
        engine.emu_stop()

    names = ("_sleh_irq", "_mido_irq_handler", "_rtclock_intr", "_timer_intr", "_entropy_collect", "_ml_set_decrementer", "_mido_irq_set_decrementer", "_panic")
    try:
        for function in names:
            if function not in symbols:
                raise ValueError("missing original IRQ path symbol: " + function)
            hooks.append(cpu.hook_add(UC_HOOK_CODE, observe, function,
                begin=symbols[function], end=symbols[function]))
        hooks.append(cpu.hook_add(UC_HOOK_CODE, returned, begin=pc, end=pc))
        hooks.append(cpu.hook_add(UC_HOOK_MEM_WRITE, write_policy))
        model.registers[1, 0x0c] = 20
        cpu.cpr_write(3, 0, 4, 0, 0, state)
        cpu.reg_write(registers.UC_ARM64_REG_ELR_EL1, pc)
        cpu.reg_write(registers.UC_ARM64_REG_SP_EL0, stack)
        cpu.reg_write(registers.UC_ARM64_REG_PSTATE, (state & ~0x30001f) | 0x3c5)
        cpu.reg_write(registers.UC_ARM64_REG_SP, exception_stack)
        cpu.emu_start(vector_base + 0x80, 0, timeout=5000000, count=1000000)
    except Exception as error:
        outcome["execution_error"] = str(error)
    finally:
        for hook in hooks:
            cpu.hook_del(hook)
    events = model.events[start:]
    calls = [event["function"] for event in events if event["operation"] == "code"]
    outcome["events"] = events
    outcome["final_pc"] = cpu.reg_read(registers.UC_ARM64_REG_PC)
    outcome["registers_restored"] = all(cpu.reg_read(register) == value for register, value in original.items())
    outcome["stack_restored"] = cpu.reg_read(registers.UC_ARM64_REG_SP) == stack
    outcome["pstate_restored"] = cpu.reg_read(registers.UC_ARM64_REG_PSTATE) == state
    completions = [event for event in events if event["operation"] == "write" and
                   event["region"] == 1 and event["offset"] == 0x10]
    ordered = False
    if all(function in calls for function in names[:5]) and len(completions) == 1:
        positions = [next(index for index, event in enumerate(events) if event.get("function") == function)
                     for function in names[:4]]
        ordered = positions == sorted(positions) and positions[-1] < events.index(completions[0])
    outcome["timer_control_after_service"] = model.timer_control
    compare_writes = [index for index, event in enumerate(events)
                      if event["operation"] == "timer-write" and event["register"] == 0]
    rearmed = bool(compare_writes)
    outcome["compare_writes_before_eoi"] = (sum(index < events.index(completions[0]) for index in compare_writes)
                                            if len(completions) == 1 else 0)
    if rearmed:
        ordered = ordered and outcome["compare_writes_before_eoi"] > 0
    outcome["passed"] = (outcome["returned"] and not outcome["panic_observed"] and
        "execution_error" not in outcome and outcome["registers_restored"] and
        outcome["stack_restored"] and outcome["pstate_restored"] and ordered and
        completions[0]["value"] == 20 and model.active_token is None and
        outcome["timer_control_after_service"] & 3 == (1 if rearmed else 2))
    return outcome


def diagnose(cpu, symbols, model, write_policy):
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn.arm64_const import UC_ARM64_REG_PC, UC_ARM64_REG_PSTATE, UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X30

    names = ("_mido_irq_handler", "_rtclock_intr", "_timer_intr", "_ml_set_decrementer", "_mido_irq_set_decrementer", "_panic")
    if any(name not in symbols for name in names):
        raise ValueError("missing original timer or diagnostic handler symbol")
    result = dict(scope="separate calls of the installed native handler after original BSD entry; not vector delivery",
                  hardware_verified=False, irq_delivery_proven=False, cases={})
    sentinel = symbols["_bsd_init"]
    for name, token in (("spurious", 1023), ("decrementer-reenable", None), ("timer", 20), ("unknown-fail-closed", 28)):
        start = len(model.events)
        if token is not None:
            model.registers[1, 0x0c] = token
        outcome = dict(returned=False, panic_observed=False)
        hooks = []

        def observe(engine, address, size, function):
            event = dict(operation="code", function=function)
            if function in ("_ml_set_decrementer", "_mido_irq_set_decrementer"):
                event["ticks"] = engine.reg_read(UC_ARM64_REG_X0)
            model.events.append(event)
            if function == "_panic":
                outcome["panic_observed"] = True
                engine.emu_stop()

        def returned(engine, address, size, context):
            outcome["returned"] = True
            engine.emu_stop()

        try:
            for function in names[1:]:
                hooks.append(cpu.hook_add(UC_HOOK_CODE, observe, function,
                    begin=symbols[function], end=symbols[function]))
            hooks.append(cpu.hook_add(UC_HOOK_CODE, returned, begin=sentinel, end=sentinel))
            hooks.append(cpu.hook_add(UC_HOOK_MEM_WRITE, write_policy))
            cpu.reg_write(UC_ARM64_REG_PSTATE, cpu.reg_read(UC_ARM64_REG_PSTATE) | 0x3c0)
            for register in (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3):
                cpu.reg_write(register, 0)
            cpu.reg_write(UC_ARM64_REG_X30, sentinel)
            if name == "decrementer-reenable":
                cpu.reg_write(UC_ARM64_REG_X0, 1000)
            function = "_ml_set_decrementer" if name == "decrementer-reenable" else "_mido_irq_handler"
            cpu.emu_start(symbols[function], 0, timeout=5000000, count=1000000)
        finally:
            for hook in hooks:
                cpu.hook_del(hook)
        events = model.events[start:]
        calls = [event["function"] for event in events if event["operation"] == "code"]
        completions = [event for event in events if event["operation"] == "write" and
                       event["region"] == 1 and event["offset"] == 0x10]
        if name == "spurious":
            valid = outcome["returned"] and not calls and not completions and model.active_token is None
        elif name == "decrementer-reenable":
            valid = (outcome["returned"] and not outcome["panic_observed"] and not completions and
                     calls == ["_ml_set_decrementer", "_mido_irq_set_decrementer"] and
                     model.timer_control & 3 == 1 and
                     all(event.get("ticks") == 1000 for event in events if event["operation"] == "code"))
        elif name == "timer":
            valid = (outcome["returned"] and not outcome["panic_observed"] and
                     all(function in calls for function in names[1:3]) and
                     len(completions) == 1 and completions[0]["value"] == 20 and model.active_token is None)
            if valid:
                first = next(index for index, event in enumerate(events) if event.get("function") == "_rtclock_intr")
                compare_writes = [index for index, event in enumerate(events)
                                  if event["operation"] == "timer-write" and event["register"] == 0]
                rearmed = bool(compare_writes)
                valid = (first < events.index(completions[0]) and model.timer_control & 3 == (1 if rearmed else 2)
                         and (not rearmed or first < compare_writes[0] < events.index(completions[0])))
        else:
            valid = outcome["panic_observed"] and not outcome["returned"] and not completions and model.active_token == 28
        outcome.update(passed=valid, events=events, final_pc=cpu.reg_read(UC_ARM64_REG_PC))
        result["cases"][name] = outcome
        if not valid:
            break
    result["passed"] = len(result["cases"]) == 4 and all(case["passed"] for case in result["cases"].values())
    return result
