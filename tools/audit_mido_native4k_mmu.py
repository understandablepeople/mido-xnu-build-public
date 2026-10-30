"""Offline native-4K MMU startup and mapped-read/return audit; no device access."""

import argparse
import hashlib
import json
import struct
import subprocess
from pathlib import Path

from tools.audit_mido_native4k_binary import KERNEL_SHA256, PHYSICAL, ARENA_SIZE, POOL_SIZE, reference_tables
from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols

OBSERVER_SHA256 = "0a46e392c9e95f5eb3ddff55492572235a67657d61aa4fabec5eaa42d0092e76"
OBSERVER_PA = 0x12400000
ARGS_PA = 0x12200000
RETURN_PA = 0x10080000
MODES = ("normal", "missing-high-root", "missing-low-root", "missing-args-block", "missing-stack-block")


def branch_word(source, target):
    distance = target - source
    if (source | target) & 3 or not -(1 << 27) <= distance < 1 << 27:
        raise ValueError("Branch outside aligned imm26 range")
    return 0x14000000 | ((distance >> 2) & 0x3ffffff)


def adrp_word(source, target):
    distance = (target >> 12) - (source >> 12)
    if not -(1 << 20) <= distance < 1 << 20:
        raise ValueError("ADRP outside signed page range")
    immediate = distance & 0x1fffff
    return 0x90000000 | ((immediate & 3) << 29) | ((immediate >> 2) << 5)


def build_observer(toolchain, directory):
    source = Path(__file__).resolve().parents[1] / "devices/mido/xnu/probe/native4k_mmu_observer.S"
    directory.mkdir(parents=True, exist_ok=False)
    subprocess.run([str(toolchain / "clang.exe"), "--target=aarch64-none-elf", "-mcpu=cortex-a53",
                    "-c", str(source), "-o", str(directory / "observer.o")], check=True)
    subprocess.run([str(toolchain / "ld.lld.exe"), "-Ttext=0x12400000", "-e", "mido_native_mmu_trampoline",
                    str(directory / "observer.o"), "-o", str(directory / "observer.elf")], check=True)
    subprocess.run([str(toolchain / "llvm-objcopy.exe"), "-O", "binary", "--only-section=.text",
                    str(directory / "observer.elf"), str(directory / "observer.bin")], check=True)
    observer = (directory / "observer.bin").read_bytes()
    if hashlib.sha256(observer).hexdigest() != OBSERVER_SHA256:
        raise ValueError("Compiled observer differs from reviewed 92-byte sequence")
    return observer


def execute(kernel, observer, mode="normal"):
    if mode not in MODES:
        raise ValueError("Unknown native-4K MMU scenario")
    if hashlib.sha256(kernel).hexdigest() != KERNEL_SHA256:
        raise ValueError("Requires exact reviewed full-provider native-4K kernel")
    if hashlib.sha256(observer).hexdigest() != OBSERVER_SHA256:
        raise ValueError("Requires exact reviewed read-only mapped observer")
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_TLB_CPU
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_INVALID, UC_HOOK_INTR, UC_HOOK_INSN
    from unicorn import arm64_const as registers

    symbols = macho_symbols(kernel)
    segments = [segment for segment in inspect(kernel)["segments"] if segment["vmsize"]]
    header = min(segment["vmaddr"] for segment in segments)
    virtual = header & -2097152
    initial = bytearray(ARENA_SIZE)
    for segment in segments:
        offset = segment["vmaddr"] - virtual
        if not 0 <= offset <= ARENA_SIZE - segment["vmsize"]:
            raise ValueError("Kernel segment outside bounded arena")
        initial[offset:offset + segment["filesize"]] = kernel[segment["fileoff"]:segment["fileoff"] + segment["filesize"]]
    if any(initial[ARGS_PA - PHYSICAL:ARGS_PA - PHYSICAL + 4096]) or any(initial[OBSERVER_PA - PHYSICAL:OBSERVER_PA - PHYSICAL + 4096]):
        raise ValueError("Synthetic arguments or observer overlap existing bytes")
    struct.pack_into("<Q", initial, ARGS_PA - PHYSICAL + 8, virtual)
    observer_va = virtual + OBSERVER_PA - PHYSICAL
    initial[OBSERVER_PA - PHYSICAL:OBSERVER_PA - PHYSICAL + len(observer)] = observer
    arm_init = symbols["_arm_init"]
    struct.pack_into("<I", initial, arm_init - virtual, branch_word(arm_init, observer_va))
    common_va = symbols["common_start"]
    vector_site = common_va + 0x9c
    if struct.unpack_from("<I", initial, vector_site - virtual)[0] != 0x90ffffe0:
        raise ValueError("Original VBAR setup instruction differs")
    vectors = symbols["_LowExceptionVectorBase"]
    if any(struct.unpack_from("<I", initial, vectors - virtual + slot * 128)[0] != 0x14000000 for slot in range(16)):
        raise ValueError("Exception vectors are not halt-only")
    struct.pack_into("<I", initial, vector_site - virtual, adrp_word(vector_site, vectors))
    tables = PHYSICAL + symbols["_bootstrap_pagetables"] - virtual
    expected_tables, exhausted = reference_tables(tables, PHYSICAL + header - virtual, header, ARENA_SIZE)
    if exhausted:
        raise ValueError("Diagnostic arena exhausted bootstrap pool")
    tcr = struct.unpack_from("<Q", initial, symbols["_sysreg_restore"] - virtual)[0]
    start = PHYSICAL + symbols["_mido_checkpoint_args_loaded"] + 48 - virtual
    common = PHYSICAL + common_va - virtual
    setter = PHYSICAL + symbols["_set_mmu_ttb"] - virtual
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.ctl_set_cpu_model(registers.UC_CPU_ARM64_A53)
    cpu.ctl_set_tlb_mode(UC_TLB_CPU)
    cpu.mem_map(PHYSICAL, ARENA_SIZE)
    cpu.mem_write(PHYSICAL, bytes(initial))
    cpu.mem_map(RETURN_PA, 4096)
    cpu.reg_write(registers.UC_ARM64_REG_PSTATE, 0x3c5)
    cpu.cpr_write(3, 6, 1, 1, 0, 0x401)
    cpu.cpr_write(3, 4, 1, 1, 0, 1 << 31)
    cpu.cpr_write(3, 0, 1, 0, 0, 0xc00800)
    for name, value in (("X20", ARGS_PA), ("X21", 0), ("X22", virtual), ("X23", PHYSICAL),
                        ("X24", ARENA_SIZE), ("X25", tables), ("X29", RETURN_PA)):
        cpu.reg_write(getattr(registers, "UC_ARM64_REG_" + name), value)
    events, faults = [], []
    injected = None

    def instruction(engine, address, size, context):
        nonlocal injected
        if address == RETURN_PA:
            events.append("returned-mmu-off")
            engine.emu_stop()
            return
        if address == arm_init:
            events.append("arm-init-boundary")
            return
        if address == common:
            if bytes(engine.mem_read(tables, POOL_SIZE)) != expected_tables:
                raise AssertionError("Native tables differ before MMU enable")
            events.append("native-tables-verified")
            if mode in ("missing-high-root", "missing-low-root"):
                upper = mode == "missing-high-root"
                cursor = virtual if upper else PHYSICAL
                injected = tables + (4096 if upper else 0) + ((cursor >> 30) & 255) * 8
            elif mode != "normal":
                cursor = virtual + ARGS_PA - PHYSICAL if mode == "missing-args-block" else symbols["_intstack_top"] - 8
                injected = tables + 12288 + ((cursor >> 21) & 511) * 8
            if injected is not None:
                engine.mem_write(injected, bytes(8))
        if address == observer_va + 36:
            if engine.reg_read(registers.UC_ARM64_REG_X17) != virtual:
                raise AssertionError("Translated arguments read differs")
            events.append("translated-args-read")
        if address == observer_va + 40:
            expected = struct.unpack_from("<Q", initial, symbols["_intstack_top"] - virtual - 8)[0]
            if engine.reg_read(registers.UC_ARM64_REG_X18) != expected:
                raise AssertionError("Translated stack read differs")
            events.append("translated-stack-read")
        if not (start <= address < common + 256 or setter <= address < setter + 16
                or observer_va <= address < observer_va + len(observer)
                or OBSERVER_PA <= address < OBSERVER_PA + len(observer)):
            raise AssertionError(f"Execution escaped reviewed startup/observer windows: {address:#x}")

    def write(engine, access, address, size, value, context):
        if engine.cpr_read(3, 0, 1, 0, 0) & 0x1005 or not tables <= address < address + size <= tables + POOL_SIZE:
            raise AssertionError("Write outside pre-MMU table construction")

    def invalid(engine, access, address, size, value, context):
        faults.append(dict(kind="unmapped", address=address, access=access))
        return False

    def interrupt(engine, number, context):
        faults.append(dict(kind="exception", number=number, pc=engine.reg_read(registers.UC_ARM64_REG_PC),
                           esr=engine.cpr_read(3, 0, 5, 2, 0), far=engine.cpr_read(3, 0, 6, 0, 0)))
        engine.emu_stop()

    def system_write(engine, register, encoding, context):
        if (encoding.op0, encoding.op1, encoding.crn, encoding.crm, encoding.op2) == (3, 0, 1, 0, 0):
            original = engine.reg_read(register)
            engine.reg_write(register, original | (1 << 23))
            following = engine.reg_read(registers.UC_ARM64_REG_PC) + 4

            def restore_operand(cpu, address, size, context):
                cpu.reg_write(register, original)
                cpu.hook_del(hook)

            hook = engine.hook_add(UC_HOOK_CODE, restore_operand, begin=following, end=following)
        return 0

    cpu.hook_add(UC_HOOK_CODE, instruction)
    cpu.hook_add(UC_HOOK_MEM_WRITE, write)
    cpu.hook_add(UC_HOOK_MEM_INVALID, invalid)
    cpu.hook_add(UC_HOOK_INTR, interrupt)
    cpu.hook_add(UC_HOOK_INSN, system_write, None, aux1=registers.UC_ARM64_INS_MSR)
    try:
        cpu.emu_start(start, 0, timeout=10000000, count=100000)
    except Exception:
        if not faults:
            raise
    expected = bytearray(initial)
    expected[tables - PHYSICAL:tables - PHYSICAL + POOL_SIZE] = expected_tables
    if injected is not None:
        expected[injected - PHYSICAL:injected - PHYSICAL + 8] = bytes(8)
    if bytes(cpu.mem_read(PHYSICAL, ARENA_SIZE)) != expected:
        raise AssertionError("Arena changed outside tables and explicit fault injection")
    state = dict(sctlr=cpu.cpr_read(3, 0, 1, 0, 0), tcr=cpu.cpr_read(3, 0, 2, 0, 2),
                 ttbr0=cpu.cpr_read(3, 0, 2, 0, 0), ttbr1=cpu.cpr_read(3, 0, 2, 0, 1),
                 sp=cpu.reg_read(registers.UC_ARM64_REG_SP), pc=cpu.reg_read(registers.UC_ARM64_REG_PC))
    if mode == "normal":
        if faults or events != ["native-tables-verified", "arm-init-boundary", "translated-args-read", "translated-stack-read", "returned-mmu-off"]:
            raise AssertionError(f"Incomplete translated-read/return path: {events}, {faults}")
        if (state["sctlr"], state["tcr"], state["ttbr0"], state["ttbr1"], state["sp"]) != (0xc00800, tcr, tables, tables + 4096, symbols["_intstack_top"]):
            raise AssertionError("MMU or stack state differs at observer return")
    elif not faults or "returned-mmu-off" in events or injected is None:
        raise AssertionError("Broken mapping failed to stop before successful return")
    if mode != "normal":
        expected_events = ["native-tables-verified"]
        if mode in ("missing-args-block", "missing-stack-block"):
            expected_events.append("arm-init-boundary")
        if mode == "missing-stack-block":
            expected_events.append("translated-args-read")
        expected_pc = {"missing-high-root": arm_init, "missing-low-root": common + 0xc4,
                       "missing-args-block": observer_va + 32, "missing-stack-block": observer_va + 36}[mode]
        if events != expected_events or len(faults) != 1 or faults[0].get("pc") != expected_pc:
            raise AssertionError(f"Fault did not occur at the intended missing mapping: {events}, {faults}")
    return dict(mode=mode, events=events, faults=faults, state=state, kernel_sha256=KERNEL_SHA256,
                all_arena_bytes_verified=ARENA_SIZE, modeled_sctlr_res1_bit=23,
                hardware_execution_proven=False, boot_approved=False,
                scope="Offline synthetic args, patched arm_init boundary, no original C execution")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", type=Path)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    observer = build_observer(args.toolchain, args.output_directory)
    kernel = args.kernel.read_bytes()
    result = {mode: execute(kernel, observer, mode) for mode in MODES}
    (args.output_directory / "mmu-audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
