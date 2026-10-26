"""Inventory saved DT memory evidence; never propose a kernel load address."""

import argparse
import hashlib
import json
from pathlib import Path
import struct

try:
    from tools.inspect_boot import parse_fdt
except ModuleNotFoundError:
    from inspect_boot import parse_fdt


LIMIT = 1 << 64


def width(properties, name):
    raw = properties.get(name, b"")
    if len(raw) != 4 or struct.unpack(">I", raw)[0] not in (1, 2):
        raise ValueError(f"explicit {name} of one or two cells required")
    return struct.unpack(">I", raw)[0]


def scalar(raw, cells):
    if len(raw) != 4 * cells:
        raise ValueError("incorrect scalar cell width")
    return int.from_bytes(raw, "big")


def interval(start, size, source):
    if size <= 0 or start < 0 or start >= LIMIT or size > LIMIT - start:
        raise ValueError(f"{source}: invalid 64-bit memory interval")
    return dict(start=start, size=size, end_exclusive=start + size, source=source)


def tuples(raw, address_cells, size_cells, source):
    stride = 4 * (address_cells + size_cells)
    if not raw or len(raw) % stride:
        raise ValueError(f"{source}: truncated or empty address/size tuples")
    return [interval(int.from_bytes(raw[offset:offset + address_cells * 4], "big"),
                     int.from_bytes(raw[offset + address_cells * 4:offset + stride], "big"), source)
            for offset in range(0, len(raw), stride)]


def status(properties):
    raw = properties.get("status", b"okay\0")
    if not raw.endswith(b"\0") or b"\0" in raw[:-1]:
        raise ValueError("malformed node status")
    return raw[:-1].decode("ascii")


def union_size(regions):
    end, total = 0, 0
    for region in sorted(regions, key=lambda item: item["start"]):
        total += max(0, region["end_exclusive"] - max(end, region["start"]))
        end = max(end, region["end_exclusive"])
    return total


def inspect_tree(tree):
    nodes = tree["nodes"]
    root = nodes["/"]
    address_cells, size_cells = width(root, "#address-cells"), width(root, "#size-cells")
    ram, disabled_memory = [], []
    for path, properties in nodes.items():
        if properties.get("device_type") != b"memory\0":
            continue
        if path.count("/") != 1:
            raise ValueError("memory node under a translated bus is unsupported")
        if status(properties) not in ("ok", "okay"):
            disabled_memory.append(path)
            continue
        ram.extend(tuples(properties.get("reg", b""), address_cells, size_cells, path))
    if not ram:
        raise ValueError("no enabled root memory nodes")
    if union_size(ram) != sum(region["size"] for region in ram):
        raise ValueError("overlapping declared RAM banks")
    fixed = [interval(int(item["address"], 16), int(item["size"], 16), "FDT reservation map")
             for item in tree["reservations"]]
    unresolved, inactive = [], []
    reserved = nodes.get("/reserved-memory")
    if reserved is not None:
        if status(reserved) not in ("ok", "okay"):
            raise ValueError("disabled reserved-memory parent requires separate review")
        if reserved.get("ranges") != b"":
            raise ValueError("reserved-memory requires explicit empty identity ranges")
        if (width(reserved, "#address-cells"), width(reserved, "#size-cells")) != (address_cells, size_cells):
            raise ValueError("reserved-memory cell widths must match root")
        for path, properties in nodes.items():
            if not path.startswith("/reserved-memory/"):
                continue
            if path.count("/") != 2:
                raise ValueError("nested reserved-memory layout is unsupported")
            node_status = status(properties)
            flags = [name for name in ("no-map", "reusable", "linux,remove-completely",
                     "linux,reserve-contiguous-region", "linux,reserve-region") if name in properties]
            for flag in ("no-map", "reusable"):
                if flag in properties and properties[flag] != b"":
                    raise ValueError(f"{path}: malformed boolean property {flag}")
            if "no-map" in properties and "reusable" in properties:
                raise ValueError(f"{path}: contradictory no-map and reusable")
            details = dict(source=path, status=node_status, flags=flags)
            if node_status not in ("ok", "okay"):
                inactive.append(details)
            if "reg" in properties:
                for region in tuples(properties["reg"], address_cells, size_cells, path):
                    if region["start"] == 0 and any(flag.startswith("linux,") for flag in flags):
                        unresolved.append(dict(details, reason="vendor zero-base reservation; not an approved physical address",
                                               requested_bytes=region["size"]))
                    else:
                        fixed.append(dict(region, status=node_status, flags=flags,
                                          conservative_exclusion=True))
            elif "size" in properties:
                requested = scalar(properties["size"], size_cells)
                if not requested:
                    raise ValueError(f"{path}: zero dynamic reservation size")
                entry = dict(details, reason="dynamic allocation has no DT physical address", requested_bytes=requested)
                if "alignment" in properties:
                    alignment = scalar(properties["alignment"], size_cells)
                    if not alignment or alignment & (alignment - 1):
                        raise ValueError(f"{path}: invalid dynamic alignment")
                    entry["alignment"] = alignment
                if "alloc-ranges" in properties:
                    entry["allocation_constraints_not_reservations"] = tuples(
                        properties["alloc-ranges"], address_cells, size_cells, path)
                unresolved.append(entry)
            else:
                unresolved.append(dict(details, reason="reservation without reg or size"))
    outside = [region for region in fixed if not any(
        bank["start"] <= region["start"] and region["end_exclusive"] <= bank["end_exclusive"] for bank in ram)]
    return dict(
        purpose="saved DT evidence inventory, NOT a current usable-memory map",
        ram_banks=ram, declared_ram_bytes=sum(region["size"] for region in ram),
        fixed_reservations=fixed, unresolved_reservations=unresolved,
        inactive_reservation_nodes=inactive, disabled_memory_nodes=disabled_memory,
        fixed_reservations_not_contained_in_one_bank=outside,
        fixed_reserved_union_bytes=union_size(fixed),
        recommended_load_address=None, usable_memory_ranges=None,
        boot_approved=False, platform_memory_approved=False,
        blockers=[
            "saved recovery tree is not a current loader allocation snapshot",
            "dynamic and vendor reservations need runtime placement evidence",
            "loader, input kernel, boot_args, device tree, stacks and page tables need explicit reservations",
            "firmware and secure-world ownership is not established by this inventory",
            "inactive fixed reservations are conservatively retained, not reclaimed",
        ],
    )


def inspect_blob(blob):
    result = inspect_tree(parse_fdt(blob))
    result.update(dtb_sha256=hashlib.sha256(blob).hexdigest(), dtb_bytes=len(blob))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dtb", type=Path)
    args = parser.parse_args()
    try:
        report = inspect_blob(args.dtb.read_bytes())
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"memory inventory rejected: {error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
