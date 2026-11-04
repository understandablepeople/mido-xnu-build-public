#!/usr/bin/env python3
"""Build and run fb_host_test.c against a patched xnu tree, then write PNGs.

usage: run_fb_test.py <patched-xnu-root> [outdir]
Needs ziglang on Windows, or a host C compiler on Linux.
The code under test is extracted from the patched tree, not copied.
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

W, H = 1080, 1920
root = os.path.abspath(sys.argv[1])
here = os.path.dirname(os.path.abspath(__file__))
out = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else here
os.makedirs(out, exist_ok=True)


def read(p):
    with open(os.path.join(root, p), newline="") as f:
        return f.read()


ps = read("pexpert/arm/pe_serial.c")
a = ps.index("static volatile uint8_t *fbcon_base;")
b = ps.index("SECURITY_READ_ONLY_LATE(static struct pe_serial_functions) mido_fbcon")
extract = "#define FBCON_SCALE 2\n" + ps[a:b]

tmp = tempfile.mkdtemp(prefix="fbtest_")
for d in ("arm64", "kern", os.path.join("pexpert", "arm64")):
    os.makedirs(os.path.join(tmp, d))
with open(os.path.join(tmp, "fbcon_extract.inc"), "w", newline="") as f:
    f.write(extract)
fbh = os.path.join(root, "osfmk/arm64/mido_fb.h")
shutil.copy(fbh, tmp)
shutil.copy(fbh, os.path.join(tmp, "arm64"))
shutil.copy(os.path.join(root, "osfmk/arm64/mido_early.h"), os.path.join(tmp, "arm64"))
# Only change to the code under test: the ARM barrier instruction does not assemble on the host.
with open(os.path.join(tmp, "mido_early.c"), "w", newline="") as f:
    f.write(read("osfmk/arm64/mido_early.c").replace('"dsb sy"', '""'))
shutil.copy(os.path.join(root, "osfmk/console/iso_font.c"), tmp)
with open(os.path.join(tmp, "pexpert", "arm64", "board_config.h"), "w") as f:
    f.write("#define MIDO 1\n")
with open(os.path.join(tmp, "kern", "misc_protos.h"), "w") as f:
    f.write("#include <stdarg.h>\nint _doprnt(const char *, va_list *, void (*)(char), int);\n")

exe = os.path.join(tmp, "t.exe" if os.name == "nt" else "t")
compiler = [sys.executable, "-m", "ziglang", "cc"] if os.name == "nt" else [os.environ.get("CC", "cc")]
subprocess.check_call(compiler + ["-std=gnu11", "-Wall", "-Wextra",
                       "-Wno-unused-function", "-Wno-unused-parameter", "-I", tmp,
                       os.path.join(here, "fb_host_test.c"), "-o", exe], cwd=tmp)
r = subprocess.run([exe, out], cwd=tmp)


def png(path, raw):
    rows = []
    for y in range(H):
        line = raw[y * W * 3:(y + 1) * W * 3]
        rgb = bytearray(len(line))
        rgb[0::3] = line[2::3]   # memory order is B,G,R; PNG wants R,G,B
        rgb[1::3] = line[1::3]
        rgb[2::3] = line[0::3]
        rows.append(b"\x00" + bytes(rgb))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)

    data = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(data)


for n in ("fb_dump", "fb_early_dump"):
    p = os.path.join(out, n + ".bgr")
    if os.path.exists(p):
        with open(p, "rb") as f:
            png(os.path.join(out, n + ".png"), f.read())
        os.remove(p)
shutil.rmtree(tmp, ignore_errors=True)
sys.exit(r.returncode)
