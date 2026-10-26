"""Check actual Darwin KERNEL=1 provider compilation prerequisites, without building or booting XNU."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import struct
import sys

try:
    from tools.test_mido_drbg import ARCHIVE_SHA256, verify_dependency
except ModuleNotFoundError:
    from test_mido_drbg import ARCHIVE_SHA256, verify_dependency


UNITS = ("mido_prng_bridge.c", "mido_kmem_random.c", "mido_sha256.c", "mido_prng_lock.c", "mido_hmac_sha256.c", "mido_digest.c", "mido_hmac.c", "mido_aes_cbc.c", "mido_aes_ctr.c", "mido_aes_xts.c", "mido_aes_gcm.c", "mido_ccrng.c")
UNIT_PATHS = {name: "devices/mido/xnu/runtime/" + name for name in UNITS}
UNIT_PATHS.update({name: "devices/mido/xnu/early/" + name for name in ("drbg.c", "kernel_prng.c")})
UNIT_PATHS["mido_boot_crypto.c"] = "devices/mido/xnu/runtime/mido_boot_crypto.c"
UNIT_PATHS.update({name: "artifacts/bearssl-0.6/src/" + relative for name, relative in (
    ("sha2small.c", "hash/sha2small.c"), ("hmac.c", "mac/hmac.c"),
    ("hmac_drbg.c", "rand/hmac_drbg.c"), ("dec32be.c", "codec/dec32be.c"),
    ("enc32be.c", "codec/enc32be.c"), ("md5.c", "hash/md5.c"), ("sha1.c", "hash/sha1.c"),
    ("sha2big.c", "hash/sha2big.c"), ("dec64be.c", "codec/dec64be.c"), ("enc64be.c", "codec/enc64be.c"),
    ("dec32le.c", "codec/dec32le.c"), ("enc32le.c", "codec/enc32le.c"),
    ("aes_ct.c", "symcipher/aes_ct.c"), ("aes_ct_enc.c", "symcipher/aes_ct_enc.c"),
    ("aes_ct_dec.c", "symcipher/aes_ct_dec.c"), ("aes_ct_cbcenc.c", "symcipher/aes_ct_cbcenc.c"),
    ("aes_ct_cbcdec.c", "symcipher/aes_ct_cbcdec.c"), ("aes_ct_ctr.c", "symcipher/aes_ct_ctr.c"),
    ("gcm.c", "aead/gcm.c"), ("ghash_ctmul32.c", "hash/ghash_ctmul32.c"))})


def is_arm64_object_header(data):
    return (len(data) >= 32 and data[:4] == b"\xcf\xfa\xed\xfe" and
            struct.unpack_from("<III", data, 4) == (0x0100000C, 0, 1))


def command_for(workspace, compiler, name, sdk_root=None, source_root=None, object_root=None, object_output=None):
    if name not in UNIT_PATHS:
        raise ValueError("Unknown provider unit")
    source = source_root or workspace / "artifacts/mido-runtime-v3/source"
    command = [str(compiler), "--target=arm64-apple-ios16.6", "-mcpu=cortex-a53",
               "-ffreestanding", "-mgeneral-regs-only", "-fno-stack-protector",
               "-DKERNEL=1", "-DKERNEL_PRIVATE=1", "-DXNU_KERNEL_PRIVATE=1", "-D__APPLE_API_UNSTABLE=1",
               "-DARM64_BOARD_CONFIG_MIDO=1", "-DPRIVATE=1", "-DAPPLE=1",
               "-Wall", "-Wextra", "-Werror", "-fsyntax-only",
               str(workspace / UNIT_PATHS[name])]
    if object_output is not None:
        command.remove("-fsyntax-only")
        command += ["-O2", "-fno-builtin", "-c", "-o", str(object_output)]
    if name == "mido_boot_crypto.c":
        command += ["-DMIDO_BOOT_CRYPTO_DIAGNOSTIC=1",
                    "-I", str(workspace / "devices/mido/xnu/runtime")]
    if sdk_root is not None:
        command += ["-isysroot", str(sdk_root)]
    includes = [workspace / "devices/mido/xnu/early", workspace / "artifacts/bearssl-0.6/inc",
                workspace / "artifacts/bearssl-0.6/src",
                source / "EXTERNAL_HEADERS", source / "libkern", source / "bsd", source / "osfmk", source / "pexpert",
                workspace / "artifacts/mido-runtime-v3/generated/DEVELOPMENT/osfmk",
                workspace / "artifacts/mido-runtime-v3/generated/DEVELOPMENT/bsd"]
    if object_root is not None:
        includes = [object_root / "DEVELOPMENT_ARM64_MIDO/osfmk/DEVELOPMENT",
                    object_root / "DEVELOPMENT_ARM64_MIDO/bsd/DEVELOPMENT"] + [
                        object_root / "EXPORT_HDRS" / component
                        for component in ("osfmk", "bsd", "libkern", "pexpert", "iokit")] + includes
    return command + [item for include in includes for item in ("-I", str(include))]


def inspect(workspace, compiler, sdk_root=None, source_root=None, object_root=None, compile_directory=None):
    if sdk_root is not None and not sdk_root.is_dir():
        raise ValueError("SDK root is not an existing directory")
    verify_dependency(workspace / "artifacts/bearssl-0.6.tar.gz", workspace / "artifacts/bearssl-0.6")
    version = subprocess.run([str(compiler), "--version"], capture_output=True, text=True,
                             timeout=15, check=True).stdout
    records = []
    if compile_directory is not None:
        compile_directory.mkdir(parents=True, exist_ok=False)
    for name in UNIT_PATHS if compile_directory is not None else UNITS:
        object_output = compile_directory / (name + ".o") if compile_directory is not None else None
        command = command_for(workspace, compiler, name, sdk_root, source_root, object_root, object_output)
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        path = workspace / UNIT_PATHS[name]
        records.append(dict(unit=name, command=command, exit_code=result.returncode,
                            stdout=result.stdout, stderr=result.stderr,
                            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        if object_output is not None:
            data = object_output.read_bytes() if object_output.is_file() else b""
            valid = is_arm64_object_header(data)
            records[-1]["object"] = dict(path=str(object_output), bytes=len(data), valid_arm64_mach_o=valid,
                                         sha256=hashlib.sha256(data).hexdigest() if data else None)
    blockers = []
    if sdk_root is None:
        blockers.append("No explicit Apple SDK root supplied; SDK headers are not emulated or replaced.")
    if any(record["exit_code"] != 0 for record in records):
        blockers.append("Darwin KERNEL=1 syntax checks failed; inspect original compiler diagnostics.")
    if compile_directory is not None and any(not record["object"]["valid_arm64_mach_o"] for record in records):
        blockers.append("One or more genuine ARM64 Mach-O objects were not generated.")
    if sys.platform != "darwin":
        blockers.append("Existing full XNU build pipeline requires a real macOS host and xcrun.")
    source = source_root or workspace / "artifacts/mido-runtime-v3/source"
    abi_headers = sorted((source / "EXTERNAL_HEADERS/corecrypto").glob("*.h"))
    abi_headers += sorted((source / "libkern/libkern/crypto").glob("*.h"))
    if not abi_headers:
        blockers.append("Original crypto ABI headers were not found for provenance recording.")
    return dict(scope=__doc__, compiler_version=version, host_platform=sys.platform,
                dependency_archive_sha256=ARCHIVE_SHA256, dependency_tree_verified=True,
                abi_header_sha256={str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in abi_headers},
                sdk_root=str(sdk_root) if sdk_root is not None else None,
                units=records, blockers=blockers,
                kernel_syntax_passed=all(record["exit_code"] == 0 for record in records),
                kernel_objects_built=compile_directory is not None and not blockers,
                full_kernel_rebuilt=False, provider_registered=False, phone_accessed=False,
                github_action_dispatched_by_checker=False, boot_approved=False)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--sdk-root", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--object-root", type=Path)
    parser.add_argument("--compile-directory", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Refusing to overwrite existing evidence")
    workspace = Path(__file__).resolve().parents[1]
    report = inspect(workspace, args.compiler.resolve(), args.sdk_root.resolve() if args.sdk_root else None,
                     args.source_root.resolve() if args.source_root else None,
                     args.object_root.resolve() if args.object_root else None,
                     args.compile_directory.resolve() if args.compile_directory else None)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"report": str(output), "blockers": report["blockers"]}, indent=2))
    return 1 if report["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
