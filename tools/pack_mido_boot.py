#!/usr/bin/env python3
"""Package the mido XNU shim + SWEETXNU payload as an lk2nd boot image (header v0).

  pack_mido_boot.py SHIM.bin PAYLOAD OUTDIR [--reference-dtb DTB]

Derived from tools/pack_screen_test.py of the old repo (same validated Image
header checks, DTB scaffold and v0 header) and extended with a ramdisk = the
payload built by tools/mkpayload.py. Host-side only; never touches a device.

  kernel  (0x10080000) = shim Image + appended DTB (lk2nd picks the DTB by qcom,msm-id/board-id)
  tags    (0x13400000) = lk2nd copies the DTB here and rewrites /chosen (initrd props)
  ramdisk (0x13600000) = SWEETXNU payload; the shim reads /chosen linux,initrd-start/-end
                         (lk2nd dev_tree.c update_device_tree) and falls back to 0x13600000
"""
import argparse, hashlib, json, os, struct, sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from inspect_boot import align, parse_boot, parse_fdt  # noqa: E402

RECOVERY_DTB_SHA256 = "d595c03a0fc5a55b78451b0d761a357682fb5cf86ac7629b52d9977b6551b420"
CMDLINE = b"mido-xnu-shim lk2nd.pass-simplefb=keep"
PAGE_SIZE = 2048
KERNEL_ADDR, TAGS_ADDR, RAMDISK_ADDR = 0x10080000, 0x13400000, 0x13600000
MAX_SHIM = 65536
PAYLOAD_MAGIC = b"SWEETXNU"


def make_tree(reference=None):
    """Minimal DTB for lk2nd: identification, /memory, /chosen, /reserved-memory."""
    msm_id, board_id = struct.pack(">II", 293, 0), struct.pack(">II", 11, 0)
    if reference is not None:
        if hashlib.sha256(reference).hexdigest() != RECOVERY_DTB_SHA256:
            raise ValueError("Expected the verified original mido recovery DTB")
        root = parse_fdt(reference)["nodes"]["/"]
        if root["qcom,msm-id"] != msm_id or root["qcom,board-id"] != board_id:
            raise ValueError("Unexpected mido identification")
    strings, structure, names = bytearray(), bytearray(), {}
    cell = lambda n: struct.pack(">I", n)

    def pad():
        structure.extend(bytes(align(len(structure), 4) - len(structure)))

    def begin(name):
        structure.extend(cell(1) + name.encode("ascii") + b"\0")
        pad()

    def end():
        structure.extend(cell(2))

    def prop(name, value):
        if name not in names:
            names[name] = len(strings)
            strings.extend(name.encode("ascii") + b"\0")
        structure.extend(struct.pack(">III", 3, len(value), names[name]) + value)
        pad()

    begin("")
    prop("compatible", b"mido,xnu-shim\0")
    prop("model", b"Mido XNU shim - NOT Linux\0")
    prop("#address-cells", cell(2))
    prop("#size-cells", cell(2))
    prop("qcom,msm-id", msm_id)
    prop("qcom,board-id", board_id)
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


def validate_shim(shim):
    """Exact 64-byte arm64 Image header of mido/m1 (hardware-validated layout)."""
    if len(shim) < 4096 or len(shim) >= MAX_SHIM or len(shim) % 16:
        raise ValueError("Unexpected shim length or alignment")
    if shim[56:60] != b"ARM\x64":
        raise ValueError("Missing ARM64 Image magic")
    text_offset, image_size, flags = struct.unpack_from("<QQQ", shim, 8)
    if text_offset != 0x80000 or image_size != len(shim) or flags != 0:
        raise ValueError("Unexpected ARM64 placement, size or flags")
    if struct.unpack_from("<I", shim, 44)[0] != len(shim):
        raise ValueError("Qualcomm appended-DTB offset does not match shim length")
    if (struct.unpack_from("<I", shim)[0] >> 26) != 0b000101:
        raise ValueError("Entry is not a branch")


def validate_payload(payload):
    if len(payload) < 0x2a8 + 32 or payload[:8] != PAYLOAD_MAGIC:
        raise ValueError("Not a SWEETXNU payload")
    version, nsegs = struct.unpack_from("<II", payload, 8)
    if version != 1 or not 0 < nsegs <= 32:
        raise ValueError("Unsupported payload version/segment count")
    virt_base, entry_va, adt_off, adt_size, kernel_end, phys_base, mem_size = struct.unpack_from("<7Q", payload, 0x10)
    if adt_off + adt_size > len(payload):
        raise ValueError("ADT outside payload")
    if phys_base % 0x200000 or virt_base % 0x200000 or mem_size % 0x1000:
        raise ValueError("Payload is not 4K/2MiB aligned (built for 16K?)")
    if not (0x10000000 <= phys_base and phys_base + mem_size <= 0x80000000):
        raise ValueError("Arena outside free low RAM")
    if RAMDISK_ADDR + len(payload) > phys_base and RAMDISK_ADDR < phys_base + mem_size:
        raise ValueError("Ramdisk would overlap the kernel arena")
    return dict(phys_base=hex(phys_base), mem_size=hex(mem_size), entry_va=hex(entry_va), nsegs=nsegs)


def make_image(shim, dtb, payload):
    validate_shim(shim)
    validate_payload(payload)
    parse_fdt(dtb)
    kernel = shim + dtb
    digest = hashlib.sha1(kernel + struct.pack("<I", len(kernel)) + payload + struct.pack("<I", len(payload))
                          + struct.pack("<I", 0)).digest()
    header = struct.pack(
        "<8s10I16s512s32s1024s", b"ANDROID!", len(kernel), KERNEL_ADDR,
        len(payload), RAMDISK_ADDR, 0, 0, TAGS_ADDR, PAGE_SIZE, 0, 0,
        b"mido-xnu-shim", CMDLINE, digest, b"",
    )
    result = (header.ljust(PAGE_SIZE, b"\0") + kernel.ljust(align(len(kernel), PAGE_SIZE), b"\0")
              + payload.ljust(align(len(payload), PAGE_SIZE), b"\0"))
    _, parts = parse_boot(result)
    if parts["kernel"] != kernel or parts["ramdisk"] != payload or parts["second"]:
        raise ValueError("Boot image round trip failed")
    return result


def package(shim_path, payload_path, output_path, reference_path=None):
    shim, payload = Path(shim_path).read_bytes(), Path(payload_path).read_bytes()
    tree = make_tree(Path(reference_path).read_bytes() if reference_path else None)
    image = make_image(shim, tree, payload)
    if output_path.exists():
        raise ValueError("Output exists; refusing to overwrite")
    output_path.mkdir(parents=True)
    (output_path / "shim.dtb").write_bytes(tree)
    (output_path / "mido-xnu-shim.img").write_bytes(image)
    report = {
        "purpose": "Experimental XNU boot shim + payload for lk2nd RAM boot; NOT hardware validated",
        "loader": "lk2nd-msm8953 23.1 only (fastboot boot); not stock fastboot",
        "addresses": {"kernel": hex(KERNEL_ADDR), "tags": hex(TAGS_ADDR), "ramdisk": hex(RAMDISK_ADDR)},
        "cmdline": CMDLINE.decode("ascii"),
        "shim_bytes": len(shim), "shim_sha256": hashlib.sha256(shim).hexdigest(),
        "payload_bytes": len(payload), "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "payload": validate_payload(payload),
        "image_bytes": len(image), "image_sha256": hashlib.sha256(image).hexdigest(),
        "device_commands_executed": False,
    }
    (output_path / "manifest.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("shim", type=Path)
    ap.add_argument("payload", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--reference-dtb", type=Path, help="verified recovery DTB (sha256-checked) to cross-check ids")
    a = ap.parse_args()
    print(json.dumps(package(a.shim, a.payload, a.output, a.reference_dtb), indent=2))


if __name__ == "__main__":
    main()
