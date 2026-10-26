"""Opt-in pre-MMU framebuffer checkpoints in the reviewed MIDO startup."""

import hashlib
from pathlib import Path


START_SHA256 = "0c1ee26454db866e13ebfc183cd213c29c65d6742ad4eff3b01886ff9d1c98c9"
ENTRY = b"LEXT(start_first_cpu)\n"
ARGS = b"\tldr\t\tx26, [x20, BA_BOOT_FLAGS]\t\t\t// Get the kernel boot flags\n"
MACRO = "devices/mido/xnu/probe/boot_checkpoints.inc"


def stage_boot_checkpoints(source, workspace=None):
    source = source.resolve()
    workspace = workspace or Path(__file__).resolve().parent.parent
    startup = source / "osfmk/arm64/start.s"
    configuration = source / "config/MASTER.arm64.MIDO"
    for path in (startup, configuration):
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("escaped boot checkpoint staging path")
    before = startup.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(before).hexdigest() != START_SHA256:
        raise ValueError("unexpected prepared startup source for boot checkpoints")
    configuration.read_bytes()
    macro = (workspace / MACRO).read_bytes().replace(b"\r\n", b"\n")
    if before.count(ENTRY) != 1:
        raise ValueError("ambiguous startup checkpoint anchors")
    prefix, cold_start = before.split(ENTRY)
    if cold_start.count(ARGS) != 1:
        raise ValueError("ambiguous cold-start checkpoint anchor")
    definitions = b"#if defined(MIDO)\n" + macro + b"\n#endif\n"
    first = (b"#if defined(MIDO)\n.globl EXT(mido_checkpoint_entry)\n"
             b"LEXT(mido_checkpoint_entry)\n    MIDO_EARLY_MARK 560\n#endif\n")
    second = (b"#if defined(MIDO)\n.globl EXT(mido_checkpoint_args_loaded)\n"
              b"LEXT(mido_checkpoint_args_loaded)\n    MIDO_EARLY_MARK 584\n#endif\n")
    after = prefix + definitions + ENTRY + first + cold_start.replace(ARGS, ARGS + second)
    startup.write_bytes(after)
    return dict(
        startup_before_sha256=START_SHA256, startup_sha256=hashlib.sha256(after).hexdigest(),
        macro_sha256=hashlib.sha256(macro).hexdigest(),
        framebuffer=dict(base=0x90001000, stride=3240, bytes_per_pixel=3),
        marks=[dict(symbol="mido_checkpoint_entry", row=560, meaning="start_first_cpu entered"),
               dict(symbol="mido_checkpoint_args_loaded", row=584, meaning="boot_args memory parameters loaded")],
        scratch_registers=["x9", "x10", "x11", "x12"],
        pre_mmu_only=True, original_startup_instructions_removed=False,
        hardware_verified=False, boot_approved=False)
