"""Validate a local A506 split firmware set without loading or publishing it."""

import argparse
import hashlib
import json
from pathlib import Path
import struct


ELF_HEADER = struct.Struct("<16sHHIIIIIHHHHHH")
PROGRAM_HEADER = struct.Struct("<8I")
HASH_TYPE = 2
RELOCATABLE = 1 << 27
MAX_FIRMWARE_SIZE = 16 * 1024 * 1024


def read_firmware(path):
    if path.stat().st_size > MAX_FIRMWARE_SIZE:
        raise ValueError("Firmware file exceeds the inspection size limit")
    return path.read_bytes()


def describe(blob):
    return {"size": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}


def inspect_zap(directory):
    directory = Path(directory)
    metadata = read_firmware(directory / "a506_zap.mdt")
    if len(metadata) < ELF_HEADER.size:
        raise ValueError("Truncated ELF header")
    header = ELF_HEADER.unpack_from(metadata)
    ident, kind, machine, version, entry, phoff, _, _, ehsize, phsize, count, _, _, _ = header
    if ident[:7] != b"\x7fELF\x01\x01\x01" or version != 1:
        raise ValueError("Expected little-endian ELF32 version 1")
    if kind != 2 or machine != 164:
        raise ValueError("Expected Qualcomm Hexagon executable")
    if ehsize != ELF_HEADER.size or phsize != PROGRAM_HEADER.size or not 1 <= count <= 32:
        raise ValueError("Unsupported ELF header or program table dimensions")
    table_end = phoff + count * phsize
    if phoff < ehsize or table_end > len(metadata):
        raise ValueError("Program header table outside metadata")
    segments = []
    hashes = []
    files = {"a506_zap.mdt": describe(metadata)}
    for index in range(count):
        segment = PROGRAM_HEADER.unpack_from(metadata, phoff + index * phsize)
        segment_type, offset, _, address, size, memory_size, flags, alignment = segment
        if size > MAX_FIRMWARE_SIZE or memory_size > MAX_FIRMWARE_SIZE:
            raise ValueError("Segment exceeds the inspection size limit")
        if alignment and alignment & (alignment - 1):
            raise ValueError("Segment alignment is not a power of two")
        if (flags >> 24) & 7 == HASH_TYPE:
            hashes.append((index, size))
            continue
        if segment_type != 1:
            continue
        if size > memory_size or address + memory_size > 1 << 32:
            raise ValueError("Invalid loadable segment extent")
        if not memory_size:
            continue
        name = f"a506_zap.b{index:02d}"
        blob = read_firmware(directory / name) if size else b""
        if len(blob) != size:
            raise ValueError(f"Split segment size mismatch: {name}")
        if size:
            files[name] = describe(blob)
        segments.append({"index": index, "file": name if size else None,
                         "elf_offset": offset, "link_address": address,
                         "file_size": size, "memory_size": memory_size,
                         "alignment": alignment, "relocatable": bool(flags & RELOCATABLE)})
    if len(hashes) != 1 or not segments:
        raise ValueError("Expected one authentication segment and loadable firmware")
    hash_index, hash_size = hashes[0]
    if len(metadata) != table_end + hash_size:
        raise ValueError("Unexpected packed MDT authentication layout")
    hash_name = f"a506_zap.b{hash_index:02d}"
    authentication = read_firmware(directory / hash_name)
    if len(authentication) != hash_size or metadata[table_end:] != authentication:
        raise ValueError("MDT authentication data differs from split hash segment")
    files[hash_name] = describe(authentication)
    if read_firmware(directory / "a506_zap.b00") != metadata[:table_end]:
        raise ValueError("Split ELF header differs from MDT")
    files["a506_zap.b00"] = describe(metadata[:table_end])
    ordered = sorted(segments, key=lambda segment: segment["link_address"])
    for previous, following in zip(ordered, ordered[1:]):
        if previous["link_address"] + previous["memory_size"] > following["link_address"]:
            raise ValueError("Overlapping loadable segments")
    if not any(segment["link_address"] <= entry < segment["link_address"] + segment["memory_size"]
               for segment in segments):
        raise ValueError("Entry point outside loadable firmware")
    return {"pas_id": 13, "firmware": "a506_zap", "entry": entry, "files": files,
            "segments": segments, "signature_verified": False, "hardware_loaded": False,
            "requires": ["reserved non-overlapping physical allocation",
                         "SCM PAS authentication on the device",
                         "mido GFX-LDO, CX/GX domains and clocks",
                         "GPU SMMU mapping before command submission"]}


def inspect_bundle(directory):
    result = inspect_zap(directory)
    for name in ("a530_pfp.fw", "a530_pm4.fw"):
        blob = read_firmware(Path(directory) / name)
        if len(blob) < 8 or len(blob) % 4:
            raise ValueError(f"Invalid microcode word layout: {name}")
        result["files"][name] = describe(blob)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    try:
        result = inspect_bundle(args.directory)
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f"Firmware inspection failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
