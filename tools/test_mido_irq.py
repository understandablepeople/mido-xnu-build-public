"""Build and execute host C register-model tests; cross-compile ARM64 only."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--linker", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parent.parent
    output = args.output_directory.resolve()
    artifacts = (workspace / "artifacts").resolve()
    if sys.platform != "win32" or not output.is_relative_to(artifacts) or output == artifacts:
        parser.error("requires Windows and a new directory under workspace artifacts")
    if output.exists():
        parser.error("output exists; choose a new directory")
    output.mkdir(parents=True)
    source = workspace / "devices/mido/xnu/early"
    common = ["-ffreestanding", "-fno-builtin", "-fno-stack-protector", "-O2", "-Wall", "-Wextra", "-Werror", "-std=c11"]
    model_object = output / "model.obj"
    subprocess.run([str(args.compiler), "-target", "x86_64-pc-windows-msvc", *common,
                    "-c", str(source / "irq_timer.c"), "-o", str(model_object)], check=True, timeout=60)
    library = output / "model.dll"
    exports = ["mido_gic_attach", "mido_gic_take", "mido_gic_finish", "mido_timer_arm_delta", "mido_timer_stop",
               "mido_gic_prepare_virtual_timer", "mido_gic_dispatch_timer",
               "mido_gic_prepare_self_sgi", "mido_gic_send_self_sgi", "mido_gic_dispatch_timer_or_signal"]
    subprocess.run([str(args.linker), "-flavor", "link", "/dll", "/noentry", "/nodefaultlib",
                    f"/out:{library}", *[f"/export:{name}" for name in exports], str(model_object)], check=True, timeout=60)
    for filename in ("irq_timer.c", "arm64_timer.c"):
        subprocess.run([str(args.compiler), "-target", "aarch64-none-elf", "-mcpu=cortex-a53",
                        "-march=armv8-a", "-mstrict-align", "-mgeneral-regs-only", *common,
                        "-S", str(source / filename), "-o", str(output / f"{Path(filename).stem}.s")],
                       check=True, timeout=60)
    result = subprocess.run([sys.executable, str(workspace / "tests/early_irq_cases.py"), "--library", str(library)],
                            capture_output=True, text=True, timeout=60)
    (output / "tests.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    print(result.stdout + result.stderr)
    report = {
        "purpose": "native x86_64 C with mock registers; ARM64 cross-compilation only",
        "tests_exit": result.returncode,
        "sources_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(source.iterdir()) if path.is_file()},
        "harness_sha256": hashlib.sha256((workspace / "tests/early_irq_cases.py").read_bytes()).hexdigest(),
        "model_library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
        "hardware_executed": False,
        "kernel_integrated": False,
        "boot_approved": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
