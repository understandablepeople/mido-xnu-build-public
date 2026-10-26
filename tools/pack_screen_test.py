"""Package a mido RAM-only screen experiment; never connect to a phone."""

import argparse
import hashlib
import json
from pathlib import Path
import struct

from inspect_boot import align, parse_boot, parse_fdt


RECOVERY_DTB_SHA256 = "d595c03a0fc5a55b78451b0d761a357682fb5cf86ac7629b52d9977b6551b420"
CMDLINE = b"mido-screen-test lk2nd.pass-simplefb=keep"


def make_tree(reference):
    if hashlib.sha256(reference).hexdigest() != RECOVERY_DTB_SHA256:
        raise ValueError("Expected the verified original mido recovery DTB")
    root = parse_fdt(reference)["nodes"]["/"]
    if root["qcom,msm-id"] != struct.pack(">II", 293, 0) or root["qcom,board-id"] != struct.pack(">II", 11, 0):
        raise ValueError("Unexpected mido identification")
    strings = bytearray()
    structure = bytearray()
    names = {}

    def cell(number):
        return struct.pack(">I", number)

    def begin(name):
        structure.extend(cell(1) + name.encode("ascii") + b"\0")
        structure.extend(bytes(align(len(structure), 4) - len(structure)))

    def end():
        structure.extend(cell(2))

    def prop(name, value):
        if name not in names:
            names[name] = len(strings)
            strings.extend(name.encode("ascii") + b"\0")
        structure.extend(struct.pack(">III", 3, len(value), names[name]) + value)
        structure.extend(bytes(align(len(structure), 4) - len(structure)))

    begin("")
    prop("compatible", b"mido,arm64-screen-test\0")
    prop("model", b"Mido ARM64 RAM screen test - NOT iOS\0")
    prop("#address-cells", cell(2))
    prop("#size-cells", cell(2))
    prop("qcom,msm-id", root["qcom,msm-id"])
    prop("qcom,board-id", root["qcom,board-id"])
    begin("memory")
    prop("device_type", b"memory\0")
    prop("reg", bytes(16))
    end()
    begin("chosen")
    prop("#address-cells", cell(2))
    prop("#size-cells", cell(2))
    end()
    begin("reserved-memory")
    prop("#address-cells", cell(2))
    prop("#size-cells", cell(2))
    prop("ranges", b"")
    end()
    end()
    structure.extend(cell(9))
    strings_offset = 56 + len(structure)
    total = strings_offset + len(strings)
    header = struct.pack(">10I", 0xD00DFEED, total, 56, strings_offset, 40, 17, 16, 0, len(strings), len(structure))
    result = header + bytes(16) + structure + strings
    parse_fdt(result)
    return result


def validate_payload(payload):
    if len(payload) < 4096 or len(payload) >= 65536 or len(payload) % 16:
        raise ValueError("Unexpected payload length or alignment")
    if payload[56:60] != b"ARM\x64":
        raise ValueError("Missing ARM64 Image magic")
    text_offset, image_size, flags = struct.unpack_from("<QQQ", payload, 8)
    if text_offset != 0x80000 or image_size != len(payload) or flags != 0:
        raise ValueError("Unexpected ARM64 placement, size or flags")
    if struct.unpack_from("<I", payload, 44)[0] != len(payload):
        raise ValueError("Qualcomm appended-DTB offset does not match payload length")
    if struct.unpack_from("<I", payload)[0] != 0x14000010:
        raise ValueError("Unexpected entry branch")


def make_image(payload, dtb):
    validate_payload(payload)
    parse_fdt(dtb)
    kernel = payload + dtb
    digest = hashlib.sha1(kernel + struct.pack("<I", len(kernel)) + bytes(8)).digest()
    header = struct.pack(
        "<8s10I16s512s32s1024s", b"ANDROID!", len(kernel), 0x10080000,
        0, 0x13600000, 0, 0, 0x13400000, 2048, 0, 0,
        b"mido-screen-test", CMDLINE, digest, b"",
    )
    result = header.ljust(2048, b"\0") + kernel.ljust(align(len(kernel), 2048), b"\0")
    _, parts = parse_boot(result)
    if parts["kernel"] != kernel or parts["ramdisk"] or parts["second"]:
        raise ValueError("Boot image round trip failed")
    return result


def package(payload_path, reference_path, output_path, diagnostics=False):
    payload = payload_path.read_bytes()
    tree = make_tree(reference_path.read_bytes())
    image = make_image(payload, tree)
    if output_path.exists():
        raise ValueError("Output exists; refusing to overwrite")
    output_path.mkdir(parents=True)
    (output_path / "screen-test.dtb").write_bytes(tree)
    (output_path / "mido-arm64-screen-test.img").write_bytes(image)
    report = {
        "purpose": "Experimental ARM64 " + ("exceptions/counter" if diagnostics else "screen") + " test, NOT iOS; not hardware validated",
        "diagnostics": diagnostics,
        "loader": "Temporary lk2nd-msm8953 23.1 only; not stock fastboot",
        "cmdline": CMDLINE.decode("ascii"),
        "payload_bytes": len(payload),
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "reference_dtb_sha256": RECOVERY_DTB_SHA256,
        "image_bytes": len(image),
        "image_sha256": hashlib.sha256(image).hexdigest(),
        "device_commands_executed": False,
    }
    (output_path / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path)
    parser.add_argument("reference_dtb", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--diagnostics", action="store_true")
    args = parser.parse_args()
    print(json.dumps(package(args.payload, args.reference_dtb, args.output, args.diagnostics), indent=2))


if __name__ == "__main__":
    main()
