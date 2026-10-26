"""Explicit staging of a diagnostic framebuffer marker using native IO mapping."""

import hashlib
from pathlib import Path


UNITS = {
    "mapped_checkpoint.h": "devices/mido/xnu/early/mapped_checkpoint.h",
    "mapped_checkpoint.c": "devices/mido/xnu/early/mapped_checkpoint.c",
    "mido_mapped_checkpoint.c": "devices/mido/xnu/runtime/mido_mapped_checkpoint.c",
}


def stage_mapped_checkpoint(source, workspace=None):
    source = source.resolve()
    workspace = workspace or Path(__file__).resolve().parent.parent
    target = source / "osfmk/kern/mido_framebuffer"
    paths = [source / "osfmk/conf/files", source / "osfmk/conf/Makefile.arm64"]
    for path in [target, *paths]:
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("escaped mapped checkpoint staging path")
    if target.exists():
        raise ValueError("refusing to replace mapped checkpoint backend")
    contents = {name: (workspace / relative).read_bytes().replace(b"\r\n", b"\n")
                for name, relative in UNITS.items()}
    configurations = {}
    for path in paths:
        before = path.read_bytes().replace(b"\r\n", b"\n")
        if b"mido_framebuffer" in before:
            raise ValueError("mapped checkpoint already configured")
        if path.name == "files":
            extra = "".join(f"osfmk/kern/mido_framebuffer/mido_framebuffer_{name} optional mido_runtime\n"
                            for name in contents if name.endswith(".c"))
        else:
            extra = "".join(
                f"mido_framebuffer_{Path(name).stem}.o_CFLAGS_ADD += "
                "-DMIDO_MAPPED_CHECKPOINT_DIAGNOSTIC=1 -mgeneral-regs-only -fno-stack-protector -fno-lto\n"
                for name in contents if name.endswith(".c"))
        configurations[path] = before + b"\n" + extra.encode()
    target.mkdir()
    records = {}
    for name, data in contents.items():
        path = target / ("mido_framebuffer_" + name if name.endswith(".c") else name)
        path.write_bytes(data)
        records[path.relative_to(source).as_posix()] = hashlib.sha256(data).hexdigest()
    for path, data in configurations.items():
        path.write_bytes(data)
        records[path.relative_to(source).as_posix()] = hashlib.sha256(data).hexdigest()
    return dict(files=records, startup="EARLY_BOOT/MIDDLE", boot_approved=False,
                hardware_verified=False, requires_explicit_framebuffer_contract=True)
