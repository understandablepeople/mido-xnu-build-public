"""Compile the independent read-only RTC backend and run register-model tests."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(workspace / "artifacts") or output == workspace / "artifacts" or output.exists():
        parser.error("output must be a new directory under workspace artifacts")
    output.mkdir(parents=True)
    compiler, linker = args.toolchain / "clang.exe", args.toolchain / "ld.lld.exe"
    source = workspace / "devices/mido/xnu/early/pmic_rtc.c"
    flags = ["-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-O2", "-Wall", "-Wextra", "-Werror", "-std=c11"]
    subprocess.run([str(compiler), "-target", "x86_64-pc-windows-msvc", *flags, "-c", str(source), "-o", str(output / "rtc.obj")], check=True, timeout=60)
    library = output / "rtc.dll"
    subprocess.run([str(linker), "-flavor", "link", "/dll", "/noentry", "/nodefaultlib", f"/out:{library}",
                    "/export:mido_pmic_rtc_attach", "/export:mido_pmic_rtc_seconds", "/export:mido_pmic_rtc_discover", str(output / "rtc.obj")], check=True, timeout=60)
    subprocess.run([str(compiler), "-target", "aarch64-none-elf", "-mcpu=cortex-a53", "-march=armv8-a", "-mstrict-align", "-mgeneral-regs-only", *flags,
                    "-S", str(source), "-o", str(output / "rtc-arm64.s")], check=True, timeout=60)
    result = subprocess.run([sys.executable, "-X", "utf8", str(workspace / "tests/pmic_rtc_cases.py"), "--library", str(library)], capture_output=True, timeout=60)
    (output / "tests.log").write_bytes(result.stdout + result.stderr)
    report = dict(scope="host C register model and Cortex-A53 cross-compilation only", tests_exit=result.returncode,
                  source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  header_sha256=hashlib.sha256(source.with_suffix(".h").read_bytes()).hexdigest(),
                  harness_sha256=hashlib.sha256((workspace / "tests/pmic_rtc_cases.py").read_bytes()).hexdigest(),
                  device_commands_executed=False, hardware_verified=False, kernel_integrated=False)
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print((result.stdout + result.stderr).decode("utf-8", errors="replace"))
    raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
