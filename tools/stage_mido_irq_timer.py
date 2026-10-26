"""Opt-in staging of the single-CPU MIDO diagnostic GICv2/timer backend."""

import hashlib
from pathlib import Path


UNITS = {
    "irq_timer.c": "devices/mido/xnu/early/irq_timer.c",
    "irq_timer.h": "devices/mido/xnu/early/irq_timer.h",
    "arm64_timer.c": "devices/mido/xnu/early/arm64_timer.c",
    "mido_irq_timer.c": "devices/mido/xnu/runtime/mido_irq_timer.c",
}


def stage_irq_timer(source, workspace=None):
    source = source.resolve()
    workspace = workspace or Path(__file__).resolve().parent.parent
    target = source / "osfmk/kern/mido_irq"
    paths = [target, source / "osfmk/conf/files", source / "osfmk/conf/Makefile.arm64"]
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("escaped IRQ staging path")
    if target.exists():
        raise ValueError("refusing to replace IRQ backend")
    contents = {name: (workspace / relative).read_bytes().replace(b"\r\n", b"\n")
                for name, relative in UNITS.items()}
    configurations = {}
    for path in paths[1:]:
        before = path.read_bytes().replace(b"\r\n", b"\n")
        if b"mido_irq/" in before or b"mido_irq_" in before:
            raise ValueError("IRQ backend already configured")
        if path.name == "files":
            after = before + b"\n" + b"".join(
                f"osfmk/kern/mido_irq/mido_irq_{name} optional mido_runtime\n".encode()
                for name in contents if name.endswith(".c"))
        else:
            after = before + b"\n" + b"".join(
                (f"mido_irq_{Path(name).stem}.o_CFLAGS_ADD += -DMIDO_IRQ_TIMER_DIAGNOSTIC=1 "
                 "-mgeneral-regs-only -fno-stack-protector -fno-lto\n").encode()
                for name in contents if name.endswith(".c"))
        configurations[path] = (before, after)
    target.mkdir()
    records = {}
    for name, data in contents.items():
        path = target / ("mido_irq_" + name if name.endswith(".c") else name)
        path.write_bytes(data)
        records[path.relative_to(source).as_posix()] = {"sha256": hashlib.sha256(data).hexdigest()}
    for path, (before, after) in configurations.items():
        path.write_bytes(after)
        records[path.relative_to(source).as_posix()] = dict(
            before_sha256=hashlib.sha256(before).hexdigest(), sha256=hashlib.sha256(after).hexdigest())
    return dict(files=records, single_cpu_only=True, timer_intid=20,
                unexpected_interrupt_policy="panic without EOI", hardware_verified=False,
                startup="EARLY_BOOT/LAST", boot_approved=False)
