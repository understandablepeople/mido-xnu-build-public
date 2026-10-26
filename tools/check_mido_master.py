"""Replay the pinned XNU doconf selector, not make or the config compiler."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request

try:
    from tools.check_mido_config import SOURCE_COMMIT
except ModuleNotFoundError:
    from check_mido_config import SOURCE_COMMIT


SOURCE_HASHES = {
    "config/MASTER": "e89579a814c1cf6b32ebf99119fa57d42725e085ccad677d9fdb3175d4f58c3a",
    "SETUP/config/doconf": "24a2116497d23d981e7ae6fd131d0c1ec13930b2dd601458d70a2e80ff9ae0df",
}
CONFIGS = ("DEVELOPMENT", "DEBUG")
REQUIRED = {"MACH", "MACH_BSD", "IOKIT", "IOKITCPP", "LIBKERNCPP",
            "CONFIG_NOMONITORS", "CONFIG_SCHED_TRADITIONAL", "MACH_ASSERT", "DEVFS",
            "CONFIG_PMAP_PPL", "NOS_ARM_PMAP", "NOS_ARM_ASM", "INET", "NETWORKING", "SOCKETS",
            "CONFIG_MEMORYSTATUS", "CONFIG_JETSAM", "CONFIG_MACF", "CONFIG_MACF_SOCKET_SUBSET",
            "VM_PRESSURE_EVENTS", "CONFIG_COALITIONS", "IMPORTANCE_INHERITANCE", "CONFIG_IOSCHED",
            "NAMEDSTREAMS", "NECP", "MULTIPATH", "MPTCP", "TRAFFIC_MGT", "SKYWALK",
            "CONFIG_NEXUS_USER_PIPE", "CONFIG_NEXUS_KERNEL_PIPE", "CONFIG_NEXUS_MONITOR",
            "CONFIG_NEXUS_FLOWSWITCH", "CONFIG_NEXUS_NETIF",
            "CONFIG_SCHED_MULTIQ", "CONFIG_FSE", "IPSEC", "IPSEC_ESP", "CRYPTO", "PF",
            "CONTENT_FILTER", "CONFIG_ATM", "CONFIG_TELEMETRY", "CONFIG_PROC_UUID_POLICY",
            "MACH_KDP", "CONFIG_KDP_INTERACTIVE_DEBUGGING", "CONFIG_DTRACE", "IOTRACKING",
            "CONFIG_XNUPOST", "CONFIG_COREDUMP"}
FORBIDDEN = {"XNU_MONITOR", "CONFIG_KERNEL_INTEGRITY", "KPC", "KPERF",
             "CONFIG_KASAN", "CONFIG_KERNEL_TBI", "CONFIG_PGTRACE"}


def validate_sources(sources):
    if set(sources) != set(SOURCE_HASHES):
        raise ValueError("unexpected source file set")
    for path, expected in SOURCE_HASHES.items():
        if hashlib.sha256(sources[path]).hexdigest() != expected:
            raise ValueError(f"source hash mismatch: {path}")


def reject_preprocessing(text):
    if re.search(r"^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif|define|undef|include)\b", text, re.M):
        raise ValueError("unifdef is not executed; preprocessor directives are unsupported")


def selector_script(doconf):
    start = "    sed -n \\\n"
    end = " >$SYSCONF.new"
    if doconf.count(start) != 1 or doconf.count(end) != 1:
        raise ValueError("unexpected doconf selector boundaries")
    selector = doconf.split(start, 1)[1].split(end, 1)[0]
    return (
        "set -eu\nset -o pipefail\n"
        "{ cat \"$1\" \"$2\"; printf '+%s\\n' \"$3\"; cat \"$1\" \"$2\"; } |\n"
        + start + selector + "\n"
    )


def validate_configuration(text, config):
    if config not in CONFIGS:
        raise ValueError("unsupported MIDO kernel configuration")
    options = []
    for line in text.splitlines():
        match = re.match(r"^\s*options\s+([A-Za-z_][A-Za-z_0-9]*)(?:=[^\s#]+)?(?:\s|$)", line)
        if match:
            options.append(match[1])
    selected = set(options)
    if len(options) != len(selected):
        raise ValueError("duplicate selected options")
    if not REQUIRED <= selected or selected & FORBIDDEN:
        raise ValueError(f"unsafe or incomplete option selection: missing={sorted(REQUIRED - selected)}, forbidden={sorted(selected & FORBIDDEN)}")
    expected, rejected = ("DEVELOPMENT", "DEBUG") if config == "DEVELOPMENT" else ("DEBUG", "DEVELOPMENT")
    if expected not in selected or rejected in selected:
        raise ValueError("wrong kernel configuration selected")
    if len(re.findall(r'^machine\s+"arm64"\s*$', text, re.M)) != 1:
        raise ValueError("expected exactly one arm64 machine")
    if len(re.findall(r'^makeoptions\s+OSFMK_MACHINE\s*=\s*"arm64"\s*$', text, re.M)) != 1:
        raise ValueError("expected exactly one arm64 OSFMK machine")
    return sorted(selected)


def check(shell, output):
    workspace = Path(__file__).resolve().parent.parent
    output = output.resolve()
    artifacts = (workspace / "artifacts").resolve()
    if output == artifacts or not output.is_relative_to(artifacts) or output.exists():
        raise ValueError("output must be a new directory under workspace artifacts")
    sources = {}
    for path in SOURCE_HASHES:
        url = f"https://raw.githubusercontent.com/apple-oss-distributions/xnu/{SOURCE_COMMIT}/{path}"
        with urllib.request.urlopen(url, timeout=30) as response:
            sources[path] = response.read(1048577)
    validate_sources(sources)
    master = workspace / "devices/mido/xnu/MASTER.arm64.mido"
    master_bytes = master.read_bytes()
    reject_preprocessing(sources["config/MASTER"].decode("utf-8"))
    reject_preprocessing(master_bytes.decode("utf-8"))
    script = selector_script(sources["SETUP/config/doconf"].decode("utf-8"))
    output.mkdir(parents=True)
    (output / "MASTER").write_bytes(sources["config/MASTER"])
    (output / "doconf.reference").write_bytes(sources["SETUP/config/doconf"])
    (output / "MASTER.arm64.mido").write_bytes(master_bytes)
    (output / "selector.sh").write_text(script, encoding="utf-8", newline="\n")
    environment = os.environ.copy()
    environment["PATH"] = str(shell.resolve().parent) + os.pathsep + environment.get("PATH", "")
    results = {}
    for config in CONFIGS:
        result = subprocess.run([str(shell.resolve()), "--noprofile", "--norc", "selector.sh",
                                 "MASTER", "MASTER.arm64.mido", config],
                                cwd=output, env=environment, capture_output=True, text=True, timeout=30)
        (output / f"{config}.log").write_text(result.stderr, encoding="utf-8")
        if result.returncode:
            raise ValueError(f"selector failed: {result.stderr}")
        (output / f"config.{config}_ARM64.fragment").write_text(result.stdout, encoding="utf-8")
        results[config] = validate_configuration(result.stdout, config)
    report = {
        "purpose": "actual pinned sed/awk selector only, NOT a kernel configuration build",
        "source_commit": SOURCE_COMMIT, "source_sha256": SOURCE_HASHES,
        "master_sha256": hashlib.sha256(master_bytes).hexdigest(),
        "selector_sha256": hashlib.sha256(script.encode()).hexdigest(),
        "selected_options": results,
        "limitations": ["no csh doconf wrapper, unifdef or config compiler",
                        "no GNU make evaluation or SDK validation",
                        "minimal option dependencies are not kernel-compile validated",
                        "no platform source registration or hardware execution"],
        "boot_approved": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shell", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.shell, args.output_directory), indent=2))


if __name__ == "__main__":
    main()
