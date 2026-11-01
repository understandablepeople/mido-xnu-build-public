"""Read a legacy Android boot backup without accessing a connected phone."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import zlib


FDT_MAGIC = b"\xd0\x0d\xfe\xed"
MAX_EXPANDED = 256 * 1024 * 1024


def align(value, boundary):
    return (value + boundary - 1) // boundary * boundary


def parse_boot(image):
    if len(image) < 1632 or image[:8] != b"ANDROID!":
        raise ValueError("Not a complete legacy Android boot header")
    fields = struct.unpack_from("<10I", image, 8)
    kernel_size, kernel_address, ramdisk_size, ramdisk_address = fields[:4]
    second_size, second_address, tags_address, page_size, version, os_version = fields[4:]
    if version != 0:
        raise ValueError("Only header v0 is supported; refusing to guess another layout")
    if page_size < 1632 or page_size > 65536 or page_size & (page_size - 1):
        raise ValueError("Invalid boot page size")
    header = {
        "kernel_address": hex(kernel_address),
        "ramdisk_address": hex(ramdisk_address),
        "second_address": hex(second_address),
        "tags_address": hex(tags_address),
        "page_size": page_size,
        "header_version": version,
        "os_version_raw": os_version,
    }
    parts = {}
    offset = page_size
    for name, size in (("kernel", kernel_size), ("ramdisk", ramdisk_size), ("second", second_size)):
        if offset + size > len(image):
            raise ValueError(f"Truncated {name}")
        parts[name] = image[offset:offset + size]
        header[name] = {"offset": offset, "size": size}
        offset += align(size, page_size)
    return header, parts


def parse_fdt(blob):
    if len(blob) < 40 or blob[:4] != FDT_MAGIC:
        raise ValueError("Invalid FDT header")
    _, total, structure, strings, reserves, version, compatible, _, strings_size, structure_size = struct.unpack_from(
        ">10I", blob
    )
    if total < 40 or total > len(blob) or version != 17 or compatible > 17:
        raise ValueError("Invalid or unsupported FDT size/version")
    for offset, size in ((structure, structure_size), (strings, strings_size)):
        if offset < 40 or offset + size > total:
            raise ValueError("FDT block outside blob")
    if structure % 4 or reserves < 40 or reserves % 8 or reserves + 16 > total:
        raise ValueError("Invalid FDT alignment or reservation map")
    reserved = []
    reserve_offset = reserves
    while True:
        if reserve_offset + 16 > total:
            raise ValueError("Unterminated FDT reservation map")
        address, size = struct.unpack_from(">QQ", blob, reserve_offset)
        reserve_offset += 16
        if address == 0 and size == 0:
            break
        reserved.append({"address": hex(address), "size": hex(size)})
    nodes = {}
    stack = []
    position = structure
    limit = structure + structure_size
    saw_root = False
    while position + 4 <= limit:
        token = struct.unpack_from(">I", blob, position)[0]
        position += 4
        if token == 1:
            end = blob.find(b"\0", position, limit)
            if end < 0:
                raise ValueError("Unterminated FDT node")
            name = blob[position:end].decode("ascii", "replace")
            if not stack:
                if saw_root or name:
                    raise ValueError("Invalid FDT root")
                saw_root = True
            stack.append(name)
            path = "/" + "/".join(stack[1:])
            if path in nodes:
                raise ValueError("Duplicate FDT node")
            nodes[path] = {}
            position = align(end + 1, 4)
        elif token == 2:
            if not stack:
                raise ValueError("Unbalanced FDT node")
            stack.pop()
        elif token == 3:
            if not stack or position + 8 > limit:
                raise ValueError("Invalid FDT property")
            size, name_offset = struct.unpack_from(">II", blob, position)
            position += 8
            if name_offset >= strings_size or position + size > limit:
                raise ValueError("FDT property outside block")
            name_start = strings + name_offset
            name_end = blob.find(b"\0", name_start, strings + strings_size)
            if name_end < 0:
                raise ValueError("Unterminated FDT property name")
            name = blob[name_start:name_end].decode("ascii", "replace")
            path = "/" + "/".join(stack[1:])
            if name in nodes[path]:
                raise ValueError("Duplicate FDT property")
            nodes[path][name] = blob[position:position + size]
            position = align(position + size, 4)
        elif token == 4:
            continue
        elif token == 9:
            if stack or not saw_root:
                raise ValueError("Incomplete FDT structure")
            return {"total_size": total, "reservations": reserved, "nodes": nodes}
        else:
            raise ValueError("Unknown FDT token")
    raise ValueError("Missing FDT end token")


def find_fdts(data):
    position = 0
    while True:
        position = data.find(FDT_MAGIC, position)
        if position < 0:
            return
        try:
            tree = parse_fdt(data[position:])
        except ValueError:
            position += 4
            continue
        yield position, data[position:position + tree["total_size"]], tree
        position += tree["total_size"]


def decode_property(value, name=""):
    if not value:
        return True
    string_property = name in {"model", "compatible", "status", "device_type", "format", "method"} or name.endswith("-name")
    if string_property and value.endswith(b"\0") and all(byte == 0 or 32 <= byte < 127 for byte in value):
        return value.rstrip(b"\0").decode("ascii").split("\0")
    if len(value) % 4 == 0:
        return [hex(cell[0]) for cell in struct.iter_unpack(">I", value)]
    return {"hex": value.hex()}


def summarize(tree):
    selected = {}
    keywords = ("memory", "splash", "framebuffer", "display", "mdss", "panel", "dsi", "interrupt", "gic", "psci", "timer", "sdhc", "mmc", "touch", "goodix", "focaltech", "synaptics", "cpu")
    allowed = {"model", "compatible", "reg", "ranges", "status", "device_type", "#address-cells", "#size-cells", "width", "height", "stride", "format", "memory-region", "interrupts", "interrupt-parent", "method", "qcom,msm-id", "qcom,board-id", "qcom,pmic-id"}
    for path, properties in tree["nodes"].items():
        compatible = properties.get("compatible", b"").decode("ascii", "replace")
        if path in ("/", "/chosen", "/reserved-memory") or any(word in path.lower() + compatible.lower() for word in keywords):
            selected[path] = {name: decode_property(value, name) for name, value in properties.items() if name in allowed or name.startswith("qcom,mdss")}
    return {"reservations": tree["reservations"], "selected_nodes": selected}


def inspect(source, destination):
    source = source.resolve(strict=True)
    destination = destination.resolve()
    backup_ancestor = next((parent for parent in source.parents if parent.name == "phone-backup"), source.parent)
    if destination == backup_ancestor or destination.is_relative_to(backup_ancestor):
        raise ValueError("Output must not be inside the source backup")
    if destination.exists():
        raise ValueError("Output already exists; choose a new directory")
    image = source.read_bytes()
    header, parts = parse_boot(image)
    regions = {"kernel": parts["kernel"], "second": parts["second"]}
    if parts["kernel"].startswith(b"\x1f\x8b"):
        inflater = zlib.decompressobj(31)
        expanded = inflater.decompress(parts["kernel"], MAX_EXPANDED + 1)
        if not inflater.eof or len(expanded) > MAX_EXPANDED:
            raise ValueError("Invalid or oversized gzip kernel")
        regions["kernel-expanded"] = expanded
        regions["kernel-gzip-tail"] = inflater.unused_data
        header["gzip_kernel"] = {"expanded_size": len(expanded), "trailing_size": len(inflater.unused_data)}
    extracted = []
    seen = set()
    for region, data in regions.items():
        for offset, blob, tree in find_fdts(data):
            digest = hashlib.sha256(blob).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            extracted.append((blob, {"file": f"dtb-{len(extracted):02d}.dtb", "region": region, "offset": offset, "sha256": digest, **summarize(tree)}))
    report = {"source_sha256": hashlib.sha256(image).hexdigest(), "header": header, "device_trees": [entry for _, entry in extracted], "warning": "Static backup inspection only. A bundled DTB is not proof of the bootloader-selected live tree. No boot image is generated."}
    destination.mkdir(parents=True)
    for name, data in parts.items():
        if data:
            (destination / f"{name}.bin").write_bytes(data)
    for blob, entry in extracted:
        (destination / entry["file"]).write_bytes(blob)
    (destination / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    try:
        report = inspect(arguments.source, arguments.destination)
    except (OSError, ValueError, zlib.error) as error:
        parser.exit(1, f"Inspection failed: {error}\n")
    print(json.dumps({"header": report["header"], "device_tree_count": len(report["device_trees"])}, indent=2))


if __name__ == "__main__":
    main()
