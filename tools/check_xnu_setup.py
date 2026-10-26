"""Audit or explicitly execute pinned XNU host-tool setup; never build a kernel."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys

try:
    from tools.check_xnu_build_graph import clean_environment, make_command, query, run_make
    from tools.prepare_xnu_tree import prepare
    from tools.prepare_xnu_availability import prepare_availability
except ModuleNotFoundError:
    from check_xnu_build_graph import clean_environment, make_command, query, run_make
    from prepare_xnu_tree import prepare
    from prepare_xnu_availability import prepare_availability


HOST_TOOLS = ("clang", "flex", "bison", "gm4", "codesign_allocate")
SETUP_PROGRAMS = ("config", "kextsymboltool", "setsegname", "decomment", "installfile", "replacecontents")
SETUP_DATA = ("san/kasan-blacklist-x86_64", "san/kasan-blacklist-arm64",
              "san/kcov-blacklist-x86_64", "san/kcov-blacklist-arm64",
              "bsd/sys/_posix_availability.h", "bsd/sys/_symbol_aliasing.h")


def setup_command(source, build, sdk):
    command = make_command(source, build, sdk)
    command.remove("--just-print")
    command[-1:] = ["MAKEJOBS=--jobs=1", "setup"]
    return command


def safe_query(arguments, environment):
    try:
        return query(arguments, environment)
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"exit_code": None, "stdout": "", "stderr": str(error)}


def sdk_result_ready(path, version):
    return (path["exit_code"] == 0 and version["exit_code"] == 0
            and bool(path["stdout"]) and Path(path["stdout"]).is_dir() and bool(version["stdout"]))


def executable_resource(path):
    return path.is_file() and os.access(path, os.X_OK)


def probe_availability(path, environment):
    results = {}
    for option, required in (("--ios", "16.6"), ("--macosx", "13.5")):
        try:
            process = subprocess.run([str(path), option], env=environment, capture_output=True, text=True, timeout=15)
            versions = process.stdout.split()
            valid = (process.returncode == 0 and required in versions
                     and all(re.fullmatch(r"[0-9]+\.[0-9]+(?:\.[0-9]+)?", version) for version in versions))
            results[option] = {"exit_code": process.returncode, "stdout": process.stdout.strip(),
                               "stderr": process.stderr.strip(), "valid": valid}
        except (OSError, subprocess.TimeoutExpired) as error:
            results[option] = {"exit_code": None, "stdout": "", "stderr": str(error), "valid": False}
    return {"ready": all(item["valid"] for item in results.values()), "queries": results}


def inspect_outputs(build):
    objects = build / "obj"
    programs = {f"SETUP/{name}/{name}" for name in SETUP_PROGRAMS}
    records = {}
    for relative in sorted(programs | set(SETUP_DATA)):
        path = objects / relative
        valid = path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(objects.resolve())
        data = path.read_bytes() if valid else b""
        tokens = {"bsd/sys/_symbol_aliasing.h": (b"__DARWIN_ALIAS_STARTING_IPHONE___IPHONE_16_6",
                                               b"__DARWIN_ALIAS_STARTING_MAC___MAC_13_5"),
                  "bsd/sys/_posix_availability.h": (b"___POSIX_C_DEPRECATED_STARTING_200809L",)}
        content_valid = all(token in data for token in tokens.get(relative, ()))
        native = None
        if relative in programs:
            native = (len(data) >= 32 and data[:4] == b"\xcf\xfa\xed\xfe"
                      and struct.unpack_from("<I", data, 4)[0] in (0x01000007, 0x0100000C)
                      and struct.unpack_from("<I", data, 12)[0] == 2
                      and os.access(path, os.X_OK))
        records[relative] = {"valid": valid and bool(data) and content_valid and native is not False,
                             "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest() if data else None,
                             "native_executable_header": native, "required_tokens_present": content_valid}
    return records


def check(output, sdk, archive=None, execute_setup=False, open_availability=False):
    if sys.platform != "darwin":
        raise ValueError("requires actual macOS; host setup is not emulated")
    if sdk not in ("macosx", "iphoneos"):
        raise ValueError("unsupported SDK")
    source_report = prepare(output, archive)
    output = output.resolve()
    source = output / "source"
    build = output / "build"
    availability = prepare_availability(output) if open_availability else None
    environment = clean_environment(os.environ)
    sdk_results = {}
    blockers = []
    for selected in dict.fromkeys((sdk, "macosx")):
        path = safe_query(["--sdk", selected, "--show-sdk-path"], environment)
        version = safe_query(["--sdk", selected, "--show-sdk-version"], environment)
        ready = sdk_result_ready(path, version)
        sdk_results[selected] = {"path": path, "version": version, "ready": ready}
        if not ready:
            blockers.append(f"SDK unavailable: {selected}")
    tools = {name: safe_query(["--sdk", "macosx", "--find", name], environment) for name in HOST_TOOLS}
    for name, result in tools.items():
        if result["exit_code"] != 0 or not result["stdout"]:
            blockers.append(f"host tool unavailable: {name}")
    resources = {"codesign": Path("/usr/bin/codesign")}
    if availability:
        resources["availability.pl"] = Path(availability["script_path"])
    elif sdk_results[sdk]["ready"]:
        resources["availability.pl"] = Path(sdk_results[sdk]["path"]["stdout"]) / "usr/local/libexec/availability.pl"
    resource_results = {name: {"path": str(path), "executable": executable_resource(path)}
                        for name, path in resources.items()}
    for name, result in resource_results.items():
        if not result["executable"]:
            blockers.append(f"required executable resource unavailable: {name}")
    availability_probe = None
    if execute_setup and not blockers:
        availability_probe = probe_availability(resources["availability.pl"], environment)
        if not availability_probe["ready"]:
            blockers.append("availability.pl cannot emit validated iOS/macOS version lists")
    command = setup_command(source, build, sdk)
    if availability:
        command.insert(-1, f"MIDO_AVAILABILITY_PL={availability['script_path']}")
    result = {"exit_code": None, "stopped_by": "prerequisites unavailable" if blockers else "execution not requested"}
    outputs = {}
    if execute_setup and not blockers:
        for directory in (build / "obj" / "DEVELOPMENT_ARM64_MIDO", build / "sym", build / "dst"):
            directory.mkdir(parents=True, exist_ok=True)
        try:
            result = run_make(command, source, environment, output / "setup.log")
        except OSError as error:
            result = {"exit_code": None, "stopped_by": f"make could not start: {error}"}
        outputs = inspect_outputs(build)
    passed = (execute_setup and not blockers and result["exit_code"] == 0
              and not result["stopped_by"] and bool(outputs) and all(item["valid"] for item in outputs.values()))
    report = {"purpose": "real host-tool setup only, NOT a kernel build or full graph check",
              "source": source_report, "sdk": sdk, "sdks": sdk_results, "host_tools": tools,
              "resources": resource_results, "open_availability": availability,
              "availability_probe": availability_probe,
              "blockers": blockers, "prerequisites_ready": not blockers,
              "execution_requested": execute_setup, "make_command": command, "make_result": result,
              "outputs": outputs, "setup_passed": bool(passed), "graph_passed": False,
              "kernel_built": False, "boot_approved": False, "platform_memory_approved": False,
              "limitations": ["setup compiles, links and ad-hoc signs host programs; upstream scripts execute",
                              "output headers are checked structurally, not authenticated or executed by this validator",
                              "setup does not export all kernel headers or generate all kernel build prerequisites",
                              "a successful setup does not repair or validate the cold-tree all-target dry-run"]}
    (output / "setup-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--sdk", choices=("macosx", "iphoneos"), required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--execute-setup", action="store_true", help="allow real host-tool compilation, not kernel compilation")
    parser.add_argument("--open-availability", action="store_true", help="prepare original pinned Apple availability script outside SDK")
    args = parser.parse_args()
    report = check(args.output_directory, args.sdk, args.archive, args.execute_setup, args.open_availability)
    print(json.dumps(report, indent=2))
    log = args.output_directory / "setup.log"
    if log.exists():
        print("Last 120 setup diagnostic lines:")
        print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-120:]))
    if not (report["setup_passed"] if args.execute_setup else report["prerequisites_ready"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
