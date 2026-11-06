"""Attach a private Pronto bundle to a copy of a shim payload, without device access."""

import argparse
import hashlib
import json
from pathlib import Path
import struct

import adt
from mido_bringup_plan import check_reservation, payload_ranges
from mido_pronto_stage import BASE, SIZE


def attach(payload, bundle):
    occupied = payload_ranges(payload)
    check_reservation(BASE, SIZE, occupied)
    if len(bundle) < 56 or len(bundle) > 0x1000000:
        raise ValueError("Invalid Pronto bundle size")
    magic, version, count, allocation, metadata_physical, metadata_offset, metadata_bytes, total = struct.unpack_from("<8sII5Q", bundle)
    if magic != b"MIDOPRNT" or version != 1 or not 1 <= count <= 32 or total != len(bundle):
        raise ValueError("Invalid Pronto bundle header")
    table_end = 56 + count * 32
    if (not allocation or allocation & 4095 or allocation > SIZE or
            metadata_physical & 4095 or metadata_physical < BASE + allocation or
            not 0 < metadata_bytes <= 65536 or metadata_physical + metadata_bytes > BASE + SIZE or
            not table_end <= metadata_offset <= len(bundle) or metadata_bytes > len(bundle) - metadata_offset):
        raise ValueError("Invalid Pronto metadata layout")
    physical_ranges = []
    source_ranges = [(metadata_offset, metadata_bytes)]
    for index in range(count):
        physical, offset, size, memory = struct.unpack_from("<4Q", bundle, 56 + index * 32)
        if (not memory or size > memory or physical < BASE or physical + memory > BASE + allocation or
                (size and (offset < table_end or offset > len(bundle) or size > len(bundle) - offset)) or
                (not size and offset)):
            raise ValueError("Invalid Pronto segment")
        for previous, length in physical_ranges:
            if physical < previous + length and previous < physical + memory:
                raise ValueError("Overlapping Pronto destinations")
        for previous, length in source_ranges:
            if size and offset < previous + length and previous < offset + size:
                raise ValueError("Overlapping Pronto sources")
        physical_ranges.append((physical, memory))
        if size:
            source_ranges.append((offset, size))
    adt_offset, adt_size = struct.unpack_from("<QQ", payload, 32)
    root, consumed = adt.parse(payload[adt_offset:adt_offset + adt_size])
    if consumed != adt_size:
        raise ValueError("Unexpected ADT trailing bytes")
    chosen = [child for child in root.children if child.name == "chosen"]
    if len(chosen) != 1 or chosen[0].prop("mido-pronto-bundle") is not None:
        raise ValueError("Missing/ambiguous chosen or bundle already attached")
    dram_base = chosen[0].prop("dram-base")
    dram_size = chosen[0].prop("dram-size")
    physical, memory = struct.unpack_from("<QQ", payload, 56)
    if dram_base != struct.pack("<Q", physical) or dram_size != struct.pack("<Q", memory):
        raise ValueError("Payload and ADT memory arenas disagree")
    chosen[0].props.append(("mido-pronto-bundle", 0, bundle))
    changed = adt.serialize(root)
    output = bytearray(payload)
    output += bytes(-len(output) & 15)
    new_offset = len(output)
    output += changed
    output += bytes(-len(output) & 15)
    struct.pack_into("<QQ", output, 32, new_offset, len(changed))
    payload_ranges(output)
    return bytes(output), {"bundle_sha256": hashlib.sha256(bundle).hexdigest(),
                           "bundle_bytes": len(bundle), "adt_bytes": len(changed),
                           "device_written": False, "boot_arguments_changed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("Output exists; original payload will not be overwritten")
        result, report = attach(args.payload.read_bytes(), args.bundle.read_bytes())
        with args.output.open("xb") as target:
            target.write(result)
    except (OSError, ValueError, KeyError, struct.error, StopIteration, UnicodeError) as error:
        parser.exit(1, f"Pronto attachment rejected: {error}\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
