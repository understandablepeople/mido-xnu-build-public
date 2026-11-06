"""Inspect local Pronto firmware without loading it or exposing calibration."""

import argparse
import json
from pathlib import Path
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mido_gpu_firmware import inspect_split


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
    args = parser.parse_args()
    try:
        result = inspect_bundle(args.directory)
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f"WCNSS inspection failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
