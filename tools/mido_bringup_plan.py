"""Check own-board bring-up dependencies without issuing hardware requests."""

import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from inspect_boot import parse_fdt
from mido_gpu_firmware import inspect_bundle as inspect_gpu
from mido_wcnss_firmware import inspect_board, inspect_bundle, inspect_power_dependencies


def aggregate_supplies(supplies, existing=()):
    groups = {}
    for supply in list(supplies) + list(existing):
        if supply["sets"] not in (1, 3) or supply["voltage_units"] not in ("rpm-level", "microvolt"):
            raise ValueError("Unsupported vote units or sets")
        if not 0 < supply["minimum"] <= supply["maximum"]:
            raise ValueError("Invalid vote limits")
        for selected in (1, 2):
            if not supply["sets"] & selected:
                continue
            key = (supply["resource"], supply["resource_id"], selected)
            group = groups.setdefault(key, {"resource": key[0], "resource_id": key[1],
                "set": selected, "units": supply["voltage_units"], "minimum": 0,
                "maximum": supply["maximum"], "roles": []})
            if group["units"] != supply["voltage_units"]:
                raise ValueError("Shared rail mixes voltage units")
            group["minimum"] = max(group["minimum"], supply["minimum"])
            group["maximum"] = min(group["maximum"], supply["maximum"])
            group["roles"].append(supply["role"])
            if group["minimum"] > group["maximum"]:
                raise ValueError("Shared rail constraints conflict")
    return [groups[key] for key in sorted(groups)]


def check_reservation(base, size, occupied):
    if base < 0 or size <= 0 or base + size > 1 << 32 or base & 4095 or size & 4095:
        raise ValueError("Invalid reserved extent")
    for name, start, length in occupied:
        if start < 0 or length <= 0 or start + length > 1 << 64:
            raise ValueError("Invalid occupied extent")
        if base < start + length and start < base + size:
            raise ValueError("Pronto reservation overlaps " + name)
    return True


def payload_ranges(payload):
    if len(payload) < 680 or payload[:8] != b"SWEETXNU":
        raise ValueError("Invalid payload header")
    version, count = struct.unpack_from("<II", payload, 8)
    virtual, _, adt_offset, adt_size, kernel_end, physical, memory_size = struct.unpack_from("<7Q", payload, 16)
    if version != 1 or not 1 <= count <= 64 or len(payload) < 680 + count * 32:
        raise ValueError("Unsupported payload table")
    if not memory_size or adt_offset > len(payload) or adt_size > len(payload) - adt_offset:
        raise ValueError("Invalid payload memory or ADT extent")
    top = ((physical + kernel_end - virtual + adt_size + 16383) & ~16383) + 16384
    if kernel_end < virtual or top > physical + memory_size:
        raise ValueError("Boot data outside XNU arena")
    for index in range(count):
        address, size, offset, stored = struct.unpack_from("<4Q", payload, 680 + index * 32)
        destination = physical + address - virtual
        if address < virtual or stored > size or offset > len(payload) or stored > len(payload) - offset:
            raise ValueError("Invalid payload segment")
        if destination + size > physical + memory_size:
            raise ValueError("Payload segment outside XNU arena")
    return [("XNU arena including boot data", physical, memory_size)]


def inspect(directory, dtb, payload):
    nodes = parse_fdt(Path(dtb).read_bytes())["nodes"]
    wifi = inspect_bundle(directory)
    gpu = inspect_gpu(directory)
    board = inspect_board(nodes, wifi)
    power = inspect_power_dependencies(nodes)
    expected_clocks = {"xo": 0x89dae6d0, "scm_core_clk": 0x00d390d2,
                       "scm_iface_clk": 0x94de4919, "scm_bus_clk": 0xd4415c9b,
                       "scm_core_clk_src": 0x37a21414}
    if {clock["name"]: clock["id"] for clock in power["clocks"]} != expected_clocks or any(
            clock["provider"] != "/soc/qcom,gcc@1800000" for clock in power["clocks"]):
        raise ValueError("Own-board SCM clock binding differs from pinned 8953 header")
    gpu_node = nodes["/soc/qcom,kgsl-3d0@1c00000"]
    if gpu_node.get("reg") != struct.pack(">II", 0x01c00000, 0x40000):
        raise ValueError("GPU aperture differs from read-only status mapping")
    if gpu_node.get("clock-names", b"").rstrip(b"\x00").split(b"\x00") != [
            b"core_clk", b"iface_clk", b"mem_iface_clk", b"alt_mem_iface_clk",
            b"rbbmtimer_clk", b"alwayson_clk"]:
        raise ValueError("GPU branch dependencies differ from own-board binding")
    occupied = payload_ranges(Path(payload).read_bytes())
    occupied += [("shim temporary kernel", 0x10080000, 0x10000),
                 ("lk2nd tags", 0x13400000, 0x100000),
                 ("lk2nd payload", 0x13600000, Path(payload).stat().st_size),
                 ("framebuffer", 0x90000000, 0x600000)]
    reservation = board["reservation"]
    for path, node in nodes.items():
        raw = node.get("reg", b"")
        if path.startswith("/reserved-memory/") and path != reservation and len(raw) == 16:
            start, length = struct.unpack(">QQ", raw)
            if length:
                occupied.append((path, start, length))
    check_reservation(board["physical_base"], board["reserved_bytes"], occupied)
    existing = [{"role": "existing GPU initial CX floor", "resource": "smpa", "resource_id": 2,
                 "sets": 1, "voltage_units": "rpm-level", "minimum": 192, "maximum": 384}]
    votes = aggregate_supplies(power["supplies"], existing)
    return {"reservation_nonoverlap": True, "occupied_ranges_checked": len(occupied),
            "reservation_source": "own DT plus packaged payload; not runtime ownership proof",
            "gpu_files_checked": len(gpu["files"]), "wifi_files_checked": len(wifi["files"]),
            "aggregated_voltage_floors": votes, "proxy_clocks": power["clocks"],
            "proxy_pll": power["proxy_pll"], "scm_core_rate_hz": power["scm_core_rate_hz"],
            "proxy_load_and_xo_vote_integration": "still required before firmware startup",
            "hardware_accessed": False, "writes_authorized_by_plan": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--dtb", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = inspect(args.directory, args.dtb, args.payload)
    except (OSError, ValueError, KeyError, struct.error) as error:
        parser.exit(1, f"Bring-up plan rejected: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
