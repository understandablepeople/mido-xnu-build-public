"""Stage an opt-in synthetic-only IOPlatformExpert without replacing the panic fallback."""

import hashlib
from pathlib import Path


CATALOG_SHA256 = "05085aed787fcdff93d53b946e602a5cdc8432ce2741a97de79e7b21fd267ba4"
UNITS = {
    "MidoDiagnosticPlatform.cpp": "devices/mido/xnu/runtime/MidoDiagnosticPlatform.cpp",
    "platform_contract.h": "devices/mido/xnu/early/platform_contract.h",
    "pmic_rtc.c": "devices/mido/xnu/early/pmic_rtc.c",
    "pmic_rtc.h": "devices/mido/xnu/early/pmic_rtc.h",
    "mido_pmic_clock.c": "devices/mido/xnu/runtime/mido_pmic_clock.c",
    "mido_pmic_clock.h": "devices/mido/xnu/runtime/mido_pmic_clock.h",
}
PERSONALITY = b'''    "   {"
    "     'IOClass'         = MidoDiagnosticPlatform;"
    "     'IOProviderClass' = IOPlatformExpertDevice;"
    "     'IONameMatch'     = 'mido,synthetic-abi-only';"
    "     'IOProbeScore'    = 1000:32;"
    "   },"
'''


def stage_platform_expert(source, workspace=None):
    source = source.resolve()
    workspace = workspace or Path(__file__).resolve().parent.parent
    target = source / "iokit/Kernel/mido_platform"
    graph = source / "iokit/conf/files"
    makefile = source / "iokit/conf/Makefile.arm64"
    catalog = source / "iokit/KernelConfigTables.cpp"
    configuration = source / "config/MASTER.arm64.MIDO"
    for path in (target, graph, makefile, catalog, configuration):
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("escaped diagnostic platform staging path")
    if target.exists():
        raise ValueError("refusing to replace diagnostic platform backend")
    contents = {name: (workspace / relative).read_bytes().replace(b"\r\n", b"\n")
                for name, relative in UNITS.items()}
    before = {path: path.read_bytes().replace(b"\r\n", b"\n")
              for path in (graph, makefile, catalog, configuration)}
    if b"pseudo-device mido_runtime" not in before[configuration].splitlines():
        raise ValueError("diagnostic platform requires MIDO runtime configuration")
    if hashlib.sha256(before[catalog]).hexdigest() != CATALOG_SHA256:
        raise ValueError("unexpected prepared kernel personality catalogue")
    if any(b"MidoDiagnosticPlatform" in before[path] for path in (graph, makefile)):
        raise ValueError("diagnostic platform already configured")
    anchor = b'    "("\n'
    if before[catalog].count(anchor) != 1:
        raise ValueError("ambiguous kernel personality catalogue anchor")
    after = {
        graph: before[graph] + b"\n" + b"".join(
            f"iokit/Kernel/mido_platform/{name} optional mido_runtime\n".encode()
            for name in contents if name.endswith((".c", ".cpp"))),
        makefile: before[makefile] + b"\nMidoDiagnosticPlatform.cpo_CFLAGS_ADD += "
                  b"-DMIDO_DIAGNOSTIC_PLATFORM=1 -mgeneral-regs-only -fno-stack-protector -fno-lto\n" + b"".join(
                      (f"{Path(name).stem}.o_CFLAGS_ADD += -DMIDO_DIAGNOSTIC_PLATFORM=1 "
                       "-mgeneral-regs-only -fno-stack-protector -fno-lto" +
                       (" -DPEXPERT_KERNEL_PRIVATE=1" if name == "mido_pmic_clock.c" else "") + "\n").encode()
                      for name in contents if name.endswith(".c")),
        catalog: before[catalog].replace(anchor, anchor + PERSONALITY),
    }
    target.mkdir()
    records = {}
    for name, data in contents.items():
        path = target / name
        path.write_bytes(data)
        records[path.relative_to(source).as_posix()] = dict(sha256=hashlib.sha256(data).hexdigest())
    for path, data in after.items():
        path.write_bytes(data)
        records[path.relative_to(source).as_posix()] = dict(
            before_sha256=hashlib.sha256(before[path]).hexdigest(), sha256=hashlib.sha256(data).hexdigest())
    return dict(files=records, synthetic_identity_only=True, requires_explicit_dt_contract=True,
                panic_personality_preserved=True, rtc_resource_published=False,
                hardware_verified=False, boot_approved=False)
