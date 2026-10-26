"""Report linked root-device prerequisites without approving device execution."""

import argparse
import hashlib
import json
from pathlib import Path

try:
    from tools.apple_device_tree import decode_tree
    from tools.mido_macho_symbols import macho_symbols
except ModuleNotFoundError:
    from apple_device_tree import decode_tree
    from mido_macho_symbols import macho_symbols


def audit(symbols, tree):
    chosen = next((node for node in tree["children"] if node["name"] == "chosen"), None)
    memory_map = next((node for node in chosen["children"] if node["name"] == "memory-map"), None) if chosen else None
    ramdisk = memory_map["properties"].get("RAMDisk") if memory_map else None
    memdev = {name: name in symbols for name in
              ("_mdevadd", "_mdevlookup", "_mdevstrategy", "_mdevrw")}
    candidates = {name: name in symbols for name in
                  ("_hfs_mountroot", "_hfs_vfsops", "_apfs_vfsops",
                   "_apfs_mountroot", "_nfs_mountroot", "_mockfs_mountroot")}
    blockers = []
    if not all(memdev.values()):
        blockers.append("native-memory-device-path-incomplete")
    if ramdisk is None:
        blockers.append("no-ramdisk-in-chosen-memory-map")
    elif len(ramdisk) != 16:
        blockers.append("invalid-arm64-ramdisk-property-size")
    if not any(candidates.values()):
        blockers.append("no-recognized-root-filesystem-provider-symbols")
    return dict(scope="read-only static evidence, not runtime root or filesystem validation",
                memory_device_symbols=memdev, ramdisk_property_present=ramdisk is not None,
                filesystem_provider_symbol_candidates=candidates, blockers=blockers,
                limitations=["symbol presence does not prove VFS registration or successful mounting",
                             "an absent RAMDisk does not rule out other storage devices",
                             "external filesystem modules are not inspected"],
                root_selected=False, root_mounted=False, boot_approved=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kernel", type=Path)
    parser.add_argument("apple_tree", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    kernel, tree = args.kernel.read_bytes(), args.apple_tree.read_bytes()
    result = audit(macho_symbols(kernel), decode_tree(tree))
    result.update(kernel_sha256=hashlib.sha256(kernel).hexdigest(),
                  apple_tree_sha256=hashlib.sha256(tree).hexdigest())
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
