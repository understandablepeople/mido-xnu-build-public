"""Apply reviewed RPC output adaptation only inside the disposable host build tree."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

try:
    from tools.prepare_iig_legacy_probe import legacy_candidate, invocation_assertions
except ModuleNotFoundError:
    from prepare_iig_legacy_probe import legacy_candidate, invocation_assertions


def backport(path, header, build):
    workspace = Path(__file__).resolve().parent.parent
    artifacts = (workspace / "artifacts").resolve()
    build = build.resolve()
    if build == artifacts or not build.is_relative_to(artifacts):
        raise ValueError("RPC adaptation requires an isolated artifact build root")
    if path.is_symlink() or not path.resolve().is_relative_to(build) or not path.is_file():
        raise ValueError("RPC output is missing or outside build root")
    relative = path.resolve().relative_to(build)
    allowed = (Path("DEVELOPMENT_ARM64_MIDO/iokit/DriverKit"),
               Path("DEVELOPMENT_ARM64_MIDO/iokit/DEVELOPMENT/DriverKit"))
    if relative.parent not in allowed or path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("unreviewed generated RPC output location")
    profiles = json.loads(Path(__file__).with_name("iig_legacy_profiles.json").read_text())
    if path.name not in profiles:
        raise ValueError("unreviewed generated RPC class")
    candidate, report = legacy_candidate(path.read_bytes(), header.read_bytes(), profiles[path.name],
                                         allow_unreviewed_legacy=True)
    if report.get("temporary_legacy_passthrough"):
        diagnostics = build.parent.parent if build.name == "obj" and build.parent.name == "build" else build
        review = dict(report, implementation=candidate.decode("utf-8"), path=str(relative))
        review_path = diagnostics / (path.stem + "-" + report["input_sha256"] + "-report.json")
        review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
        report["unreviewed_source_report"] = str(review_path)
    assertions, count = invocation_assertions(candidate)
    result = candidate + assertions
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".reviewed-rpc-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(result)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    report.update(path=str(relative), invocation_unions_checked=count,
                  written_sha256=hashlib.sha256(result).hexdigest())
    return report


def install_hook(source):
    path = source / "iokit/DriverKit/Makefile"
    data = path.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "e47aa8b27a5245d755fbe84afa82aad3366b48d7b97e25eb5c21268593e0e90a":
        raise ValueError("unreviewed IIG generation Makefile")
    recipe = (b"\t$(_v)$(IIG) --def $< --header $@ --impl $(patsubst %.h,%.iig.cpp,$@) "
              b"--framework-name DriverKit ${OTHER_IIG_FLAGS} -- ${OTHER_IIG_CFLAGS} $(_vstdout)\n")
    if data.count(recipe) != 1:
        raise ValueError("unexpected IIG generation recipe")
    hook = (b'\t$(_v)"$(MIDO_RPC_PYTHON)" "$(MIDO_RPC_BACKPORT)" '
            b'--implementation "$(patsubst %.h,%.iig.cpp,$@)" '
            b'--iorpc-header "$(SRCROOT)/iokit/IOKit/IORPC.h" --build-root "$(OBJROOT)" $(_vstdout)\n')
    updated = data.replace(recipe, recipe + hook)
    path.write_bytes(updated)
    return {"original_sha256": hashlib.sha256(data).hexdigest(),
            "updated_sha256": hashlib.sha256(updated).hexdigest(), "sdk_modified": False,
            "scope": "generated host IIG implementations only; no kernel ABI change"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--implementation", type=Path, required=True)
    parser.add_argument("--iorpc-header", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(backport(args.implementation, args.iorpc_header, args.build_root)))


if __name__ == "__main__":
    main()
