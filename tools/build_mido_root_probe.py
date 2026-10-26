"""Build an unsigned freestanding diagnostic Mach-O, never an installation image."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess


TEXT_BASE = 0x100000000
TEXT_OFFSET = 0x4000
FILE_SIZE = 0x8000


def executable(code):
    if not code or len(code) > 4096 or len(code) % 4:
        raise ValueError("expected bounded aligned ARM64 instructions")
    pagezero = struct.pack("<II16sQQQQiiII", 0x19, 72, b"__PAGEZERO", 0, TEXT_BASE, 0, 0, 0, 0, 0, 0)
    text = struct.pack("<II16sQQQQiiII", 0x19, 152, b"__TEXT", TEXT_BASE, FILE_SIZE,
                       0, FILE_SIZE, 5, 5, 1, 0)
    text += struct.pack("<16s16sQQIIIIIIII", b"__text", b"__TEXT", TEXT_BASE + TEXT_OFFSET,
                        len(code), TEXT_OFFSET, 2, 0, 0, 0x80000400, 0, 0, 0)
    state = bytearray(272)
    struct.pack_into("<Q", state, 256, TEXT_BASE + TEXT_OFFSET)
    thread = struct.pack("<4I", 5, 288, 6, 68) + state
    platform = struct.pack("<6I", 0x32, 24, 2, 16 << 16, (17 << 16) | (5 << 8), 0)
    commands = pagezero + text + thread + platform
    header = struct.pack("<8I", 0xFEEDFACF, 0x0100000C, 0, 2, 4, len(commands), 1, 0)
    result = bytearray(FILE_SIZE)
    result[:len(header + commands)] = header + commands
    result[TEXT_OFFSET:TEXT_OFFSET + len(code)] = code
    return bytes(result)


def build(toolchain, output):
    workspace = Path(__file__).resolve().parent.parent
    output = output.resolve()
    if not output.is_relative_to((workspace / "artifacts").resolve()) or output.exists():
        raise ValueError("output must be a new directory under artifacts")
    source = workspace / "devices/mido/xnu/userspace/root_probe.S"
    compiler = toolchain / "clang.exe"
    objcopy = toolchain / "llvm-objcopy.exe"
    if not compiler.is_file() or not objcopy.is_file():
        raise ValueError("explicit Windows LLVM assembler and objcopy are required")
    output.mkdir(parents=True)
    commands = [[str(compiler), "--target=arm64-apple-ios16.0", "-march=armv8-a",
                 "-ffreestanding", "-c", str(source), "-o", str(output / "root_probe.o")],
                [str(objcopy), "--dump-section", "__TEXT,__text=" + str(output / "text.bin"),
                 str(output / "root_probe.o")]]
    for command in commands:
        subprocess.run(command, check=True, timeout=30)
    code = (output / "text.bin").read_bytes()
    payload = executable(code)
    (output / "root_probe.macho").write_bytes(payload)
    report = dict(purpose="single-executable diagnostic root payload, not Apple launchd",
                  bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest(),
                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  code_sha256=hashlib.sha256(code).hexdigest(), commands=commands,
                  entry=TEXT_BASE + TEXT_OFFSET, dynamic_linker_required=False,
                  signed=False, loaded_by_xnu=False, executed=False, boot_approved=False)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.toolchain, args.output), indent=2))


if __name__ == "__main__":
    main()
