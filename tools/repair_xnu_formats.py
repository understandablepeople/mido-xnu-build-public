"""Apply reviewed diagnostic-only format repairs to pinned XNU sources."""

import hashlib
import json
from pathlib import Path
import re


PROFILES = {
    "bsd/kern/kdebug_common.c": (
        "77c88ca0895e3909564d63e60d36e7b85119ec6cc411375a9e664edb96cf644f",
        ((863, 16, "%lld", "%llu"), (864, 28, "%lld", "%llu"),
         (913, 16, "%lld", "%llu"), (914, 28, "%lld", "%llu"))),
    "security/mac_process.c": (
        "940d2ed33c6a5e789f44793bd0d02d97ea2b45b6a78cf3690113b812d4011c5d",
        ((973, 45, "%ld", "%zu"),)),
    "security/mac_vfs.c": (
        "c571a0b7de9c1b521c7724b0dc99ca74e244373fcaa96c503f71df7df2c8011a",
        ((1370, 45, "%ld", "%zu"), (1413, 45, "%ld", "%zu"),
         (1418, 71, "%ld", "%zu"))),
    "bsd/kern/kern_memorystatus.c": (
        "7866b8cec52303897d510f737a0f256a4ce495b6b1e9dccd04bcbac2d24f6a65",
        ((4719, 62, "%lld", "%llu"), (4719, 68, "%lld", "%llu"))),
    "bsd/kern/kpi_mbuf.c": (
        "67be9bff442dc694738cf4232968fb4a767c7ce730bed563f49509a243534f8e",
        ((270, 28, "%ld", "%zu"),)),
    "iokit/Kernel/IOService.cpp": (
        "986334f52f7c50de1e413269a0d13e2ee52e4b3ca567421271e66580fda19a67",
        ((5563, 34, "%lld", "%llu"), (5563, 41, "%lld", "%llu"),
         (5664, 18, "%lld", "%llu"), (5671, 18, "%lld", "%llu"))),
    "iokit/Kernel/IOServicePM.cpp": (
        "551254d9ac104251617936122e1f32ca1889435e7568c070daaf718577743db2",
        ((2083, 25, "%ld", "%lu"),)),
    "iokit/Kernel/IOPolledInterface.cpp": (
        "aa8fe75a5fc515e7b0f31e1249452f51aa9cc3ec0dee8168a37f38fd0a8f09d5",
        ((664, 45, "%ld", "%lu"),)),
    "iokit/Kernel/IOPMrootDomain.cpp": (
        "7d8a2db2da31c0d8aded672c10c76d2ca6222206cbf1794e2e18c228a34c58a0",
        ((2946, 30, "%lld", "%llu"),)),
    "iokit/Kernel/IOUserServer.cpp": (
        "2a3c7e5e45c0c943e9bba0689e25ce6b13897ae2e69a3d63bc4a0efbf670bc2f",
        ((4840, 30, "%ld", "%lu"), (4892, 38, "%ld", "%lu"),
         (4941, 38, "%ld", "%lu"))),
}


def load_decimal_profiles():
    manifest = json.loads(Path(__file__).with_name("reviewed_decimal_profiles.json").read_text(encoding="utf-8"))
    for relative, profile in manifest["profiles"].items():
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("invalid decimal repair source path")
        expected = profile["sha256"]
        replacements = tuple(tuple(entry) for entry in profile["replacements"])
        if relative in PROFILES:
            previous, original = PROFILES[relative]
            if previous != expected:
                raise ValueError("conflicting decimal source hash")
            replacements = original + replacements
        PROFILES[relative] = expected, replacements


load_decimal_profiles()
CAST_PROFILES = json.loads(Path(__file__).with_name("reviewed_integer_casts.json").read_text(encoding="utf-8"))["profiles"]
for relative, profile in CAST_PROFILES.items():
    if relative in PROFILES and PROFILES[relative][0] != profile["sha256"]:
        raise ValueError("conflicting integer cast source hash")
    PROFILES.setdefault(relative, (profile["sha256"], ()))


def repair_formats(relative, data):
    expected, replacements = PROFILES[relative]
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("unexpected format repair source: " + relative)
    lines = data.splitlines(keepends=True)
    changes = list(replacements)
    casts = set()
    for row, column, expression, primitive in CAST_PROFILES.get(relative, {}).get("casts", ()):
        if primitive not in ("unsigned int", "unsigned long", "unsigned long long") or not re.fullmatch(
                r"[A-Za-z_]\w*(?:(?:->|\.)[A-Za-z_]\w*)*", expression):
            raise ValueError("unreviewed integer cast")
        entry = (row, column, expression, "(" + primitive + ")(" + expression + ")")
        casts.add(entry)
        changes.append(entry)
    for row, column, original, replacement in sorted(changes, reverse=True):
        is_format = original.startswith("%")
        if not is_format and (row, column, original, replacement) not in casts:
            raise ValueError("unreviewed source expression replacement")
        original = original.encode("ascii")
        replacement = replacement.encode("ascii")
        if is_format and (original, replacement) not in {
            (b"%lld", b"%llu"), (b"%ld", b"%lu"), (b"%ld", b"%zu"),
            (b"%d", b"%u"), (b"%03d", b"%03u"), (b"%2d", b"%2u")
        }:
            raise ValueError("unreviewed format conversion")
        if row < 1 or row > len(lines) or column < 1:
            raise ValueError("invalid format repair coordinate")
        line = lines[row - 1]
        start = column - 1
        if line[start:start + len(original)] != original:
            raise ValueError("unexpected format repair location: " + relative)
        lines[row - 1] = line[:start] + replacement + line[start + len(original):]
    return b"".join(lines)


def stage_format_repairs(source):
    pending = []
    report = {}
    for relative, (expected, replacements) in PROFILES.items():
        target = source / relative
        after = repair_formats(relative, target.read_bytes())
        pending.append((target, after))
        report[relative] = {"original_sha256": expected,
                            "updated_sha256": hashlib.sha256(after).hexdigest(),
                            "format_replacements": len(replacements),
                            "integer_casts": len(CAST_PROFILES.get(relative, {}).get("casts", ()))}
    for target, after in pending:
        target.write_bytes(after)
    return report
