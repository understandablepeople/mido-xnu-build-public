"""Probe a real macOS SDK and full XNU make graph; NOT a kernel build."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

try:
    from tools.prepare_xnu_tree import prepare
except ModuleNotFoundError:
    from prepare_xnu_tree import prepare


REQUIRED_TOOLS = ("clang", "clang++", "mig", "migcom", "iig", "unifdef")
LOG_LIMIT = 4 * 1024 * 1024
MAX_LOG_LIMIT = 16 * 1024 * 1024
MAKE_TIMEOUT = 90


def clean_environment(environment):
    allowed = {"PATH", "HOME", "TMPDIR", "TMP", "TEMP", "USER", "LOGNAME", "LANG",
               "LC_ALL", "LC_CTYPE", "DEVELOPER_DIR", "TZ"}
    return {name: value for name, value in environment.items() if name in allowed}


def make_command(source, build, sdk):
    if sdk not in ("macosx", "iphoneos"):
        raise ValueError("only explicit macosx/iphoneos SDK diagnostics are supported")
    return ["/usr/bin/make", "--no-print-directory", "-j1", "--just-print", "-f", str(source / "Makefile"),
            f"SRCROOT={source}", f"VERSDIR={source}", f"OBJROOT={build / 'obj'}",
            f"SYMROOT={build / 'sym'}", f"DSTROOT={build / 'dst'}", f"SDKROOT={sdk}",
            "HOST_SDKROOT=macosx", "RC_ProjectName=xnu", "TARGET_CONFIGS=DEVELOPMENT ARM64 MIDO", "all"]


def run_make(command, source, environment, log, timeout=MAKE_TIMEOUT, log_limit=LOG_LIMIT):
    if type(log_limit) is not int or not 1 <= log_limit <= MAX_LOG_LIMIT:
        raise ValueError("invalid bounded build log limit")
    reason = None
    start = time.monotonic()
    with log.open("wb") as output:
        process = subprocess.Popen(command, cwd=source, env=environment, stdout=output,
                                   stderr=subprocess.STDOUT, start_new_session=True)
        try:
            while process.poll() is None:
                if time.monotonic() - start >= timeout:
                    reason = "timeout"
                elif log.stat().st_size > log_limit:
                    reason = "log limit"
                if reason:
                    break
                time.sleep(0.1)
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()
    if reason is None and log.stat().st_size > log_limit:
        reason = "log limit"
    return {"exit_code": process.returncode, "stopped_by": reason,
            "elapsed_seconds": round(time.monotonic() - start, 3), "log_bytes": log.stat().st_size,
            "log_limit_bytes": log_limit}


def query(arguments, environment):
    result = subprocess.run(["/usr/bin/xcrun", *arguments], env=environment,
                            capture_output=True, text=True, timeout=15)
    return {"exit_code": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}


def check(output, sdk, archive=None):
    if sys.platform != "darwin":
        raise ValueError("requires actual macOS; SDK discovery is not emulated")
    if sdk not in ("macosx", "iphoneos"):
        raise ValueError("unsupported SDK")
    source_report = prepare(output, archive)
    output = output.resolve()
    source = output / "source"
    environment = clean_environment(os.environ)
    sdk_path = query(["--sdk", sdk, "--show-sdk-path"], environment)
    sdk_version = query(["--sdk", sdk, "--show-sdk-version"], environment)
    tools = {name: query(["--sdk", sdk, "--find", name], environment) for name in REQUIRED_TOOLS}
    missing = [name for name, result in tools.items() if result["exit_code"] or not result["stdout"]]
    sdk_ready = (sdk_path["exit_code"] == 0 and sdk_version["exit_code"] == 0
                 and Path(sdk_path["stdout"]).is_dir() and bool(sdk_version["stdout"]))
    build = output / "build"
    command = make_command(source, build, sdk)
    if sdk_ready:
        for directory in (build / "obj" / "DEVELOPMENT_ARM64_MIDO", build / "sym", build / "dst"):
            directory.mkdir(parents=True, exist_ok=True)
        make_result = run_make(command, source, environment, output / "make-graph.log")
    else:
        make_result = {"exit_code": None, "stopped_by": "SDK unavailable"}
    report = {
        "purpose": "real SDK and top-level recursive make dry-run, NOT kernel compilation",
        "source": source_report, "sdk": sdk, "sdk_path": sdk_path, "sdk_version": sdk_version,
        "required_tools": tools, "missing_tools": missing, "make_command": command,
        "make_result": make_result,
        "graph_passed": sdk_ready and not missing and make_result["exit_code"] == 0 and not make_result["stopped_by"],
        "limitations": ["make --just-print can execute recursive make recipes and parse-time shell commands",
                        "generated prerequisites may be missing during a dry-run",
                        "a green graph does not prove historical SDK or iig ABI compatibility",
                        "no actual kernel C/assembly compilation, link or hardware validation"],
        "platform_memory_approved": False, "kernel_built": False, "boot_approved": False,
    }
    (output / "build-graph-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--sdk", choices=("macosx", "iphoneos"), required=True)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    report = check(args.output_directory, args.sdk, args.archive)
    print(json.dumps(report, indent=2))
    log = args.output_directory / "make-graph.log"
    if log.exists():
        print("Last 120 make diagnostic lines:")
        print("\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-120:]))
    if not report["graph_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
