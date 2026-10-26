"""Opt-in staging of a fail-closed, incomplete MIDO bootstrap crypto provider."""

import hashlib
from pathlib import Path

try:
    from tools.check_mido_native_provider import UNIT_PATHS
    from tools.test_mido_drbg import ARCHIVE_SHA256, verify_dependency
except ModuleNotFoundError:
    from check_mido_native_provider import UNIT_PATHS
    from test_mido_drbg import ARCHIVE_SHA256, verify_dependency


UNSUPPORTED = ("AES-ECB", "DES", "TDES", "CTS3", "ChaCha20-Poly1305", "RSA",
               "crypto_digest_v2", "crypto_hmac_v2")
TARGET = Path("osfmk/kern/mido_crypto")


def stage_boot_crypto(source, workspace=None):
    source = source.resolve()
    workspace = (workspace or Path(__file__).resolve().parent.parent).resolve()
    dependency = workspace / "artifacts/bearssl-0.6"
    verify_dependency(workspace / "artifacts/bearssl-0.6.tar.gz", dependency)
    target = source / TARGET
    if target.exists() or target.is_symlink() or not target.resolve().is_relative_to(source):
        raise ValueError("refusing to replace or escape MIDO bootstrap crypto")
    configuration = source / "osfmk/conf/files"
    makefile = source / "osfmk/conf/Makefile.arm64"
    for path in (configuration, makefile):
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("escaped MIDO bootstrap configuration")
    files_before = configuration.read_bytes()
    make_before = makefile.read_bytes()
    if b"mido_crypto" in files_before or b"MIDO_BOOT_CRYPTO_DIAGNOSTIC" in make_before:
        raise ValueError("MIDO bootstrap crypto already staged")
    units = dict(UNIT_PATHS)
    units["mido_boot_crypto.c"] = "devices/mido/xnu/runtime/mido_boot_crypto.c"
    contents = {}
    origins = {}

    def add(name, path):
        if name in contents or path.is_symlink():
            raise ValueError("duplicate or symbolic bootstrap dependency: " + name)
        contents[name] = path.read_bytes()
        origins[name] = path.relative_to(workspace).as_posix()

    for name, relative in units.items():
        add("mido_crypto_" + name, workspace / relative)
    for directory in (workspace / "devices/mido/xnu/early", workspace / "devices/mido/xnu/runtime",
                      dependency / "inc"):
        for path in sorted(directory.glob("*.h")):
            add(path.name, path)
    for relative in ("src/inner.h", "src/config.h", "LICENSE.txt"):
        path = dependency / relative
        add(path.name, path)
    add("limits.h", workspace / "devices/mido/xnu/runtime/mido_kernel_limits.h")
    files_after = files_before + b"\n" + b"".join(
        f"{TARGET.as_posix()}/mido_crypto_{name} optional mido_runtime\n".encode()
        for name in units)
    flags = ("-DMIDO_BOOT_CRYPTO_DIAGNOSTIC=1 -mgeneral-regs-only -fno-stack-protector "
             "-fno-lto -I$(SRCROOT)/" + TARGET.as_posix())
    make_after = make_before + b"\n" + b"".join(
        f"mido_crypto_{Path(name).stem}.o_CFLAGS_ADD += {flags}\n".encode() for name in units)
    target.mkdir()
    for name, data in contents.items():
        (target / name).write_bytes(data)
    configuration.write_bytes(files_after)
    makefile.write_bytes(make_after)
    records = {str(TARGET / name).replace("\\", "/"):
               {"origin": origins[name], "sha256": hashlib.sha256(data).hexdigest()}
               for name, data in contents.items()}
    records.update({path.relative_to(source).as_posix():
                    {"before_sha256": hashlib.sha256(before).hexdigest(),
                     "sha256": hashlib.sha256(after).hexdigest()}
                    for path, before, after in ((configuration, files_before, files_after),
                                                (makefile, make_before, make_after))})
    return {"diagnostic_only": True, "complete_crypto_provider": False,
            "unsupported_operation_policy": "panic", "unsupported": list(UNSUPPORTED),
            "startup": "EARLY_BOOT/FIRST before kmem_crypto_init at MIDDLE",
            "bearssl_archive_sha256": ARCHIVE_SHA256, "units": len(units), "files": records,
            "provider_registration_executed": False, "boot_approved": False}
