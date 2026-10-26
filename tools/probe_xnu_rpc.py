"""Compile one pinned RPC candidate with real XNU make rules; no kernel link or device access."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import time

try:
    from tools.check_xnu_build import check, configuration_command, run_phase, succeeded
    from tools.check_xnu_build_graph import clean_environment
    from tools.check_xnu_setup import setup_command
    from tools.prepare_iig_legacy_probe import legacy_candidate, prepare_candidates, invocation_assertions
except ModuleNotFoundError:
    from check_xnu_build import check, configuration_command, run_phase, succeeded
    from check_xnu_build_graph import clean_environment
    from check_xnu_setup import setup_command
    from prepare_iig_legacy_probe import legacy_candidate, prepare_candidates, invocation_assertions


EXPECTED_BLOCKER = "IIG emits kernelContent absent from pinned IORPC ABI; matching generator or reviewed RPC backport required"


def object_command(source, build, generated, sdk, availability, names=("OSObject.iig.cpp",)):
    if not names or len(names) > 17 or len(set(names)) != len(names) or any(
            not re.fullmatch(r"[A-Za-z_]\w*\.iig\.cpp", name) for name in names):
        raise ValueError("unsafe or unbounded RPC object targets")
    command = setup_command(source, build, sdk)
    command[command.index(str(source / "Makefile"))] = str(generated / "Makefile")
    command[-1:] = [f"MIDO_AVAILABILITY_PL={availability}",
                   "CURRENT_KERNEL_CONFIG=DEVELOPMENT", "CURRENT_ARCH_CONFIG=ARM64",
                   "CURRENT_MACHINE_CONFIG=MIDO", "CURRENT_BUILD_CONFIG=DEVELOPMENT_ARM64_MIDO",
                   f"SOURCE={source / 'iokit'}/", "RELATIVE_SOURCE_PATH=./iokit/conf",
                   f"TARGET={build / 'obj/DEVELOPMENT_ARM64_MIDO/iokit'}",
                   f"OBJPATH={build / 'obj/DEVELOPMENT_ARM64_MIDO'}",
                   "BUILD_LTO=0", "VERBOSE=YES", *[name[:-1] + "o" for name in names]]
    if len(names) > 1:
        command.insert(1, "--keep-going")
    return command


def inspect_object(path):
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 16 * 1024 * 1024:
        raise ValueError("missing or unsafe RPC object")
    data = path.read_bytes()
    if len(data) < 32 or struct.unpack_from("<4I", data) != (0xFEEDFACF, 0x0100000C, 0, 1):
        raise ValueError("expected baseline ARM64 Mach-O object, not bitcode or a linked kernel")
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "format": "MH_OBJECT ARM64_ALL", "instruction_baseline_audited": False}


def probe(output, sdk, all_rpc=False):
    started = time.monotonic()
    initial = check(output, sdk, attempt_kernel=True)
    output = output.resolve()
    source = output / "source"
    build = output / "build"
    report = {"purpose": __doc__, "passed": False, "boot_approved": False,
              "kernel_built": False, "phases": {}, "blockers": []}
    try:
        if not initial["configuration_generated"] or initial["blockers"] != [EXPECTED_BLOCKER]:
            raise ValueError("expected isolated IIG rejection after genuine exports/configuration")
        records = initial["iig_abi"]["implementations"]
        if len(records) != 1:
            raise ValueError("expected exactly one retained OSObject implementation")
        original = build / records[0]["path"]
        candidate, report["candidate"] = legacy_candidate(original.read_bytes(),
                                                         (source / "iokit/IOKit/IORPC.h").read_bytes())
        candidates = {"OSObject.iig.cpp": candidate}
        if all_rpc:
            candidates, report["all_candidates"] = prepare_candidates(
                original.parent, (source / "iokit/IOKit/IORPC.h").read_bytes())
        generated = build / "obj/DEVELOPMENT_ARM64_MIDO/iokit/DEVELOPMENT"
        generated.mkdir(parents=True, exist_ok=True)
        environment = clean_environment(os.environ)
        environment.update(SRCROOT=str(source), OBJROOT=str(build / "obj"),
                           SOURCE=str(source / "iokit/conf") + "/")
        command = configuration_command(source, generated, sdk)
        command[command.index(str(source / "osfmk/conf"))] = str(source / "iokit/conf")
        result = run_phase(command, source, environment, output / "rpc-configuration.log", started)
        report["phases"]["configuration"] = {"command": command, "result": result}
        if not succeeded(result):
            raise ValueError("real IOKit configuration failed")
        (generated / "DriverKit").mkdir(exist_ok=True)
        report["layout_assertion_union_counts"] = {}
        for name, data in candidates.items():
            assertions, count = invocation_assertions(data)
            report["layout_assertion_union_counts"][name] = count
            (generated / "DriverKit" / name).write_bytes(data + assertions)
        availability = json.loads((output / "setup-report.json").read_text())["open_availability"]["script_path"]
        command = object_command(source, build, generated, sdk, availability, tuple(candidates))
        result = run_phase(command, generated, environment, output / "rpc-compile.log", started)
        report["phases"]["compile"] = {"command": command, "result": result}
        report["objects"] = {name: inspect_object(generated / (name[:-1] + "o")) for name in candidates
                             if (generated / (name[:-1] + "o")).is_file()}
        if not succeeded(result):
            raise ValueError("real RPC object compilation failed; inspect rpc-compile.log")
        report["object"] = inspect_object(generated / "OSObject.iig.cpo")
        if len(report["objects"]) != len(candidates):
            raise ValueError("not every requested RPC class produced an inspected object")
        report["passed"] = True
    except (OSError, ValueError, KeyError) as error:
        report["blockers"].append(str(error))
    (output / "rpc-probe-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--sdk", choices=("iphoneos", "macosx"), default="iphoneos")
    parser.add_argument("--all-rpc", action="store_true")
    args = parser.parse_args()
    report = probe(args.output_directory, args.sdk, args.all_rpc)
    print(json.dumps(report, indent=2))
    for name in ("rpc-configuration", "rpc-compile"):
        path = args.output_directory / (name + ".log")
        if path.exists():
            lines = path.read_text(errors="replace").splitlines()
            print("\n".join(lines[-100:]))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
