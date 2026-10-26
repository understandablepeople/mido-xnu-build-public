"""Compile layout assertions against a pinned Apple header; no device access."""

import argparse
import hashlib
from pathlib import Path
import subprocess
import tempfile
import urllib.request


SOURCE_COMMIT = "1b191cb58250d0705d8a51287127505aa4bc0789"
HEADER_URL = f"https://raw.githubusercontent.com/apple-oss-distributions/xnu/{SOURCE_COMMIT}/pexpert/pexpert/arm64/boot.h"
HEADER_SHA256 = "efdfec46319cb147297682a8faebe02873f845261b57f7511ab8e15c13ef3439"
FIELD_OFFSETS = {
    "Revision": 0,
    "Version": 2,
    "virtBase": 8,
    "physBase": 16,
    "memSize": 24,
    "topOfKernelData": 32,
    "Video": 40,
    "machineType": 88,
    "deviceTreeP": 96,
    "deviceTreeLength": 104,
    "CommandLine": 108,
    "bootFlags": 720,
    "memSizeActual": 728,
}


def assertion_source():
    declarations = [
        "typedef __UINT16_TYPE__ uint16_t;",
        "typedef __UINT32_TYPE__ uint32_t;",
        "typedef __UINT64_TYPE__ uint64_t;",
        '#include "boot.h"',
        '_Static_assert(sizeof(unsigned long) == 8, "LP64 unsigned long");',
        '_Static_assert(sizeof(void *) == 8, "64-bit pointers");',
        '_Static_assert(sizeof(Boot_Video) == 48, "Boot_Video size");',
        '_Static_assert(sizeof(boot_args) == 736, "boot_args size");',
        '_Static_assert(_Alignof(boot_args) == 8, "boot_args alignment");',
        '_Static_assert(BOOT_LINE_LENGTH == 608, "command line length");',
    ]
    declarations.extend(
        f'_Static_assert(__builtin_offsetof(boot_args, {field}) == {offset}, "{field} offset");'
        for field, offset in FIELD_OFFSETS.items()
    )
    return "\n".join(declarations) + "\n"


def check_header(header, compiler):
    if hashlib.sha256(header).hexdigest() != HEADER_SHA256:
        raise ValueError("Apple boot.h hash mismatch; refusing to compile")
    with tempfile.TemporaryDirectory(prefix="mido-xnu-abi-") as temporary:
        root = Path(temporary)
        includes = root / "pexpert" / "arm"
        includes.mkdir(parents=True)
        for filename in ("consistent_debug.h", "protos.h"):
            (includes / filename).write_bytes(b"")
        (root / "boot.h").write_bytes(header)
        source = root / "layout.c"
        source.write_text(assertion_source(), encoding="utf-8")
        subprocess.run(
            [str(compiler), "-target", "arm64-apple-macos13.0", "-std=c11",
             "-fsyntax-only", "-nostdinc", "-Wall", "-Wextra", "-Werror",
             "-I", str(root), str(source)],
            check=True, timeout=60,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", required=True, type=Path)
    parser.add_argument("--header", type=Path, help="use a local copy instead of downloading the pinned header")
    args = parser.parse_args()
    if args.header:
        header = args.header.read_bytes()
    else:
        with urllib.request.urlopen(HEADER_URL, timeout=30) as response:
            header = response.read(65537)
        if len(header) > 65536:
            parser.error("header download exceeded the size limit")
    check_header(header, args.compiler)
    print(f"PASS: Apple {SOURCE_COMMIT} boot_args: size 736, alignment 8, {len(FIELD_OFFSETS)} offsets")
    print("Header layout only. Dependency headers are empty stubs; no kernel build, pointer-semantics audit or boot approval.")


if __name__ == "__main__":
    main()
