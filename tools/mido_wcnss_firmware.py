"""Inspect local Pronto firmware without loading it or exposing calibration."""

import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mido_gpu_firmware import inspect_split
from inspect_boot import parse_fdt


def inspect_board(nodes, firmware):
    pronto = nodes["/soc/qcom,pronto@a21b000"]
    wlan = nodes["/soc/qcom,wcnss-wlan@0a000000"]
    if pronto.get("qcom,pas-id") != struct.pack(">I", 6):
        raise ValueError("Board does not identify Pronto PAS6")
    if "qcom,is-pronto-v3" not in wlan:
        raise ValueError("Expected own-device Pronto-v3 binding")
    phandle = pronto.get("memory-region")
    if phandle is None or len(phandle) != 4:
        raise ValueError("Pronto memory-region is missing or invalid")
    matches = [(name, node) for name, node in nodes.items()
               if node.get("phandle") == phandle and name.startswith("/reserved-memory/")]
    if len(matches) != 1:
        raise ValueError("Pronto memory-region is not uniquely reserved")
    parent = nodes["/reserved-memory"]
    if any(parent.get(field) != struct.pack(">I", 2)
           for field in ("#address-cells", "#size-cells")):
        raise ValueError("Unsupported reserved-memory cell dimensions")
    name, region = matches[0]
    if "no-map" not in region or len(region.get("reg", b"")) != 16:
        raise ValueError("Expected a single no-map firmware reservation")
    base, size = struct.unpack(">QQ", region["reg"])
    if not size or base + size > 1 << 32 or base & 4095:
        raise ValueError("Invalid Pronto reservation extent")
    if firmware["allocation_bytes"] > size:
        raise ValueError("Pronto firmware exceeds reserved memory")
    plan = []
    for segment in firmware["segments"]:
        destination = base + segment["link_address"] - firmware["link_base"]
        if destination < base or destination + segment["memory_size"] > base + size:
            raise ValueError("Relocated segment outside reserved memory")
        if segment["alignment"] > 1 and (base - firmware["link_base"]) % segment["alignment"]:
            raise ValueError("Relocation breaks segment alignment")
        plan.append({"index": segment["index"], "destination": destination,
                     "copy_bytes": segment["file_size"],
                     "zero_bytes": segment["memory_size"] - segment["file_size"]})
    return {"pas_id": 6, "binding": "Pronto-v3", "reservation": name,
            "physical_base": base, "reserved_bytes": size,
            "relocation_delta": base - firmware["link_base"], "segments": plan,
            "allocation_verified_on_device": False, "hardware_accessed": False}


def inspect_power_dependencies(nodes):
    wlan = nodes["/soc/qcom,wcnss-wlan@0a000000"]
    pronto = nodes["/soc/qcom,pronto@a21b000"]

    def cells(value, count):
        if len(value) != count * 4:
            raise ValueError("Invalid dependency cell count")
        return struct.unpack(">" + "I" * count, value)

    def reference(value):
        cells(value, 1)
        matches = [(path, node) for path, node in nodes.items()
                   if node.get("phandle") == value]
        if len(matches) != 1:
            raise ValueError("Dependency phandle is not unique")
        return matches[0]

    supplies = []
    for role in ("pronto-vddmx", "pronto-vddcx", "pronto-vddpx",
                 "iris-vddxo", "iris-vddrfa", "iris-vddpa", "iris-vdddig"):
        path, regulator = reference(wlan["qcom," + role + "-supply"])
        parent = nodes[path.rsplit("/", 1)[0]]
        resource = parent["qcom,resource-name"].rstrip(b"\x00").decode("ascii")
        if resource not in ("ldoa", "smpa"):
            raise ValueError("Unsupported Pronto RPM supply resource")
        resource_id, = cells(parent["qcom,resource-id"], 1)
        sets, = cells(regulator["qcom,set"], 1)
        minimum, = cells(regulator["regulator-min-microvolt"], 1)
        maximum, = cells(regulator["regulator-max-microvolt"], 1)
        voltage_key = "qcom," + role.removeprefix("pronto-") + "-voltage-level"
        low, off, high = cells(wlan[voltage_key], 3)
        if not resource_id or sets not in (1, 3) or off != 0 or not minimum <= low <= high <= maximum:
            raise ValueError("Invalid Pronto supply constraints")
        current_key = "qcom," + role + "-current"
        current, = cells(wlan[current_key], 1)
        supplies.append({"role": role, "node": path, "resource": resource,
                         "resource_id": resource_id, "sets": sets,
                         "voltage_units": "rpm-level" if "qcom,use-voltage-level" in regulator else "microvolt",
                         "minimum": low, "maximum": high, "load_microamp": current})
    proxy_path, _ = reference(pronto["vdd_pronto_pll-supply"])
    xo = next(supply for supply in supplies if supply["role"] == "iris-vddxo")
    if proxy_path != xo["node"]:
        raise ValueError("Pronto proxy PLL and IRIS XO supply differ")
    proxy_uv, proxy_load = cells(pronto["vdd_pronto_pll-uV-uA"], 2)
    if xo["voltage_units"] != "microvolt" or not xo["minimum"] <= proxy_uv <= xo["maximum"]:
        raise ValueError("Pronto proxy voltage outside IRIS constraints")
    clock_names = pronto["clock-names"].rstrip(b"\x00").decode("ascii").split("\x00")
    clocks = cells(pronto["clocks"], 2 * len(clock_names))
    if len(set(clock_names)) != len(clock_names):
        raise ValueError("Duplicate Pronto clock names")
    clock_plan = []
    for index, name in enumerate(clock_names):
        provider = struct.pack(">I", clocks[index * 2])
        provider_path, node = reference(provider)
        if cells(node["#clock-cells"], 1) != (1,):
            raise ValueError("Unsupported Pronto clock provider")
        clock_plan.append({"name": name, "provider": provider_path, "id": clocks[index * 2 + 1]})
    proxy_names = pronto["qcom,proxy-clock-names"].rstrip(b"\x00").decode("ascii").split("\x00")
    if not set(proxy_names).issubset(clock_names):
        raise ValueError("Unresolved Pronto proxy clock")
    shared = {}
    for supply in supplies:
        key = (supply["resource"], supply["resource_id"])
        shared.setdefault(key, []).append(supply["role"])
    rate, = cells(pronto["qcom,scm_core_clk_src"], 1)
    return {"supplies": supplies, "proxy_pll": {"node": proxy_path, "voltage_microvolt": proxy_uv,
            "load_microamp": proxy_load}, "clocks": clock_plan, "proxy_clocks": proxy_names,
            "scm_core_rate_hz": rate, "hardware_accessed": False,
            "shared_supply_groups": [{"resource": resource, "resource_id": number, "roles": roles}
                                     for (resource, number), roles in shared.items() if len(roles) > 1],
            "requires_shared_supply_vote_aggregation": True}

def inspect_bundle(directory):
    result = inspect_split(directory, "wcnss", 40, 6)
    segments = result["segments"]
    if not all(segment["relocatable"] for segment in segments):
        raise ValueError("Expected relocatable Pronto load segments")
    first = min(segment["link_address"] for segment in segments)
    end = max(segment["link_address"] + segment["memory_size"] for segment in segments)
    result["link_base"] = first
    result["allocation_bytes"] = ((end + 4095) & ~4095) - first
    result["zero_fill_bytes"] = sum(segment["memory_size"] - segment["file_size"]
                                    for segment in segments)
    result["network_ready"] = False
    result["requires"] = ["reserved non-overlapping physical allocation",
                          "board-specific Pronto power/reset/clock sequence",
                          "SCM PAS6 authentication and startup",
                          "WCNSS SMD control and own-device NV calibration",
                          "DXE DMA/interrupts and WLAN protocol driver",
                          "XNU network interface and iOS integration"]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--dtb", type=Path)
    parser.add_argument("--power-plan", action="store_true")
    args = parser.parse_args()
    try:
        result = inspect_bundle(args.directory)
        if args.dtb:
            nodes = parse_fdt(args.dtb.read_bytes())["nodes"]
            result["board_plan"] = inspect_board(nodes, result)
            if args.power_plan:
                result["power_dependencies"] = inspect_power_dependencies(nodes)
        elif args.power_plan:
            raise ValueError("--power-plan requires --dtb")
    except (OSError, ValueError, KeyError, struct.error) as error:
        parser.exit(1, f"WCNSS inspection failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
