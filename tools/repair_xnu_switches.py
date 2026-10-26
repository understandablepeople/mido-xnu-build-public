"""Make reviewed implicit unmatched-switch exits explicit without adding work."""

import hashlib
import json
from pathlib import Path


PROFILES = json.loads(Path(__file__).with_name("reviewed_switch_profiles.json").read_text(encoding="utf-8"))["profiles"]


def repair_switches(relative, data):
    profile = PROFILES[relative]
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != profile["sha256"]:
        raise ValueError("unexpected switch repair source: " + relative)
    lines = data.splitlines(keepends=True)
    rows = set()
    for row, expected, indent in sorted(profile["insertions"], reverse=True):
        if row < 1 or row > len(lines) or row in rows or indent.strip():
            raise ValueError("invalid switch insertion coordinate")
        rows.add(row)
        if lines[row - 1] != expected.encode("utf-8") or not expected.rstrip().endswith("{"):
            raise ValueError("unexpected switch opening line")
        addition = (indent + "default:\n" + indent + "\tbreak;\n").encode("ascii")
        lines.insert(row, addition)
    return b"".join(lines)


def stage_switch_repairs(source):
    pending = []
    report = {}
    for relative, profile in PROFILES.items():
        target = source / relative
        after = repair_switches(relative, target.read_bytes())
        pending.append((target, after))
        report[relative] = {"original_sha256": profile["sha256"],
                            "updated_sha256": hashlib.sha256(after).hexdigest(),
                            "default_exits": len(profile["insertions"])}
    for target, after in pending:
        target.write_bytes(after)
    return report
