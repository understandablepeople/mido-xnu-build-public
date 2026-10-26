"""Inspect local ARM ELF32 bootloader readbacks; never execute their code."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys


KNOWN_SHA256 = "873a4f8013e6e9f8057ac40e6e086db701cc13818c07318af71d27941a59c448"
KNOWN_WINDOWS = {
    "address_rewriter": (0x8F6294A0, 0x8F629514),
    "memory_bank_selector": (0x8F60496C, 0x8F604A98),
    "fastboot_arm64_recognition": (0x8F62E874, 0x8F62E8A0),
    "kernel_handoff_dispatch": (0x8F62ABF8, 0x8F62ACB8),
    "secure_monitor_bridge": (0x8F6162B8, 0x8F6163BC),
}


def parse_elf32(image):
    if len(image) < 52 or image[:7] != b"\x7fELF\x01\x01\x01":
        raise ValueError("Expected little-endian ELF32 version 1")
    header = struct.unpack_from("<16sHHIIIIIHHHHHH", image)
    _, executable_type, machine, version, entry, offset, _, _, header_size, entry_size, count, _, _, _ = header
    if executable_type != 2 or machine != 40 or version != 1 or header_size != 52 or entry_size != 32:
        raise ValueError("Unsupported ARM executable header")
    if not 0 < count <= 256 or offset < 52 or offset + count * entry_size > len(image):
        raise ValueError("Invalid ELF program table")
    segments = []
    for index in range(count):
        values = struct.unpack_from("<8I", image, offset + index * entry_size)
        segment = dict(zip(("type", "offset", "vaddr", "paddr", "filesz", "memsz", "flags", "align"), values))
        if segment["offset"] + segment["filesz"] > len(image):
            raise ValueError("ELF segment outside file")
        if segment["type"] == 1:
            if segment["filesz"] > segment["memsz"] or segment["vaddr"] + segment["memsz"] > 2**32:
                raise ValueError("Invalid ELF load segment")
            alignment = segment["align"]
            if alignment > 1 and (alignment & (alignment - 1) or segment["offset"] % alignment != segment["vaddr"] % alignment):
                raise ValueError("Invalid ELF load alignment")
        segments.append(segment)
    if not any(segment["type"] == 1 and segment["flags"] & 1 and segment["vaddr"] <= entry < segment["vaddr"] + segment["filesz"] for segment in segments):
        raise ValueError("ELF entry is not file-backed executable code")
    return {"entry": entry, "segments": segments}


def file_offset(elf, address, size):
    if size <= 0 or address < 0:
        raise ValueError("Invalid requested range")
    candidates = [segment for segment in elf["segments"] if segment["type"] == 1 and segment["vaddr"] <= address and address + size <= segment["vaddr"] + segment["filesz"]]
    if len(candidates) != 1:
        raise ValueError("Address is not in exactly one file-backed load segment")
    segment = candidates[0]
    return segment["offset"] + address - segment["vaddr"]


def verify_readback(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8-sig"))
    expected = {"aboot", "abootbak", "persist"}
    if not isinstance(manifest, list) or len(manifest) != 3 or {item.get("Name") for item in manifest} != expected:
        raise ValueError("Expected exactly aboot, abootbak and persist manifest entries")
    verified = {}
    for item in manifest:
        name = item["Name"]
        data = (directory / (name + ".img")).read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if not isinstance(item.get("SHA256"), str) or not re.fullmatch(r"[0-9a-fA-F]{64}", item["SHA256"]):
            raise ValueError("Invalid manifest checksum")
        if len(data) != item.get("Bytes") or digest != item["SHA256"].lower():
            raise ValueError(f"Readback integrity failed: {name}")
        verified[name] = {"size": len(data), "sha256": digest}
    return verified


def inspect(directory, destination):
    directory = directory.resolve(strict=True)
    destination = destination.resolve()
    if destination.exists() or destination == directory or destination.is_relative_to(directory):
        raise ValueError("Choose a new output directory outside the readback")
    verified = verify_readback(directory)
    image = (directory / "aboot.img").read_bytes()
    elf = parse_elf32(image)
    recognized = verified["aboot"]["sha256"] == KNOWN_SHA256
    report = {
        "verified_files": verified,
        "aboot_and_backup_identical": verified["aboot"]["sha256"] == verified["abootbak"]["sha256"],
        "elf": elf,
        "known_binary": recognized,
        "warning": "Static analysis only. Not a boot authorization, a write map, or proof of successful XNU execution.",
    }
    listings = {}
    if recognized:
        dependencies = Path(__file__).resolve().parents[1] / "artifacts" / "python-deps"
        if dependencies.is_dir():
            sys.path.insert(0, str(dependencies))
        import capstone

        engine = capstone.Cs(capstone.CS_ARCH_ARM, capstone.CS_MODE_ARM)
        report["disassembler"] = "Capstone " + capstone.__version__
        for name, (start, end) in KNOWN_WINDOWS.items():
            offset = file_offset(elf, start, end - start)
            instructions = list(engine.disasm(image[offset:offset + end - start], start))
            if sum(instruction.size for instruction in instructions) != end - start:
                raise ValueError("Incomplete disassembly of known code")
            listings[name] = "\n".join(f"{instruction.address:08x}: {instruction.bytes.hex():8s}  {instruction.mnemonic:8s} {instruction.op_str}" for instruction in instructions) + "\n"
        report["observed_address_rewriter"] = {
            "function_va": "0x8f6294a0",
            "bank_selector_va": "0x8f60496c",
            "arm32_kernel_offset": "0x8000",
            "arm64_kernel_offset": "0x80000",
            "ramdisk_offset": "0x3600000",
            "dtb_offset": "0x3400000",
            "interpretation": "Header destinations are overwritten using a selected RAM-bank base. The observed recovery base 0x10000000 predicts kernel 0x10080000, ramdisk 0x13600000 and DTB 0x13400000. Kernel and ramdisk agree with capture; DTB address is a static prediction, not a captured physical pointer.",
        }
    destination.mkdir(parents=True)
    (destination / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for name, listing in listings.items():
        (destination / (name + ".asm")).write_text(listing, encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("destination", type=Path)
    arguments = parser.parse_args()
    try:
        report = inspect(arguments.directory, arguments.destination)
    except (OSError, ValueError, ImportError) as error:
        parser.exit(1, f"Inspection failed: {error}\n")
    print(json.dumps({"verified": list(report["verified_files"]), "aboot_and_backup_identical": report["aboot_and_backup_identical"], "known_binary": report["known_binary"], "entry": hex(report["elf"]["entry"]), "address_rewriter": report.get("observed_address_rewriter")}, indent=2))


if __name__ == "__main__":
    main()
