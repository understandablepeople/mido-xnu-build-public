"""Apply a pinned XNU architecture scaffold and compile host-only probes."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import urllib.request


SOURCE_COMMIT = "1b191cb58250d0705d8a51287127505aa4bc0789"
SOURCE_HASHES = {
    "makedefs/MakeInc.def": "3574d6e9ca26f05fd7f88cb675eaabeb28804a9bc6b7f10b592df5a4f13580a9",
    "pexpert/pexpert/arm64/board_config.h": "1de4d28c9f2896dadbe0e1a430a9b2cea463817dd13523f03583a3a4c3edaab9",
    "osfmk/arm64/proc_reg.h": "129f4d42d97c8c403dd83ebbb99bb7ccc3954adfcbb9621bcf08f8f8b218b33b",
}


def validate_sources(sources):
    if set(sources) != set(SOURCE_HASHES):
        raise ValueError("unexpected source file set")
    for path, expected in SOURCE_HASHES.items():
        if hashlib.sha256(sources[path]).hexdigest() != expected:
            raise ValueError(f"source hash mismatch: {path}")


def machine_flags(text):
    matches = [line.split("=", 1)[1].strip() for line in text.splitlines()
               if line.startswith("MACHINE_FLAGS_ARM64_MIDO =")]
    if len(matches) != 1:
        raise ValueError("expected exactly one MIDO machine flags definition")
    flags = shlex.split(matches[0])
    expected = ["-DARM64_BOARD_CONFIG_MIDO", "-mcpu=cortex-a53", "-march=armv8-a", "-mstrict-align"]
    if flags != expected:
        raise ValueError("MIDO flags differ from the reviewed baseline")
    return flags


def download_sources():
    sources = {}
    for path in SOURCE_HASHES:
        url = f"https://raw.githubusercontent.com/apple-oss-distributions/xnu/{SOURCE_COMMIT}/{path}"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(1048577)
        if len(data) > 1048576:
            raise ValueError(f"source exceeds size limit: {path}")
        sources[path] = data
    validate_sources(sources)
    return sources


def check(compiler, output):
    workspace = Path(__file__).resolve().parent.parent
    output = output.resolve()
    artifact_root = (workspace / "artifacts").resolve()
    if not output.is_relative_to(artifact_root) or output == artifact_root:
        raise ValueError("output must be a new directory under workspace artifacts")
    if output.exists():
        raise ValueError("output already exists; choose a new directory")
    sources = download_sources()
    output.mkdir(parents=True)
    root = output / "source"
    root.mkdir()
    for path, data in sources.items():
        destination = root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    patch = workspace / "devices/mido/xnu/patches/0001-mido-architecture-scaffold.patch"
    environment = os.environ.copy()
    environment["GIT_CEILING_DIRECTORIES"] = str(output)
    for options in (["--check"], []):
        subprocess.run(["git", "-C", str(root), "apply", *options, "--whitespace=error", str(patch)],
                       check=True, env=environment, timeout=30)
    flags = machine_flags((root / "makedefs/MakeInc.def").read_text(encoding="utf-8"))
    stub = root / "stubs/mach/machine.h"
    stub.parent.mkdir(parents=True)
    stub.write_bytes(b"")
    probe = workspace / "devices/mido/xnu/config-probe.c"
    command = [str(compiler), "-target", "arm64-apple-macos13.0", *flags,
               "-DASSEMBLER=1", "-ffreestanding", "-fno-builtin", "-fno-stack-protector",
               "-nostdinc", "-std=c11", "-Wall", "-Wextra", "-Werror",
               "-I", str(root / "pexpert"), "-I", str(root / "osfmk"), "-I", str(root / "stubs")]
    scenarios = {
        "baseline": ([], None),
        "arm64e-rejected": (["-D__arm64e__=1"], "without PAC or LSE"),
        "lse-rejected": (["-D__ARM_FEATURE_ATOMICS=1"], "without PAC or LSE"),
        "armv85-rejected": (["-mcpu=apple-a14", "-march=armv8.5-a"], "without PAC or LSE"),
        "pauth-rejected": (["-D__ARM_FEATURE_PAUTH=1"], "without PAC or LSE"),
        "16kb-rejected": (["-D__ARM_16K_PG__=1"], "4KB page path"),
        "16kb-zero-rejected": (["-D__ARM_16K_PG__=0"], "4KB page path"),
        "apple-monitor-rejected": (["-DXNU_MONITOR=1"], "must not be enabled"),
    }
    results = {}
    for name, (extra, expected_error) in scenarios.items():
        destination = output / f"{name}.s"
        result = subprocess.run([*command, *extra, "-S", str(probe), "-o", str(destination)],
                                capture_output=True, text=True, timeout=60)
        (output / f"{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        if expected_error is None:
            passed = result.returncode == 0
        else:
            passed = result.returncode != 0 and expected_error in result.stderr
        results[name] = {"passed": passed, "compiler_exit": result.returncode}
        if not passed:
            print(
                f"FAIL: {name}, compiler exit {result.returncode}, extra flags {extra}, "
                f"expected error {expected_error!r}\n{result.stdout}{result.stderr}",
                flush=True,
            )
    report = {
        "purpose": "architecture scaffold checks, NOT a kernel build or boot approval",
        "source_commit": SOURCE_COMMIT,
        "source_sha256": SOURCE_HASHES,
        "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
        "probe_sha256": hashlib.sha256(probe.read_bytes()).hexdigest(),
        "machine_flags": flags,
        "scenarios": results,
        "limitations": ["mach/machine.h is an empty stub", "ASSEMBLER excludes C-only header declarations",
                        "make configuration is not evaluated", "no linked kernel or platform backend"],
        "boot_approved": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not all(result["passed"] for result in results.values()):
        raise ValueError(f"configuration checks failed; inspect {output}")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.compiler, args.output_directory), indent=2))


if __name__ == "__main__":
    main()
