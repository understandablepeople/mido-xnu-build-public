"""Observe unmodified XNU early C initialization in the existing CPU model."""

import struct


def crypto_registration_contract(events, pointer, ready):
    registrations = [entry for entry in events if entry["function"] == "_register_crypto_functions"]
    prng_registrations = [entry for entry in events if entry["function"] == "_register_and_init_prng"]
    kmem_entries = [entry for entry in events if entry["function"] == "_kmem_crypto_init"]
    valid = False
    if len(registrations) == len(prng_registrations) == len(kmem_entries) == 1:
        entry = kmem_entries[0]
        valid = (pointer != 0 and ready is True
                 and events.index(registrations[0]) < events.index(prng_registrations[0]) < events.index(entry)
                 and entry.get("crypto_functions_pointer") == pointer
                 and entry.get("kernel_prng_ready") is True
                 and registrations[0].get("table_pointer") == pointer)
    return dict(original_kmem_hook_returned=True,
                original_crypto_registrations=len(registrations), original_prng_registrations=len(prng_registrations),
                crypto_functions_pointer=pointer, kernel_prng_ready=ready, registration_contract_passed=valid,
                complete_crypto_provider=False, boot_approved=False)


def trace(cpu, symbols, inspection, fixture, stage):
    irq_diagnostic = stage == "bsd-irq"
    if irq_diagnostic:
        stage = "bsd-entry"
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_INVALID, UC_HOOK_MEM_WRITE
    from unicorn.arm64_const import UC_ARM64_REG_PC, UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_X4, UC_ARM64_REG_X8, UC_ARM64_REG_X30, UC_ARM64_REG_SP, UC_ARM64_REG_PSTATE

    physical_base, virtual_base = fixture["physical_base"], fixture["virtual_base"]
    memory_size = fixture["memory_size"]
    target = {"topology-entry": "_ml_parse_cpu_topology",
              "topology-done": "_ml_parse_cpu_topology",
              "vm-entry": "_arm_vm_init", "vm-done": "_arm_vm_init",
              "entropy-done": "_PE_get_random_seed",
              "serial-done": "_serial_init",
              "cpu-init-entry": "_PE_init_cpu",
              "machine-startup-entry": "_machine_startup",
              "kernel-bootstrap-entry": "_kernel_bootstrap",
              "vm-mem-done": "_vm_mem_bootstrap",
              "sched-done": "_sched_init",
              "clock-done": "_clock_init",
              "crypto-entry": "_kmem_crypto_init", "crypto-done": "_kmem_crypto_init",
              "interrupts-enabled": "_initialize_screen", "bsd-entry": "_bsd_init"}[stage]
    if target not in symbols:
        raise ValueError(f"Missing target symbol {target}")
    result = dict(target=target, reached=False, events=[], writes=0, fault=None,
                  write_policy="RW kernel segments, early __DATA_CONST, exact seed range and bounded synthetic allocator window")
    hooks = []
    gic_model = None
    io_mappings = []
    if "_mido_irq_timer_startup" in symbols:
        try:
            from tools.model_mido_gicv2 import MidoGicV2
        except ModuleNotFoundError:
            from model_mido_gicv2 import MidoGicV2
        gic_model = MidoGicV2()
        gic_model.map(cpu)
    header_offset = min(segment["vmaddr"] for segment in inspection["segments"] if segment["vmsize"]) - virtual_base
    allocation_end = physical_base + ((memory_size - header_offset) >> 21 << 21)
    result["synthetic_allocator_window"] = dict(start=fixture["top_of_kernel_data"], end=allocation_end)
    original_seed = bytes(cpu.mem_read(fixture["random_seed_pa"], 64)) if fixture.get("random_seed_pa") else None
    entropy_destination = None

    def topology_return(engine, address, size, context):
        result["reached"] = True
        result["topology_return_va"] = address
        if stage == "crypto-done":
            crypto_return(engine)
        if stage == "entropy-done":
            received = engine.reg_read(UC_ARM64_REG_X0)
            copied = bytes(engine.mem_read(physical(entropy_destination), 64))
            erased = not any(engine.mem_read(fixture["random_seed_pa"], 64))
            result["entropy_consumer"] = dict(returned_bytes=received, copied_exact_input=copied == original_seed,
                                               original_tree_seed_erased=erased)
            if received != 64 or copied != original_seed or not erased:
                result["fault"] = dict(kind="entropy-consumption-mismatch")
        engine.emu_stop()

    def physical(address):
        if virtual_base <= address < virtual_base + memory_size:
            return physical_base + address - virtual_base
        return address

    early_boot_subsystem = None
    if stage in ("interrupts-enabled", "bsd-entry"):
        entries = [name for name in symbols if name.startswith("___startup_EARLY_BOOT_entry_kmem_crypto_init_")]
        if len(entries) != 1:
            raise ValueError("Missing or ambiguous original kmem startup hook")
        phase, rank, function, argument = struct.unpack("<IIQQ", cpu.mem_read(physical(symbols[entries[0]]), 24))
        if not 0 < phase < 256 or rank != 0x7fffffff or function != symbols["_kmem_crypto_init"] or argument != 0:
            raise ValueError("Original kmem startup hook layout changed")
        early_boot_subsystem = phase
        result["original_kmem_startup_hook"] = dict(symbol=entries[0], subsystem=phase, rank=rank)

    def crypto_return(engine):
        pointer = struct.unpack("<Q", engine.mem_read(physical(symbols["_g_crypto_funcs"]), 8))[0]
        ready = bool(struct.unpack("<I", engine.mem_read(physical(symbols["_prng_ready"]), 4))[0])
        result["crypto_startup"] = crypto_registration_contract(result["events"], pointer, ready)
        if not result["crypto_startup"]["registration_contract_passed"]:
            result["fault"] = dict(kind="original-crypto-registration-contract-not-met")
            engine.emu_stop()

    def string(address):
        address = physical(address)
        if not physical_base <= address < physical_base + memory_size:
            return f"unmapped-pointer:{address:#x}"
        data = bytes(cpu.mem_read(address, min(512, physical_base + memory_size - address)))
        return data.split(b"\0", 1)[0].decode("utf-8", errors="replace")

    def observe(engine, address, size, name):
        nonlocal entropy_destination
        event = dict(function=name, pc=address)
        event["caller_return_va"] = engine.reg_read(UC_ARM64_REG_X30)
        if name == "_ml_io_map" and gic_model is not None:
            base = engine.reg_read(UC_ARM64_REG_X0)
            length = engine.reg_read(UC_ARM64_REG_X1)
            if base not in (0x0b000000, 0x0b002000) or length != 4096:
                result["fault"] = dict(kind="unmodeled-io-mapping", base=base, size=length)
                engine.emu_stop()
                return
            def mapped(return_engine, return_pc, return_size, context):
                io_mappings.append(dict(physical_base=base, size=length,
                    virtual_base=return_engine.reg_read(UC_ARM64_REG_X0)))
                return_engine.hook_del(mapping_hook)
                hooks.remove(mapping_hook)
            mapping_hook = cpu.hook_add(UC_HOOK_CODE, mapped,
                begin=event["caller_return_va"], end=event["caller_return_va"])
            hooks.append(mapping_hook)
        if name == "_ml_install_interrupt_handler" and gic_model is not None:
            event["handler"] = engine.reg_read(UC_ARM64_REG_X3)
            if event["handler"] != symbols.get("_mido_irq_handler"):
                result["fault"] = dict(kind="unexpected-native-irq-handler")
                engine.emu_stop()
        if name == "_register_crypto_functions":
            event["table_pointer"] = engine.reg_read(UC_ARM64_REG_X0)
        if name == "_register_and_init_prng":
            event["context_pointer"] = engine.reg_read(UC_ARM64_REG_X0)
            event["callbacks_pointer"] = engine.reg_read(UC_ARM64_REG_X1)
        if name == "_kmem_crypto_init":
            event["crypto_functions_pointer"] = struct.unpack(
                "<Q", engine.mem_read(physical(symbols["_g_crypto_funcs"]), 8))[0]
            event["kernel_prng_ready"] = bool(engine.mem_read(physical(symbols["_prng_ready"]), 1)[0])
            if stage in ("interrupts-enabled", "bsd-entry"):
                def after_crypto(return_engine, return_pc, return_size, context):
                    crypto_return(return_engine)
                    return_engine.hook_del(crypto_hook)
                    hooks.remove(crypto_hook)
                crypto_hook = cpu.hook_add(UC_HOOK_CODE, after_crypto,
                    begin=event["caller_return_va"], end=event["caller_return_va"])
                hooks.append(crypto_hook)
        if name == "_initialize_screen" and stage == "bsd-entry" and "interrupt_boundary" not in result:
            phase = struct.unpack("<I", engine.mem_read(physical(symbols["_startup_phase"]), 4))[0]
            if phase == early_boot_subsystem:
                result["interrupt_boundary"] = dict(startup_phase=phase,
                    irq_unmasked=not bool(engine.reg_read(UC_ARM64_REG_PSTATE) & 0x80),
                    irq_delivery_proven=False, device_boot_proven=False)
        if name == "_kalloc_type_apply_policy":
            count = struct.unpack("<Q", engine.mem_read(physical(symbols["_num_kt_sizeclass"]), 8))[0]
            if not 0 < count <= 256:
                raise ValueError("Unexpected kalloc sizeclass count")
            pointers = [engine.reg_read(register) for register in
                        (UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3)]
            def values(pointer):
                return list(struct.unpack(f"<{count}H", engine.mem_read(physical(pointer), count * 2)))
            policy = dict(sizeclass_count=count, budget=engine.reg_read(UC_ARM64_REG_X4) & 0xffff,
                          signature_frequencies=values(pointers[0]), type_frequencies=values(pointers[1]))
            result.setdefault("allocator_policy", []).append(policy)
            def policy_return(return_engine, return_pc, return_size, context):
                policy["signature_zones"] = values(pointers[2])
                policy["type_zones"] = values(pointers[3])
                policy["maximum_zones_including_shared"] = max(
                    sig + typ + 1 for sig, typ in zip(policy["signature_zones"], policy["type_zones"]))
                return_engine.hook_del(return_hook)
                hooks.remove(return_hook)
            return_hook = cpu.hook_add(UC_HOOK_CODE, policy_return,
                                       begin=event["caller_return_va"], end=event["caller_return_va"])
            hooks.append(return_hook)
        if name.startswith("___ubsan_handle_"):
            before = [(value, symbol) for symbol, value in symbols.items() if value <= event["caller_return_va"]]
            if before:
                value, symbol = max(before)
                event["caller_symbol"] = symbol
                event["caller_symbol_offset"] = event["caller_return_va"] - value
        if name in ("_panic", "_panic_with_options", "___assert_rtn", "__Assert"):
            event["x0_string"] = string(engine.reg_read(UC_ARM64_REG_X0))
            event["x1_raw"] = engine.reg_read(UC_ARM64_REG_X1)
            event["x2_raw"] = engine.reg_read(UC_ARM64_REG_X2)
            if event["x0_string"].startswith("%s:%d Assertion failed:"):
                stack_pa = physical(engine.reg_read(UC_ARM64_REG_SP))
                file_pointer, line, expression = struct.unpack("<QI4xQ", engine.mem_read(stack_pa, 24))
                event["assertion"] = dict(file=string(file_pointer), line=line, expression=string(expression))
            result["fault"] = event
            engine.emu_stop()
        result["events"].append(event)
        if name == target:
            if stage == "bsd-entry":
                phase = struct.unpack("<I", engine.mem_read(physical(symbols["_startup_phase"]), 4))[0]
                result["bsd_entry"] = dict(startup_phase=phase,
                    irq_unmasked=not bool(engine.reg_read(UC_ARM64_REG_PSTATE) & 0x80),
                    bsd_initialization_completed=False, user_space_booted=False, device_boot_proven=False)
                if (not result.get("crypto_startup", {}).get("registration_contract_passed") or
                        not result.get("interrupt_boundary", {}).get("irq_unmasked")):
                    result["fault"] = dict(kind="bsd-entry-without-observed-crypto-and-interrupt-startup")
            if stage == "interrupts-enabled":
                phase = struct.unpack("<I", engine.mem_read(physical(symbols["_startup_phase"]), 4))[0]
                event["startup_phase"] = phase
                if phase < early_boot_subsystem:
                    return
                irq_unmasked = not bool(engine.reg_read(UC_ARM64_REG_PSTATE) & 0x80)
                result["interrupt_boundary"] = dict(startup_phase=phase, irq_unmasked=irq_unmasked,
                    irq_delivery_proven=False, device_boot_proven=False)
                if (phase != early_boot_subsystem or not irq_unmasked or
                        not result.get("crypto_startup", {}).get("registration_contract_passed")):
                    result["fault"] = dict(kind="early-boot-interrupt-boundary-contract-not-met")
                result["reached"] = True
                engine.emu_stop()
                return
            if stage in ("topology-done", "entropy-done", "vm-done", "serial-done", "vm-mem-done", "sched-done", "clock-done", "crypto-done"):
                if stage == "entropy-done":
                    if original_seed is None:
                        result["fault"] = dict(kind="entropy-test-requires-seed")
                        engine.emu_stop()
                        return
                    entropy_destination = engine.reg_read(UC_ARM64_REG_X0)
                return_address = event["caller_return_va"]
                hooks.append(cpu.hook_add(UC_HOOK_CODE, topology_return, begin=return_address, end=return_address))
            else:
                result["reached"] = True
                engine.emu_stop()

    names = {target, "_arm_init", "_cpu_data_init", "_PE_init_platform", "_pe_identify_machine",
             "_SecureDTInit", "_ml_parse_cpu_topology", "_thread_bootstrap", "_kernel_startup_bootstrap",
             "_arm_vm_init", "_PE_get_random_seed", "_early_random", "_kalloc_type_apply_policy",
             "_kmem_crypto_init", "_register_crypto_functions", "_register_and_init_prng",
             "_mido_boot_crypto_startup", "_mido_kernel_prng_install_native",
             "_initialize_screen",
             "_mido_irq_timer_startup", "_ml_install_interrupt_handler", "_ml_io_map",
             "_panic", "_panic_with_options", "___assert_rtn", "__Assert"}
    names.update(name for name in symbols if name.startswith("___ubsan_handle_"))
    for name in sorted(names):
        if name in symbols:
            address = symbols[name]
            hooks.append(cpu.hook_add(UC_HOOK_CODE, observe, name, begin=address, end=address))

    def invalid(engine, access, address, size, value, context):
        result["fault"] = dict(kind="unmapped-memory", access=access, address=address,
                               size=size, pc=engine.reg_read(UC_ARM64_REG_PC))
        return False

    def write(engine, access, address, size, value, context):
        virtual_address = virtual_base + address - physical_base if physical_base <= address < physical_base + memory_size else address
        allowed = any((segment["initprot"] & 2 or segment["name"] == "__DATA_CONST") and segment["vmaddr"] <= virtual_address
                      and virtual_address + size <= segment["vmaddr"] + segment["vmsize"]
                      for segment in inspection["segments"])
        seed_pa = fixture.get("random_seed_pa", 0)
        if seed_pa and seed_pa <= physical(address) and physical(address) + size <= seed_pa + fixture["random_seed_bytes"]:
            allowed = True
        if fixture["top_of_kernel_data"] <= physical(address) and physical(address) + size <= allocation_end:
            allowed = True
        if gic_model is not None and size == 4:
            for mapping in io_mappings:
                for base in (mapping["physical_base"], mapping["virtual_base"]):
                    if base <= address and address + size <= base + mapping["size"]:
                        allowed = True
        if not allowed:
            result["fault"] = dict(kind="write-outside-writable-kernel-segments", address=address,
                                   virtual_address=virtual_address,
                                   size=size, pc=engine.reg_read(UC_ARM64_REG_PC))
            engine.emu_stop()
        result["writes"] += 1

    hooks.append(cpu.hook_add(UC_HOOK_MEM_INVALID, invalid))
    hooks.append(cpu.hook_add(UC_HOOK_MEM_WRITE, write))
    instruction_budget = 200000000 if stage in ("vm-mem-done", "sched-done", "clock-done", "crypto-entry", "crypto-done", "interrupts-enabled", "bsd-entry") else 10000000
    timeout_budget = 120000000 if stage in ("vm-mem-done", "sched-done", "clock-done", "crypto-entry", "crypto-done", "interrupts-enabled", "bsd-entry") else 30000000
    result["execution_budget"] = dict(instructions=instruction_budget, timeout_microseconds=timeout_budget)
    try:
        cpu.emu_start(cpu.reg_read(UC_ARM64_REG_PC), 0, timeout=timeout_budget, count=instruction_budget)
    except Exception as error:
        result["execution_error"] = str(error)
        pc = cpu.reg_read(UC_ARM64_REG_PC)
        preceding = [(value, name) for name, value in symbols.items() if value <= pc]
        result["exception_context"] = dict(pc=pc, x8=cpu.reg_read(UC_ARM64_REG_X8))
        if preceding:
            symbol_address, symbol_name = max(preceding)
            result["exception_context"].update(symbol=symbol_name, symbol_offset=pc - symbol_address)
        if virtual_base <= pc < virtual_base + memory_size:
            result["exception_context"]["instruction_le_hex"] = bytes(cpu.mem_read(physical(pc), 4)).hex()
    finally:
        for hook in hooks:
            cpu.hook_del(hook)
    result["final_pc"] = cpu.reg_read(UC_ARM64_REG_PC)
    if gic_model is not None:
        result["gic_model"] = gic_model.report()
        result["gic_model"]["mappings"] = io_mappings
        registrations = [event for event in result["events"] if event["function"] == "_ml_install_interrupt_handler"]
        result["gic_model"]["native_handler_registered_once"] = len(registrations) == 1
        if result["reached"] and stage == "bsd-entry" and (
                not gic_model.report()["timer_enabled"] or len(registrations) != 1 or len(io_mappings) != 2):
            result["fault"] = dict(kind="native-gic-startup-contract-not-met")
    result["completed"] = result["reached"] and result["fault"] is None and "execution_error" not in result
    if not result["reached"] and result["fault"] is None and "execution_error" not in result:
        result["stop_reason"] = "checkpoint-not-reached-within-execution-budget"
    if fixture.get("random_seed_pa"):
        result["boot_tree_seed_erased"] = not any(cpu.mem_read(fixture["random_seed_pa"], fixture["random_seed_bytes"]))
    if result["completed"] and stage == "topology-done":
        return_address = result["topology_return_va"]
        topology = {}
        def accessor_return(engine, address, size, context):
            engine.emu_stop()
        hook = cpu.hook_add(UC_HOOK_CODE, accessor_return, begin=return_address, end=return_address)
        try:
            for name, expected in (("_ml_get_cpu_count", 1), ("_ml_get_cluster_count", 1),
                                   ("_ml_get_boot_cpu_number", 0), ("_ml_get_max_cpu_number", 0)):
                cpu.reg_write(UC_ARM64_REG_X30, return_address)
                cpu.emu_start(symbols[name], 0, timeout=1000000, count=1000)
                value = cpu.reg_read(UC_ARM64_REG_X0) & 0xffffffff
                if cpu.reg_read(UC_ARM64_REG_PC) != return_address or value != expected:
                    raise AssertionError(f"Topology accessor {name} returned {value}, expected {expected}")
                topology[name] = value
            result["topology_accessors"] = topology
            result["accessor_scope"] = "Separate diagnostic calls after the original parser returned; no later arm_init code executed"
        except Exception as error:
            result["completed"] = False
            result["accessor_error"] = str(error)
        finally:
            cpu.hook_del(hook)
    if result["completed"] and irq_diagnostic:
        try:
            from tools.trace_mido_irq_handler import diagnose, vector_diagnose
        except ModuleNotFoundError:
            from trace_mido_irq_handler import diagnose, vector_diagnose
        try:
            if gic_model is None:
                raise ValueError("IRQ diagnostics require the integrated backend")
            result["native_irq_vector"] = vector_diagnose(cpu, symbols, gic_model, write)
            if not result["native_irq_vector"]["passed"]:
                result["completed"] = False
                return result
            result["native_irq_diagnostic"] = diagnose(cpu, symbols, gic_model, write)
            if not result["native_irq_diagnostic"]["passed"] or result["fault"] is not None:
                result["completed"] = False
        except Exception as error:
            result["completed"] = False
            result["native_irq_diagnostic_error"] = str(error)
    return result
