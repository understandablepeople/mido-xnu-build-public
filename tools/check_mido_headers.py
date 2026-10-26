"""Build Apple's config utility on Windows and generate real osfmk headers."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

try:
    from tools.check_mido_config import SOURCE_COMMIT
    from tools.check_mido_master import check as check_master
except ModuleNotFoundError:
    from check_mido_config import SOURCE_COMMIT
    from check_mido_master import check as check_master


SOURCE_HASHES = {
    "SETUP/config/config.h": "64bac639b468ed3b19df4294882bdcb41afbfc45dd9da8a1b72b08dd00ed1b7b",
    "SETUP/config/externs.c": "af0ae69555064ffb44ac4b4e8155c50ec8763c4f189f1c746946fa0088b3af8f",
    "SETUP/config/main.c": "8e5f8662226a973267833c1406cb9cc1158b809607438f5909683d1590231771",
    "SETUP/config/mkheaders.c": "69492dabd46af3fb947fb5a26258788118c6501a22344880089e0d31ad6c38f0",
    "SETUP/config/mkioconf.c": "0682391b8a9e6ccefd899df7ade7277178e6efe8b3493672f34a7c873d418f6f",
    "SETUP/config/mkmakefile.c": "85b7f26db74397b8772ec9c9894df7f4b30fd8eb4c43b11c8e22f71d287002ff",
    "SETUP/config/openp.c": "43c4f4c7a6b5f3ffe62ab3d9557a758a9f563561bc0c72bb28bcf96cf7e7dd32",
    "SETUP/config/searchp.c": "7360ba7863e536db014fdece11101c2f9dba9901958008f63109be8680f9a4c7",
    "SETUP/config/lexer.l": "6c6a306091a7f40425751e11310624afc41d523bb4ea62504b278902a3111e85",
    "SETUP/config/parser.y": "b8672477a33d2dd24170844867b3195afb0e1629f905912ede6d6e5309559cf9",
    "osfmk/conf/files": "1e4d676564f5a2cfa6dc2fadd22a034ad9ca4ed267a082e0f4b236f0c2fbe7b6",
    "osfmk/conf/files.arm64": "6f7cff536fd02ad8f34c037d980a0d1cace352fec4ced04fad4234bbca5eb5a9",
    "osfmk/conf/Makefile.template": "957a11c58d2ed0c46f98fafe62f1ec9a390707614927b42fd88b942e7f43a802",
    "osfmk/conf/Makefile.arm64": "c1ca82021d8381695ead6f5d34318ad8f266f5192bafa4c50223ca11b27c388e",
}
ESSENTIAL_SOURCES = ("osfmk/arm64/start.s", "osfmk/arm/arm_init.c",
                     "osfmk/arm64/arm_vm_init.c", "osfmk/arm/pmap/pmap.c",
                     "osfmk/ipc/ipc_importance.c", "osfmk/kern/priority.c",
                     "osfmk/kern/thread.c", "osfmk/kern/sched_dualq.c",
                     "osfmk/kern/telemetry.c", "osfmk/atm/atm.c", "osfmk/vm/vm_tests.c",
                     "osfmk/kdp/kdp.c", "osfmk/kdp/kdp_udp.c", "osfmk/kdp/user_core.c",
                     "osfmk/kdp/ml/arm/kdp_machdep.c")


def validate_sources(sources):
    if set(sources) != set(SOURCE_HASHES):
        raise ValueError("unexpected config utility source set")
    for path, expected in SOURCE_HASHES.items():
        if hashlib.sha256(sources[path]).hexdigest() != expected:
            raise ValueError(f"source hash mismatch: {path}")


def verify_generated(directory, config):
    if config not in ("DEVELOPMENT", "DEBUG"):
        raise ValueError("unsupported configuration")
    expected = {"mach_assert.h": ("MACH_ASSERT", 1),
                "mach_ldebug.h": ("MACH_LDEBUG", int(config == "DEBUG")),
                "mach_vm_debug.h": ("MACH_VM_DEBUG", int(config == "DEBUG")),
                "debug.h": ("DEBUG", int(config == "DEBUG")),
                "importance_inheritance.h": ("IMPORTANCE_INHERITANCE", 1),
                "config_dtrace.h": ("CONFIG_DTRACE", 1), "mach_kdp.h": ("MACH_KDP", 1)}
    for filename, (name, value) in expected.items():
        text = (directory / filename).read_text(encoding="utf-8")
        if not re.fullmatch(rf"#define\s+{name}\s+{value}\s*", text):
            raise ValueError(f"unexpected generated header: {filename}")
    makefile = (directory / "Makefile").read_text(encoding="utf-8")
    sources = set(re.findall(r"\$\(SOURCE_DIR\)/([^\s\\]+)", makefile))
    missing = [path for path in ESSENTIAL_SOURCES if path not in sources]
    if missing:
        raise ValueError(f"core entry/pmap sources are absent: {missing}")
    if not re.search(r"(?:^|\s)-DCONFIG_PMAP_PPL(?:\s|$)", makefile):
        raise ValueError("pmap implementation selection missing from generated makefile")
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.iterdir()) if path.is_file()}


def run_logged(command, cwd, environment, log):
    result = subprocess.run([str(value) for value in command], cwd=cwd, env=environment,
                            capture_output=True, text=True, timeout=240)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise ValueError(f"host config step failed; inspect {log}")


def check(zig, bison, flex, shell, output):
    workspace = Path(__file__).resolve().parent.parent
    output = output.resolve()
    artifacts = (workspace / "artifacts").resolve()
    if sys.platform != "win32" or output == artifacts or not output.is_relative_to(artifacts) or output.exists():
        raise ValueError("requires Windows and a new directory under workspace artifacts")
    sources = {}
    for path in SOURCE_HASHES:
        url = f"https://raw.githubusercontent.com/apple-oss-distributions/xnu/{SOURCE_COMMIT}/{path}"
        with urllib.request.urlopen(url, timeout=30) as response:
            sources[path] = response.read(1048577)
    validate_sources(sources)
    output.mkdir(parents=True)
    source = output / "source"
    for path, data in sources.items():
        destination = source / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    selection = check_master(shell, output / "selection")
    environment = os.environ.copy()
    environment.pop("VPATH", None)
    environment["ZIG_GLOBAL_CACHE_DIR"] = str(output / "zig-global-cache")
    environment["ZIG_LOCAL_CACHE_DIR"] = str(output / "zig-local-cache")
    compiler_source = source / "SETUP/config"
    run_logged([bison.resolve(), "-y", "-d", "-o", "parser.c", "parser.y"], compiler_source, environment, output / "bison.log")
    run_logged([flex.resolve(), "--header-file=lexer.yy.h", "-o", "lexer.yy.c", "lexer.l"], compiler_source, environment, output / "flex.log")
    executable = output / "config.exe"
    compatibility = workspace / "tools/xnu_config_host_compat.h"
    flags = ["-target", "x86_64-windows-gnu", "-std=gnu89", "-DYY_NO_INPUT", "-include", str(compatibility), "-I.", "-O0"]
    filenames = ["externs.c", "main.c", "mkheaders.c", "mkioconf.c", "mkmakefile.c", "openp.c", "searchp.c", "lexer.yy.c", "parser.c"]
    run_logged([zig.resolve(), "cc", *flags, *filenames, "-o", executable], compiler_source, environment, output / "compile.log")
    results = {}
    for config in ("DEVELOPMENT", "DEBUG"):
        generated = output / "generated" / config
        generated.mkdir(parents=True)
        fragment = (output / "selection" / f"config.{config}_ARM64.fragment").read_text(encoding="utf-8")
        tail = f'builddir "."\nobjectdir "generated/{config}"\nsourcedir "source"\n'
        input_path = output / f"config.{config}_ARM64"
        input_path.write_text(fragment + tail, encoding="utf-8", newline="\n")
        run_logged([executable, "-c", "source/osfmk/conf", input_path.name], output, environment, output / f"{config}.log")
        results[config] = verify_generated(generated, config)
    report = {
        "purpose": "native host config compiler and osfmk header generation, NOT a kernel build",
        "source_commit": SOURCE_COMMIT, "source_sha256": SOURCE_HASHES,
        "master_sha256": selection["master_sha256"], "host_compile_flags": flags,
        "compatibility_header_sha256": hashlib.sha256(compatibility.read_bytes()).hexdigest(),
        "config_executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "tool_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest()
                        for name, path in (("zig", zig), ("bison", bison), ("flex", flex))},
        "generated_files_sha256": results,
        "limitations": ["Windows GNU89 host build with a BSD type/string compatibility header",
                        "only actual osfmk manifests/templates; no other component generation",
                        "no full doconf wrapper, SDK or kernel compilation", "no hardware access"],
        "boot_approved": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("zig", "bison", "flex", "shell", "output-directory"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.zig, args.bison, args.flex, args.shell, args.output_directory), indent=2))


if __name__ == "__main__":
    main()
