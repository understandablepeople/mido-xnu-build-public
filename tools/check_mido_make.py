"""Evaluate pinned XNU make definitions only; never invoke kernel recipes."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import urllib.request

try:
    from tools.check_mido_config import SOURCE_COMMIT, SOURCE_HASHES as ARCH_HASHES
except ModuleNotFoundError:
    from check_mido_config import SOURCE_COMMIT, SOURCE_HASHES as ARCH_HASHES


SOURCE_HASHES = {
    **ARCH_HASHES,
    "makedefs/MakeInc.cmd": "4bb6b5aec167b8a41ff19615714f11300e79be7710def4b7d2da5be61a189509",
    "makedefs/MakeInc.kernel": "4c2208998504454e18acfd56dae2810e69b1c912606df6a35c11e4c2e7f17937",
}
VARIABLES = (
    "SUPPORTED_ARM64_MACHINE_CONFIGS", "ARCH_STRING_FOR_CURRENT_MACHINE_CONFIG",
    "ARCH_FLAGS_ARM64", "MACHINE_FLAGS_ARM64_MIDO", "CFLAGS", "SFLAGS",
    "KERNEL_FILE_NAME", "LARGE_MEMORY_DEFINE", "ARM64_LINK_ADDR", "BUILD_STATIC_LINK",
)
PREFIX = "MIDO_MAKE_PROBE:"
PROBE = """CURRENT_ARCH_CONFIG = ARM64
CURRENT_ARCH_CONFIG_LC = arm64
CURRENT_MACHINE_CONFIG = MIDO
CURRENT_MACHINE_CONFIG_LC = mido
RC_ProjectName = xnu
BOUND_CHECKS = 0
CC = false
BUILD_LTO = 0
OBJROOT = probe-obj
TARGET = probe-obj/target
DSTROOT = probe-dst
SYMROOT = probe-symbols
include platform-vars.mk
include source/makedefs/MakeInc.def
include source/makedefs/MakeInc.kernel
""" + "".join(f"$(info {PREFIX}{name}=$(strip $({name})))\n" for name in VARIABLES) + """
.PHONY: mido-config-probe
mido-config-probe:
"""


def validate_sources(sources):
    if set(sources) != set(SOURCE_HASHES):
        raise ValueError("unexpected make source file set")
    for path, expected in SOURCE_HASHES.items():
        if hashlib.sha256(sources[path]).hexdigest() != expected:
            raise ValueError(f"source hash mismatch: {path}")


def platform_definitions(text):
    names = ("SUPPORTED_EMBEDDED_PLATFORMS", "SUPPORTED_SIMULATOR_PLATFORMS", "SUPPORTED_PLATFORMS")
    definitions = []
    for name in names:
        lines = [line for line in text.splitlines() if line.startswith(name + " := ")]
        if len(lines) != 1:
            raise ValueError("unexpected platform definitions")
        definitions.append(lines[0])
    return "\n".join(definitions) + "\n"


def parse_values(text):
    result = {}
    for line in text.splitlines():
        if line.startswith(PREFIX):
            name, separator, value = line[len(PREFIX):].partition("=")
            if not separator or name not in VARIABLES or name in result:
                raise ValueError("unexpected or duplicate probe variable")
            result[name] = value
    if set(result) != set(VARIABLES):
        raise ValueError("incomplete make probe output")
    return result


def validate_values(values, config, platform):
    if config not in ("DEVELOPMENT", "DEBUG") or platform not in ("MacOSX", "iPhoneOS"):
        raise ValueError("unsupported probe scenario")
    if "MIDO" not in values["SUPPORTED_ARM64_MACHINE_CONFIGS"].split():
        raise ValueError("MIDO is not registered")
    if values["ARCH_STRING_FOR_CURRENT_MACHINE_CONFIG"] != "arm64" or values["ARCH_FLAGS_ARM64"] != "-arch arm64":
        raise ValueError("MIDO must select arm64, not arm64e")
    machine = ["-DARM64_BOARD_CONFIG_MIDO", "-mcpu=cortex-a53", "-march=armv8-a", "-mstrict-align"]
    if shlex.split(values["MACHINE_FLAGS_ARM64_MIDO"]) != machine:
        raise ValueError("unexpected MIDO machine flags")
    for variable in ("CFLAGS", "SFLAGS"):
        flags = shlex.split(values[variable])
        if any(flags.count(flag) != 1 for flag in machine):
            raise ValueError(f"{variable}: missing or duplicated MIDO flags")
        if flags.count("-arch") != 1 or flags[flags.index("-arch") + 1:flags.index("-arch") + 2] != ["arm64"]:
            raise ValueError(f"{variable}: unexpected architecture")
        if any(flag.startswith(("-mcpu=", "-march=", "-DARM64_BOARD_CONFIG_")) and flag not in machine for flag in flags):
            raise ValueError(f"{variable}: conflicting CPU, ISA or board flags")
        if any(flag in flags for flag in ("-D__ARM_16K_PG__", "-D__ARM_16K_PG__=1", "-D__ARM_16K_PG__=0", "-mbranch-protection=standard")):
            raise ValueError(f"{variable}: unreviewed page or branch-protection flags")
    if values["BUILD_STATIC_LINK"] != "1":
        raise ValueError("expected the upstream static-link path")
    prefix = "kernel" if platform == "MacOSX" else "mach"
    expected_name = f"{prefix}.{config.lower()}.mido"
    if values["KERNEL_FILE_NAME"] != expected_name:
        raise ValueError("unexpected kernel output name")
    expected_memory = "-DARM_LARGE_MEMORY=1" if platform == "MacOSX" else "-UARM_LARGE_MEMORY"
    if values["LARGE_MEMORY_DEFINE"] != expected_memory:
        raise ValueError("unexpected platform memory definition")
    expected_link = "0xfffffe0007004000" if platform == "MacOSX" else "0xfffffff007004000"
    if values["ARM64_LINK_ADDR"] != expected_link:
        raise ValueError("unexpected platform link address")
    for variable in ("CFLAGS", "SFLAGS"):
        flags = shlex.split(values[variable])
        if expected_memory not in flags or f"-DVM_KERNEL_LINK_ADDRESS={expected_link}" not in flags:
            raise ValueError(f"{variable}: platform memory settings were not propagated")
    return {
        "variables": values,
        "platform_memory_review_required": True,
        "sdk_and_kernel_compile_verified": False,
    }


def check(make, output):
    workspace = Path(__file__).resolve().parent.parent
    output = output.resolve()
    artifacts = (workspace / "artifacts").resolve()
    if output == artifacts or not output.is_relative_to(artifacts) or output.exists():
        raise ValueError("output must be a new directory under workspace artifacts")
    version = subprocess.run([str(make.resolve()), "--version"], capture_output=True, text=True, check=True, timeout=15)
    if not version.stdout.startswith("GNU Make "):
        raise ValueError("GNU Make is required")
    sources = {}
    for path in SOURCE_HASHES:
        url = f"https://raw.githubusercontent.com/apple-oss-distributions/xnu/{SOURCE_COMMIT}/{path}"
        with urllib.request.urlopen(url, timeout=30) as response:
            sources[path] = response.read(1048577)
    validate_sources(sources)
    output.mkdir(parents=True)
    source = output / "source"
    source.mkdir()
    for path, data in sources.items():
        destination = source / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    patch = workspace / "devices/mido/xnu/patches/0001-mido-architecture-scaffold.patch"
    environment = os.environ.copy()
    environment["GIT_CEILING_DIRECTORIES"] = str(output)
    for name in ("MAKEFLAGS", "GNUMAKEFLAGS", "MFLAGS", "MAKEFILES"):
        environment.pop(name, None)
    for options in (["--check"], []):
        subprocess.run(["git", "-C", str(source), "apply", *options, "--whitespace=error", str(patch)],
                       env=environment, check=True, timeout=30)
    (output / "probe.mk").write_text(PROBE, encoding="utf-8", newline="\n")
    (output / "platform-vars.mk").write_text(platform_definitions(sources["makedefs/MakeInc.cmd"].decode("utf-8")),
                                            encoding="utf-8", newline="\n")
    results = {}
    for config in ("DEVELOPMENT", "DEBUG"):
        for platform in ("MacOSX", "iPhoneOS"):
            name = f"{config}-{platform}"
            command = [str(make.resolve()), "--no-print-directory", "--no-builtin-rules", "--no-builtin-variables",
                       "--just-print", "-f", "probe.mk", f"CURRENT_KERNEL_CONFIG={config}",
                       f"CURRENT_KERNEL_CONFIG_LC={config.lower()}", f"PLATFORM={platform}", "mido-config-probe"]
            result = subprocess.run(command, cwd=output, env=environment, capture_output=True, text=True, timeout=30)
            (output / f"{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
            if result.returncode or result.stderr.strip():
                raise ValueError(f"make probe failed: {name}: {result.stderr}")
            results[name] = validate_values(parse_values(result.stdout), config, platform)
    report = {
        "purpose": "real GNU Make evaluation of two XNU includes, NOT the top-level build",
        "source_commit": SOURCE_COMMIT, "source_sha256": SOURCE_HASHES,
        "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
        "probe_sha256": hashlib.sha256(PROBE.encode()).hexdigest(),
        "make_version": version.stdout.splitlines()[0], "scenarios": results,
        "limitations": ["only three declarative platform lines from MakeInc.cmd; no SDK discovery or top-level recursion",
                        "bounds-attributes detection disabled",
                        "no doconf/config compiler or generated headers", "no kernel recipe execution or hardware access"],
        "boot_approved": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--make", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.make, args.output_directory), indent=2))


if __name__ == "__main__":
    main()
