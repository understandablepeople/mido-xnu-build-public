"""Run independent host checks together; optionally collect read-only recovery evidence.

Windows host with WSL Ubuntu, Python, clang/cc and the existing local build tree.
No CI scheduling, firmware upload, reboot, flashing or MMIO probing is performed.
Reports can contain private firmware hashes/device logs: keep them local.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def run_check(name, command, output):
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=300)
        content = result.stdout + result.stderr
        status = "passed" if result.returncode == 0 else "failed"
        code = result.returncode
    except (OSError, subprocess.TimeoutExpired) as error:
        content = str(error).encode("utf-8")
        status, code = "failed", None
    (output / (name + ".log")).write_bytes(content)
    return {"name": name, "status": status, "returncode": code,
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "log": name + ".log"}


def arm64_command(distribution):
    drive = ROOT.drive[0].lower()
    linux_root = "/mnt/" + drive + ROOT.as_posix()[2:]
    program = "\n".join([
        "import os,runpy,sys,hashlib,pathlib",
        "root=" + repr(linux_root),
        "base=pathlib.Path(root)",
        "scratch=base/'research/display-buildtree/xnu/iokit/Kernel/arm'",
        "for folder,names in [('input',['MidoInput.cpp']),('gpu',['mido_gpu_cx_power.h','mido_gpu_gx_power.h','mido_gpu_clocks.h','mido_gpu_status.h','mido_gpu_bhs.h','mido_gpu_bhs_runtime.h']),('wifi',['mido_wcnss_audit.h','mido_wcnss_smem.h','mido_scm_probe.h','mido_wcnss_clocks.h'])]:",
        " for name in names:",
        "  assert (base/'mido'/folder/name).read_bytes()==(scratch/name).read_bytes(), name+' scratch differs'",
        "exec_source=(base/'research/display-buildtree/xnu/bsd/kern/kern_exec.c').read_text()",
        "assert 'MIDO SPAWN:' in exec_source and 'mido_spawn_reports' in exec_source",
        "sys.argv=['xnu-cc.py',root+'/research/ci-41382749979/run.log',root+'/research/display-buildtree','iokit/Kernel/arm/MidoInput.cpp','iokit/Kernel/arm/hid/MidoHID.cpp','bsd/kern/kern_exec.c','bsd/vm/vm_unix.c']",
        "module=runpy.run_path(root+'/tools/xnu-cc.py')",
        "module['main'].__globals__['CI_DXB']='/Users/runner/work/mido-xnu-build-public/mido-xnu-build-public/dxb'",
        "module['main'].__globals__['CLANG']='/usr/bin/clang'",
        "os.environ['XNU_CC_OBJDIR']=root+'/research/input-0107-objects'",
        "sys.exit(module['main']())",
    ])
    return ["wsl", "-d", distribution, "-u", "root", "--", "python3", "-c", program]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recovery-read", action="store_true")
    parser.add_argument("--adb", default=r"C:\platform-tools\adb.exe")
    parser.add_argument("--distribution", default="Ubuntu")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("run from Windows; native tests and ARM64 checks run inside WSL")
    output = args.output or ROOT / "logs" / ("preflight-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    output.mkdir(parents=True, exist_ok=False)
    linux_root = "/mnt/" + ROOT.drive[0].lower() + ROOT.as_posix()[2:]
    native = ["wsl", "-d", args.distribution, "-u", "root", "--", "python3"]
    checks = [
        ("native-tests", native + ["-m", "unittest", "discover", "-s", linux_root + "/mido/tests", "-p", "test_*.py", "-v"]),
        ("arm64-objects", arm64_command(args.distribution)),
        ("gpu-firmware", [sys.executable, "-I", "tools/mido_gpu_firmware.py", "research/mido-firmware"]),
        ("wifi-firmware-board", [sys.executable, "-I", "tools/mido_wcnss_firmware.py", "research/mido-firmware", "--dtb", "logs/twrp-live-20261104.dtb", "--power-plan"]),
        ("combined-bringup-plan", [sys.executable, "-I", "tools/mido_bringup_plan.py", "research/mido-firmware", "--dtb", "logs/twrp-live-20261104.dtb", "--payload", "out/gx-scm-0124-8cpu/payload.bin"]),
        ("repository-integrity", native + [linux_root + "/tools/validate-repo.py"]),
    ]
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "checks": [],
              "hardware_runtime": "not tested by host preflight",
              "full_kernel_link": "not performed; requires available build runner",
              "gpu_acceleration": "not established", "wifi_network": "not established",
              "reboot_or_flash": False}
    if args.recovery_read:
        devices = subprocess.run([args.adb, "devices"], capture_output=True, check=True, text=True)
        entries = [line.split() for line in devices.stdout.splitlines()[1:] if line.strip()]
        if len(entries) != 1 or entries[0][1] != "recovery":
            parser.error("expected exactly one recovery device; no collection started")
        device = subprocess.run([args.adb, "shell", "getprop", "ro.product.device"], capture_output=True, check=True, text=True)
        if device.stdout.strip() != "mido":
            parser.error("expected mido recovery; no collection started")
        checks += [
            ("recovery-kernel-log", [sys.executable, "-I", "tools/mido-log-pull.py", str(output / "device-kernel.txt"), "--adb", args.adb]),
            ("recovery-dmesg", [args.adb, "shell", "dmesg"]),
        ]
    with ThreadPoolExecutor(max_workers=3) as workers:
        pending = [workers.submit(run_check, name, command, output) for name, command in checks]
        for future in as_completed(pending):
            result = future.result()
            report["checks"].append(result)
            print(result["name"] + ": " + result["status"], flush=True)
    report["checks"].sort(key=lambda result: result["name"])
    report["all_checks_passed"] = all(result["status"] == "passed" for result in report["checks"])
    tracked = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    report["head"] = tracked.stdout.strip() if tracked.returncode == 0 else None
    report["source_sha256"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                               for folder in ("input", "gpu", "wifi")
                               for path in sorted((ROOT / "mido" / folder).glob("*")) if path.is_file()}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print("Local report: " + str(output / "report.json"))
    return 0 if report["all_checks_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
