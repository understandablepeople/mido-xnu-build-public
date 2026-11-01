#!/usr/bin/env python3
"""Build the mido XNU shim with the NDK clang, optionally package an lk2nd image.

  python -I mido/shim/build.py OUTDIR [--payload PAYLOAD] [--reference-dtb DTB] [--ndk DIR]

OUTDIR must not exist (nothing is overwritten). Produces OUTDIR/shim.elf,
shim.bin (the arm64 Image), disassembly.txt and, with --payload,
OUTDIR/package/mido-xnu-shim.img. Prints sha256 of every artifact.
Host only: no adb, no fastboot, no device access.
"""
import argparse, hashlib, os, subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / "tools"))
DEFAULT_NDK = Path(os.environ.get("LOCALAPPDATA", "")) / "Android/Sdk/ndk/28.2.13676358"
COMMON = ["--target=aarch64-none-elf", "-march=armv8-a", "-mgeneral-regs-only", "-mstrict-align",
          "-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-fno-unwind-tables",
          "-fno-asynchronous-unwind-tables", "-fpie", "-fvisibility=hidden", "-O2",
          "-Wall", "-Wextra", "-Werror"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        sys.exit(f"command failed: {cmd[0]}\n{r.stdout}{r.stderr}")
    return r.stdout


def build(out, ndk=DEFAULT_NDK, payload=None, reference=None):
    out = Path(out)
    bin_dir = Path(ndk) / "toolchains/llvm/prebuilt/windows-x86_64/bin"
    tool = {n: bin_dir / (n + (".exe" if (bin_dir / (n + ".exe")).exists() else "")) for n in
            ("clang", "ld.lld", "llvm-objcopy", "llvm-objdump", "llvm-readelf")}
    for t in tool.values():
        if not t.exists():
            sys.exit(f"missing NDK tool: {t}")
    if out.exists():
        sys.exit("output exists; refusing to overwrite")
    out.mkdir(parents=True)
    run([tool["clang"], "--target=aarch64-none-elf", "-march=armv8-a", "-c", HERE / "entry.S", "-o", out / "entry.o"])
    run([tool["clang"], *COMMON, "-std=c11", "-I", HERE, "-c", HERE / "shim.c", "-o", out / "shim.o"])
    elf, binary = out / "shim.elf", out / "shim.bin"
    run([tool["ld.lld"], "-static", "--no-undefined", "--build-id=none", "-T", HERE / "link.ld",
         out / "entry.o", out / "shim.o", "-o", elf])
    # No relocations may survive: lk2nd copies the Image to 0x10080000 and jumps, nobody relocates it.
    rel = run([tool["llvm-readelf"], "-r", elf])
    if "R_AARCH64" in rel:
        sys.exit("relocations present in the linked shim:\n" + rel)
    (out / "disassembly.txt").write_text(run([tool["llvm-objdump"], "-d", elf]), encoding="utf-8")
    run([tool["llvm-objcopy"], "-O", "binary", elf, binary])
    print(f"shim.bin  {binary.stat().st_size} bytes  sha256 {sha(binary)}")
    print(f"shim.elf  sha256 {sha(elf)}")
    if payload:
        import pack_mido_boot
        report = pack_mido_boot.package(binary, payload, out / "package", reference)
        img = out / "package/mido-xnu-shim.img"
        print(f"image     {img.stat().st_size} bytes  sha256 {sha(img)}")
        print(f"payload   sha256 {report['payload_sha256']}")
    print("Host build only. No device access. NOT validated on hardware.")
    return binary


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--payload")
    ap.add_argument("--reference-dtb")
    ap.add_argument("--ndk", default=str(DEFAULT_NDK))
    a = ap.parse_args()
    build(a.out, a.ndk, a.payload, a.reference_dtb)
