"""Compare an offline transfer fixture with saved evidence, never approve loading."""

import argparse
import hashlib
import json
from pathlib import Path

try:
    from tools.inspect_mido_memory import inspect_blob
    from tools.inspect_xnu import inspect
except ModuleNotFoundError:
    from inspect_mido_memory import inspect_blob
    from inspect_xnu import inspect


LIMIT = 1 << 64


def extent(start, size):
    if type(start) is not int or type(size) is not int:
        raise ValueError("range values must be integers")
    if start < 0 or size <= 0 or start + size > LIMIT:
        raise ValueError("invalid or overflowing memory range")
    return dict(start=start, end_exclusive=start + size, size=size)


def overlaps(first, second):
    return first["start"] < second["end_exclusive"] and second["start"] < first["end_exclusive"]


def audit(kernel, fixture, inventory, loader_audit=None):
    image = inspect(kernel)
    if fixture["kernel_sha256"] != image["sha256"]:
        raise ValueError("transfer fixture belongs to a different kernel")
    if "synthetic offline transfer fixture" not in fixture.get("purpose", ""):
        raise ValueError("expected an explicitly synthetic transfer fixture")
    claim = extent(fixture["physical_base"], fixture["memory_size"])
    expected_plan = []
    for segment in image["segments"]:
        if not segment["vmsize"]:
            continue
        offset = segment["vmaddr"] - fixture["virtual_base"]
        destination = extent(claim["start"] + offset, segment["vmsize"])
        if offset < 0 or destination["end_exclusive"] > claim["end_exclusive"]:
            raise ValueError("kernel segment escapes the claimed RAM")
        expected_plan.append([segment["fileoff"], offset, segment["filesize"], segment["vmsize"]])
    if fixture["copy_plan"] != expected_plan:
        raise ValueError("copy plan does not match the actual kernel segments")
    if fixture["entry_pa"] != claim["start"] + image["entry_va"] - fixture["virtual_base"]:
        raise ValueError("entry address does not match the kernel")
    handoff = extent(fixture["boot_args_pa"], fixture["handoff_blob_bytes"])
    if not claim["start"] <= handoff["start"] < handoff["end_exclusive"] <= claim["end_exclusive"]:
        raise ValueError("handoff data escapes the claimed RAM")
    if not handoff["start"] <= fixture["device_tree_pa"] < fixture["top_of_kernel_data"] <= handoff["end_exclusive"]:
        raise ValueError("invalid handoff tree bounds")
    for segment in expected_plan:
        if overlaps(handoff, extent(claim["start"] + segment[1], segment[3])):
            raise ValueError("handoff data overlaps a kernel segment")
    exclusions = list(inventory["fixed_reservations"])
    if loader_audit is not None:
        for name in ("runtime_exclusion_candidate", "scratch_exclusion_candidate"):
            candidate = loader_audit[name]
            region = extent(candidate["start"], candidate["size"])
            if candidate["end_exclusive"] != region["end_exclusive"]:
                raise ValueError("inconsistent loader exclusion bounds")
            exclusions.append(dict(region, source="supplied loader audit: " + name))
    collisions = [region for region in exclusions if overlaps(claim, region)]
    banks = sorted(inventory["ram_banks"], key=lambda region: region["start"])
    covered_until = claim["start"]
    for bank in banks:
        if bank["start"] <= covered_until < bank["end_exclusive"]:
            covered_until = bank["end_exclusive"]
    contained = covered_until >= claim["end_exclusive"]
    blockers = [
        "saved recovery evidence does not establish current RAM ownership",
        "incoming image, shim, stack, page tables and DMA lifetimes remain unverified",
        "firmware and secure-world exclusions require a current handoff contract",
    ]
    if not contained:
        blockers.append("claimed RAM extends outside saved declared RAM banks")
    if collisions:
        blockers.append("claimed RAM overlaps conservative exclusions")
    if inventory["unresolved_reservations"]:
        blockers.append("dynamic/vendor reservations remain unresolved; no implicit reclaim")
    if loader_audit is None:
        blockers.append("loader runtime and scratch exclusions were not supplied")
    return dict(
        purpose="offline collision audit, NOT an allocator or device boot approval",
        kernel_sha256=image["sha256"], claimed_ram=claim,
        declared_ram_contains_claim=contained, known_exclusion_collisions=collisions,
        known_exclusion_count=len(exclusions),
        unresolved_reservations=inventory["unresolved_reservations"],
        known_collision_check_passed=contained and not collisions,
        loader_evidence_scope="supplied historical audit only; not live ownership proof",
        blockers=blockers, platform_memory_approved=False, boot_approved=False,
        transfer_of_control_allowed=False, recommended_load_address=None,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kernel", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--dtb", type=Path, required=True)
    parser.add_argument("--loader-audit", type=Path)
    args = parser.parse_args()
    try:
        paths = dict(kernel=args.kernel, fixture=args.fixture, dtb=args.dtb)
        if args.loader_audit:
            paths["loader_audit"] = args.loader_audit
        blobs = {name: path.read_bytes() for name, path in paths.items()}
        result = audit(blobs["kernel"], json.loads(blobs["fixture"]),
                       inspect_blob(blobs["dtb"]),
                       json.loads(blobs["loader_audit"]) if "loader_audit" in blobs else None)
        result["input_sha256"] = {name: hashlib.sha256(blob).hexdigest() for name, blob in blobs.items()}
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"memory audit rejected: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
