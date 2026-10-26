"""Stage MIDO-only runtime hooks with an explicitly unavailable Firehose service."""

import hashlib
from pathlib import Path


SOURCE_HASHES = {
    "osfmk/conf/files": "1e4d676564f5a2cfa6dc2fadd22a034ad9ca4ed267a082e0f4b236f0c2fbe7b6",
    "libkern/os/log.c": "f1aa9bf4d5a990f8bd5bcd56cd58dc4aea7ccd14b0f19e47e4dbcca294e99b82",
    "bsd/kern/subr_log.c": "8611bc5219e811f894c9f706c1f6ed35716f4f02df0e45a63ba05303e8ea1e0e",
}
REPLACEMENTS = {
    "libkern/os/log.c": (
        (b"static bool oslog_disabled = false;\n",
         b"#if defined(ARM64_BOARD_CONFIG_MIDO)\nstatic bool oslog_disabled = true;\n"
         b"#else\nstatic bool oslog_disabled = false;\n#endif\n"),
        (b"\toslog_disabled = atm_get_diagnostic_config() & ATM_TRACE_DISABLE;\n",
         b"#if defined(ARM64_BOARD_CONFIG_MIDO)\n\toslog_disabled = true;\n#else\n"
         b"\toslog_disabled = atm_get_diagnostic_config() & ATM_TRACE_DISABLE;\n#endif\n"),
    ),
    "bsd/kern/subr_log.c": tuple(
        (signature + b"\n{\n", signature + b"\n{\n"
         b"#if defined(ARM64_BOARD_CONFIG_MIDO)\n\treturn ENOTSUP;\n#endif\n")
        for signature in (
            b"oslogopen(__unused dev_t dev, __unused int flags, __unused int mode, struct proc *p)",
            b"oslogioctl(__unused dev_t dev, u_long com, caddr_t data, __unused int flag, __unused struct proc *p)",
        )
    ),
}
RUNTIME_NAMES = ("mido_runtime.c", "mido_ubsan.c")


def stage_runtime(source):
    source = source.resolve()
    bundled = Path(__file__).resolve().parent.parent / "devices/mido/xnu/runtime"
    pending = []
    report = {}
    for relative, expected in SOURCE_HASHES.items():
        target = source / relative
        if target.is_symlink() or not target.resolve().is_relative_to(source):
            raise ValueError("escaped MIDO runtime configuration")
        data = target.read_bytes().replace(b"\r\n", b"\n")
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("unexpected MIDO runtime source: " + relative)
        for original, replacement in REPLACEMENTS.get(relative, ()):
            if data.count(original) != 1:
                raise ValueError("unexpected MIDO runtime anchor: " + relative)
            data = data.replace(original, replacement)
        if relative == "osfmk/conf/files":
            data += b"\n" + b"".join(
                f"osfmk/kern/{name} optional mido_runtime\n".encode() for name in RUNTIME_NAMES)
        pending.append((target, data))
        report[relative] = {"original_sha256": expected, "sha256": hashlib.sha256(data).hexdigest()}
    for name in RUNTIME_NAMES:
        target = source / "osfmk/kern" / name
        if target.exists() or target.is_symlink() or not target.resolve().is_relative_to(source):
            raise ValueError("refusing to replace MIDO runtime")
        data = (bundled / name).read_bytes().replace(b"\r\n", b"\n")
        pending.append((target, data))
        report[target.relative_to(source).as_posix()] = {"sha256": hashlib.sha256(data).hexdigest()}
    for target, data in pending:
        target.write_bytes(data)
    return {"files": report, "firehose_transport_available": False,
            "pmu_available": False, "apple_monitor_available": False,
            "ubsan_policy": "panic", "cache_backend": "CleanPoC_DcacheRegion_Force",
            "boot_approved": False}
