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
    args = parser.parse_args()
    try:
        result = inspect_bundle(args.directory)
        if args.dtb:
            result["board_plan"] = inspect_board(parse_fdt(args.dtb.read_bytes())["nodes"], result)
    except (OSError, ValueError, KeyError, struct.error) as error:
        parser.exit(1, f"WCNSS inspection failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
