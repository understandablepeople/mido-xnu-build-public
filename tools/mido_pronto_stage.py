"""Prepare a private Pronto image descriptor; never write device memory or invoke PAS."""

import argparse
import hashlib
import json
from pathlib import Path
import struct

from inspect_boot import parse_fdt
from mido_bringup_plan import check_reservation, payload_ranges
from mido_wcnss_firmware import inspect_board, inspect_bundle

BASE = 0x8E700000
SIZE = 0x700000


def prepare(directory, nodes, payload):
    directory = Path(directory)
    firmware = inspect_bundle(directory)
    board = inspect_board(nodes, firmware)
    if (board["physical_base"], board["reserved_bytes"]) != (BASE, SIZE):
        raise ValueError("Expected own mido Pronto reservation")
    check_reservation(BASE, SIZE, payload_ranges(payload))
    blobs = {}
    for name, expected in firmware["files"].items():
        blob = (directory / name).read_bytes()
        if len(blob) != expected["size"] or hashlib.sha256(blob).hexdigest() != expected["sha256"]:
            raise ValueError("Firmware changed during preparation: " + name)
        blobs[name] = blob
    metadata = blobs["wcnss.mdt"]
    metadata_physical = (BASE + SIZE - len(metadata)) & ~4095
    if not metadata or len(metadata) > 65536 or metadata_physical < BASE + firmware["allocation_bytes"]:
        raise ValueError("No separate aligned metadata space in Pronto reservation")
    if not 1 <= len(board["segments"]) <= 32:
        raise ValueError("Unsupported Pronto segment count")
    lines = ["#ifndef MIDO_PRIVATE_PRONTO_IMAGE_H", "#define MIDO_PRIVATE_PRONTO_IMAGE_H",
             '#include "mido_wcnss_loader.h"', ""]

    def array(name, blob):
        lines.append("static const uint8_t " + name + "[] = {")
        for offset in range(0, len(blob), 24):
            lines.append("    " + ", ".join("0x%02x" % value for value in blob[offset:offset + 24]) + ",")
        lines.append("};")

    array("mido_pronto_metadata", metadata)
    for segment in firmware["segments"]:
        if segment["file_size"]:
            array("mido_pronto_segment_" + str(segment["index"]), blobs[segment["file"]])
    lines.append("static const struct mido_pronto_segment mido_pronto_segments[] = {")
    for segment in board["segments"]:
        data = "mido_pronto_segment_" + str(segment["index"]) if segment["copy_bytes"] else "0"
        lines.append("    {0x%xULL, %s, %d, %d}," % (segment["destination"], data,
                     segment["copy_bytes"], segment["copy_bytes"] + segment["zero_bytes"]))
    lines += ["};", "static const struct mido_pronto_image mido_pronto_image = {",
              "    mido_pronto_metadata, sizeof(mido_pronto_metadata), 0x%xULL," % metadata_physical,
              "    %d, mido_pronto_segments, %d" % (firmware["allocation_bytes"], len(board["segments"])),
              "};", "#endif", ""]
    report = {"board_plan": board, "files": firmware["files"],
              "metadata_physical": metadata_physical, "metadata_bytes": len(metadata),
              "allocation_bytes": firmware["allocation_bytes"], "hardware_written": False,
              "pas_authentication_established": False, "network_ready": False}
    return "\n".join(lines), report


def encode_bundle(directory, report):
    directory = Path(directory)

    def checked(name):
        blob = (directory / name).read_bytes()
        expected = report["files"][name]
        if len(blob) != expected["size"] or hashlib.sha256(blob).hexdigest() != expected["sha256"]:
            raise ValueError("Firmware changed during bundle creation: " + name)
        return blob

    segments = report["board_plan"]["segments"]
    output = bytearray(56 + 32 * len(segments))
    metadata_offset = len(output)
    metadata = checked("wcnss.mdt")
    output += metadata
    output += bytes(-len(output) & 7)
    for index, segment in enumerate(segments):
        size = segment["copy_bytes"]
        offset = len(output) if size else 0
        if size:
            output += checked("wcnss.b%02d" % segment["index"])
            output += bytes(-len(output) & 7)
        struct.pack_into("<4Q", output, 56 + index * 32, segment["destination"], offset,
                         size, size + segment["zero_bytes"])
    struct.pack_into("<8sII5Q", output, 0, b"MIDOPRNT", 1, len(segments),
                     report["allocation_bytes"], report["metadata_physical"],
                     metadata_offset, len(metadata), len(output))
    if len(output) > 0x1000000:
        raise ValueError("Pronto bundle exceeds parser limit")
    return bytes(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--dtb", type=Path, required=True)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        header, report = prepare(args.directory, parse_fdt(args.dtb.read_bytes())["nodes"],
                                 args.payload.read_bytes())
        args.output.mkdir(parents=True, exist_ok=False)
        bundle = encode_bundle(args.directory, report)
        (args.output / "pronto.bin").write_bytes(bundle)
        report["bundle_sha256"] = hashlib.sha256(bundle).hexdigest()
        (args.output / "mido_private_pronto_image.h").write_text(header, encoding="ascii")
        (args.output / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, struct.error) as error:
        parser.exit(1, f"Pronto staging rejected: {error}\n")
    print("Private host-only image prepared; no PAS calls or device writes: " + str(args.output))


if __name__ == "__main__":
    main()
