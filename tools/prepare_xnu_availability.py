"""Prepare original pinned Apple AvailabilityVersions outside the SDK."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request


SOURCE_COMMIT = "f3b52ca75ee842a8ac593bd7b03f9f4768c15755"
SCRIPT_SHA256 = "10f764f1a7b9d56626fae0499b893fb05f25e302c6ea68f1ce3d6654c6fe1de1"
ALIAS_SHA256 = "2c86352519ca29e3f6ea869309dfe49cb0d7e106601df78a6bc2959678dac8c9"
SCRIPT_LIMIT = 65536


def validate_inputs(script, alias):
    if len(script) > SCRIPT_LIMIT or hashlib.sha256(script).hexdigest() != SCRIPT_SHA256:
        raise ValueError("AvailabilityVersions script size or SHA-256 mismatch")
    if hashlib.sha256(alias).hexdigest() != ALIAS_SHA256:
        raise ValueError("unexpected original XNU symbol-aliasing script")


def prepare_availability(output, script=None):
    workspace = Path(__file__).resolve().parent.parent
    artifacts = (workspace / "artifacts").resolve()
    output = output.resolve()
    if output == artifacts or not output.is_relative_to(artifacts):
        raise ValueError("dependency output must be inside workspace artifacts")
    source = output / "source"
    alias = source / "bsd/sys/make_symbol_aliasing.sh"
    if alias.is_symlink() or not alias.resolve().is_relative_to(output):
        raise ValueError("symbol-aliasing script escaped output tree")
    destination = output / "dependencies/AvailabilityVersions-121/availability.pl"
    if destination.parent.exists() or not source.is_dir():
        raise ValueError("requires a prepared source and fresh dependency directory")
    if script is None:
        url = f"https://raw.githubusercontent.com/apple-oss-distributions/AvailabilityVersions/{SOURCE_COMMIT}/availability.pl"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(SCRIPT_LIMIT + 1)
    else:
        data = script.read_bytes()
    validate_inputs(data, alias.read_bytes())
    patch = workspace / "devices/mido/xnu/patches/0002-open-availability-path.patch"
    environment = os.environ.copy()
    environment["GIT_CEILING_DIRECTORIES"] = str(output)
    for options in (["--check"], []):
        subprocess.run(["git", "-C", str(source), "apply", *options, "--whitespace=error", str(patch)],
                       env=environment, check=True, timeout=30)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(data)
    destination.chmod(0o755)
    report = {"purpose": "original Apple AvailabilityVersions dependency, NOT an SDK or kernel build",
              "source_commit": SOURCE_COMMIT, "source_tag": "AvailabilityVersions-121",
              "script_sha256": SCRIPT_SHA256, "script_bytes": len(data), "script_path": str(destination),
              "original_alias_sha256": ALIAS_SHA256,
              "patched_alias_sha256": hashlib.sha256(alias.read_bytes()).hexdigest(),
              "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
              "sdk_modified": False, "script_executed": False, "boot_approved": False}
    (output / "availability-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--script", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare_availability(args.output_directory, args.script), indent=2))


if __name__ == "__main__":
    main()
