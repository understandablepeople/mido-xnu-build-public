"""Prepare a hash-pinned complete XNU tree under artifacts; never build or boot."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import urllib.request

try:
    from tools.check_mido_config import SOURCE_COMMIT, validate_sources, SOURCE_HASHES
except ModuleNotFoundError:
    from check_mido_config import SOURCE_COMMIT, validate_sources, SOURCE_HASHES


ARCHIVE_SHA256 = "6f725962608800b26767242a0a19b8ed1c79e2bf1a0f659506f15ab0737c5acc"
ARCHIVE_LIMIT = 32 * 1024 * 1024
EXPANDED_LIMIT = 128 * 1024 * 1024
MEMBER_LIMIT = 10000
ARCHIVE_ROOT = f"xnu-{SOURCE_COMMIT}"


def validate_members(members):
    if not members or len(members) > MEMBER_LIMIT:
        raise ValueError("unexpected archive member count")
    names = set()
    total = 0
    for member in members:
        path = PurePosixPath(member.name)
        if (path.is_absolute() or not path.parts or path.parts[0] != ARCHIVE_ROOT
                or ".." in path.parts or "\\" in member.name or ":" in member.name
                or any(part.endswith((" ", ".")) for part in path.parts)):
            raise ValueError("unsafe archive path")
        if not (member.isdir() or member.isfile()) or member.size < 0:
            raise ValueError("archive contains a link or special entry")
        normalized = str(path).casefold()
        if normalized in names:
            raise ValueError("duplicate or case-colliding archive path")
        names.add(normalized)
        total += member.size
        if total > EXPANDED_LIMIT:
            raise ValueError("expanded archive exceeds limit")
    return total


def prepare(output, archive_path=None):
    workspace = Path(__file__).resolve().parent.parent
    output = output.resolve()
    artifacts = (workspace / "artifacts").resolve()
    if output == artifacts or not output.is_relative_to(artifacts) or output.exists():
        raise ValueError("output must be a new directory under workspace artifacts")
    if archive_path:
        with archive_path.open("rb") as stream:
            data = stream.read(ARCHIVE_LIMIT + 1)
    else:
        url = f"https://codeload.github.com/apple-oss-distributions/xnu/tar.gz/{SOURCE_COMMIT}"
        with urllib.request.urlopen(url, timeout=60) as response:
            data = response.read(ARCHIVE_LIMIT + 1)
    if len(data) > ARCHIVE_LIMIT or hashlib.sha256(data).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("archive size or SHA-256 mismatch")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
        expanded_bytes = validate_members(members)
        output.mkdir(parents=True)
        source = output / "source"
        source.mkdir()
        for member in members:
            relative = PurePosixPath(member.name).parts[1:]
            destination = source.joinpath(*relative)
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as input_stream, destination.open("xb") as target:
                    shutil.copyfileobj(input_stream, target)
                destination.chmod(0o755 if member.mode & 0o111 else 0o644)
    validate_sources({path: (source / path).read_bytes() for path in SOURCE_HASHES})
    patch = workspace / "devices/mido/xnu/patches/0001-mido-architecture-scaffold.patch"
    environment = os.environ.copy()
    environment["GIT_CEILING_DIRECTORIES"] = str(output)
    platform_patch = workspace / "devices/mido/xnu/patches/0002-mido-exclude-amcc.patch"
    linker_patch = workspace / "devices/mido/xnu/patches/0003-mido-lto-target.patch"
    callout_patch = workspace / "devices/mido/xnu/patches/0004-arm64-remove-duplicate-kdp-callout.patch"
    for current_patch in (patch, platform_patch, linker_patch, callout_patch):
        for options in (["--check"], []):
            subprocess.run(["git", "-C", str(source), "apply", *options, "--whitespace=error", str(current_patch)],
                           env=environment, check=True, timeout=30)
    master = workspace / "devices/mido/xnu/MASTER.arm64.mido"
    destination = source / "config/MASTER.arm64.mido"
    with destination.open("xb") as stream:
        stream.write(master.read_bytes())
    report = {
        "purpose": "complete pinned source preparation, NOT a build or boot approval",
        "source_commit": SOURCE_COMMIT, "archive_sha256": ARCHIVE_SHA256,
        "archive_bytes": len(data), "expanded_bytes": expanded_bytes, "archive_members": len(members),
        "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
        "platform_patch_sha256": hashlib.sha256(platform_patch.read_bytes()).hexdigest(),
        "linker_patch_sha256": hashlib.sha256(linker_patch.read_bytes()).hexdigest(),
        "callout_patch_sha256": hashlib.sha256(callout_patch.read_bytes()).hexdigest(),
        "master_sha256": hashlib.sha256(master.read_bytes()).hexdigest(),
        "source_directory": str(source), "device_accessed": False, "boot_approved": False,
    }
    (output / "source-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.output_directory, args.archive), indent=2))


if __name__ == "__main__":
    main()
