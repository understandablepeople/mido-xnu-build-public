"""Capture an explicit allowlist of read-only MIDO recovery observations."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
from datetime import datetime, timezone


READS = {
    "identity.txt": "id; uname -a; getprop ro.product.device; getprop ro.bootmode",
    "iomem.txt": "cat /proc/iomem",
    "meminfo.txt": "cat /proc/meminfo",
    "cmdline.txt": "cat /proc/cmdline",
    "mounts.txt": "cat /proc/mounts",
    "live.dtb": "cat /sys/firmware/fdt",
    "rtc.txt": "for n in 1 2 3; do echo ===SAMPLE===; cat /proc/uptime; date -u +%s; for p in /sys/class/rtc/rtc0/name /sys/class/rtc/rtc0/date /sys/class/rtc/rtc0/time /sys/class/rtc/rtc0/since_epoch /sys/class/rtc/rtc0/hctosys; do echo $p; cat $p; done; sleep 1; done",
    "spmi.txt": "ls -l /sys/bus/spmi/devices; ls -l /sys/devices/platform/soc/200f000.qcom,spmi; cat /sys/devices/platform/soc/200f000.qcom,spmi/uevent",
    "storage.txt": "cat /proc/partitions; ls -l /dev/block/bootdevice/by-name; cat /sys/block/mmcblk0/size; cat /sys/block/mmcblk0/queue/logical_block_size",
    "platform-dmesg.txt": "dmesg | grep -i -e spmi -e qpnp -e rtc -e 'reserved mem' -e 'memory:' -e 'cma:'",
    "kernel-config.gz": "cat /proc/config.gz",
}


def capture(adb, serial, output, workspace=None, runner=subprocess.run):
    workspace = (workspace or Path(__file__).resolve().parents[1]).resolve()
    output = output.resolve()
    artifacts = workspace / "artifacts"
    if output == artifacts or not output.is_relative_to(artifacts):
        raise ValueError("output must be a new directory within workspace artifacts")
    if output.exists():
        raise ValueError("refusing to replace a prior capture")
    devices = runner([str(adb), "devices"], capture_output=True, check=True, timeout=20).stdout.decode("utf-8")
    if [serial, "recovery"] not in [line.split() for line in devices.splitlines()]:
        raise ValueError("explicit device must be connected in recovery")
    identity = runner([str(adb), "-s", serial, "shell", "getprop ro.product.device"],
                      capture_output=True, check=True, timeout=20).stdout.strip()
    if identity != b"mido":
        raise ValueError("refusing to capture a non-MIDO device")
    output.mkdir(parents=True)
    manifest = dict(scope="read-only recovery observations; no reboot, mount, flash or raw MMIO",
                    started_utc=datetime.now(timezone.utc).isoformat(),
                    device_serial_sha256=hashlib.sha256(serial.encode()).hexdigest(), files={})
    for name, command in READS.items():
        reply = runner([str(adb), "-s", serial, "exec-out", command],
                       capture_output=True, check=False, timeout=30)
        (output / name).write_bytes(reply.stdout)
        (output / (name + ".stderr")).write_bytes(reply.stderr)
        entry = dict(command=command, returncode=reply.returncode, bytes=len(reply.stdout),
                     sha256=hashlib.sha256(reply.stdout).hexdigest())
        if name == "live.dtb":
            entry["header_valid"] = bool(len(reply.stdout) >= 40 and reply.stdout[:4] == b"\xd0\x0d\xfe\xed"
                and struct.unpack_from(">I", reply.stdout, 4)[0] == len(reply.stdout))
        manifest["files"][name] = entry
    manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["all_reads_succeeded"] = all(entry["returncode"] == 0 for entry in manifest["files"].values())
    (output / "capture-report.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = capture(args.adb, args.serial, args.output)
    print(json.dumps(result, indent=2))
    if not result["all_reads_succeeded"]:
        parser.exit(1, "Some optional reads failed; retained per-command status and stderr\n")


if __name__ == "__main__":
    main()
