"""Execute the screen-test machine code on a synthetic ARM64 CPU, never a phone."""

import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
import zlib

from inspect_boot import align, parse_boot, parse_fdt
from pack_screen_test import validate_payload


def symbols_from_elf(blob):
    if blob[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", blob, 18)[0] != 183:
        raise ValueError("Expected little-endian ELF64 AArch64")
    offset = struct.unpack_from("<Q", blob, 40)[0]
    entry_size, count = struct.unpack_from("<HH", blob, 58)
    if entry_size != 64 or count > 64 or offset + count * entry_size > len(blob):
        raise ValueError("Invalid section table")
    sections = [struct.unpack_from("<IIQQQQIIQQ", blob, offset + index * entry_size) for index in range(count)]
    symbols = {}
    for section in sections:
        if section[1] != 2:
            continue
        if section[6] >= len(sections) or section[9] != 24 or section[5] % 24:
            raise ValueError("Invalid symbol table")
        names_section = sections[section[6]]
        names = blob[names_section[4]:names_section[4] + names_section[5]]
        if section[4] + section[5] > len(blob):
            raise ValueError("Truncated symbol table")
        for position in range(section[4], section[4] + section[5], 24):
            name, _, _, _, value, _ = struct.unpack_from("<IBBHQQ", blob, position)
            end = names.find(b"\0", name)
            if end < 0:
                raise ValueError("Invalid symbol name")
            symbols[names[name:end].decode("ascii")] = value
    for required in ("_start", "_image_end", "screen_halt", "screen_main"):
        if required not in symbols:
            raise ValueError("Missing payload symbol")
    return symbols


def fixture_tree(width=1080, stride=3240, base=0x90001000, format_name="r8g8b8",
                 marker="mido,arm64-screen-test", handle=1, reference=1,
                 with_framebuffer=True, region_size=3240 * 1920, reverse=False, shifted=False):
    structure = bytearray()
    strings = bytearray()
    names = {}

    def emit_node(name, properties, children=()):
        structure.extend(struct.pack(">I", 1) + name.encode("ascii") + b"\0")
        structure.extend(bytes(align(len(structure), 4) - len(structure)))
        for key, value in properties.items():
            if key not in names:
                names[key] = len(strings)
                strings.extend(key.encode("ascii") + b"\0")
            structure.extend(struct.pack(">III", 3, len(value), names[key]) + value)
            structure.extend(bytes(align(len(structure), 4) - len(structure)))
        for child in children:
            emit_node(*child)
        structure.extend(struct.pack(">I", 2))

    def cell(number):
        return struct.pack(">I", number)

    reservation = ("reserved-memory", {"#address-cells": cell(2), "#size-cells": cell(2)}, [
        ("cont-splash@90001000", {"phandle": cell(handle), "reg": struct.pack(">QQ", base, region_size)})
    ])
    frame = ("framebuffer@90001000", {
        "compatible": b"simple-framebuffer\0", "width": cell(width), "height": cell(1920),
        "stride": cell(stride), "memory-region": cell(reference),
        "format": format_name.encode("ascii") + b"\0", "status": b"okay\0",
    })
    chosen = ("chosen", {}, [frame] if with_framebuffer else [])
    children = [chosen, reservation] if reverse else [reservation, chosen]
    root_properties = {"compatible": marker.encode("ascii") + b"\0"}
    if shifted:
        root_properties["padding"] = b""
    emit_node("", root_properties, children)
    structure.extend(struct.pack(">I", 9))
    strings_offset = 56 + len(structure)
    total = strings_offset + len(strings)
    header = struct.pack(">10I", 0xD00DFEED, total, 56, strings_offset, 40, 17, 16, 0, len(strings), len(structure))
    result = header + bytes(16) + structure + strings
    parse_fdt(result)
    return result


def simulate(payload, symbols, tree, should_draw, load_address=0x10080000, level=1, cache=False, diagnostic_options=None):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_INTR, UC_HOOK_INSN, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_WRITE
    from unicorn.arm64_const import UC_ARM64_REG_PSTATE, UC_ARM64_REG_X0, UC_ARM64_REG_PC, UC_ARM64_REG_X9, UC_ARM64_REG_X10, UC_ARM64_REG_X11, UC_ARM64_REG_X12, UC_ARM64_REG_X30, UC_ARM64_INS_MRS

    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    dtb_address = 0x13400000
    framebuffer_address = 0x90001000
    framebuffer_size = 3240 * 1920
    payload_end = load_address + len(payload)
    cpu.mem_map(load_address, align(len(payload), 4096))
    cpu.mem_write(load_address, payload)
    cpu.mem_map(dtb_address, 65536)
    cpu.mem_write(dtb_address, tree)
    cpu.mem_map(framebuffer_address, align(framebuffer_size, 4096))
    initial = bytes([0x5A]) * framebuffer_size
    cpu.mem_write(framebuffer_address, initial)
    cpu.reg_write(UC_ARM64_REG_PSTATE, 0x3C0 | (level << 2) | 1)
    cpu.cpr_write(3, 0 if level == 1 else 4, 1, 0, 0, 4 if cache else 0)
    cpu.reg_write(UC_ARM64_REG_X0, dtb_address)
    writes = 0
    stopped = False
    diagnostic = "diagnostics_brk_instruction" in symbols
    options = diagnostic_options or {}
    trap_count = 0
    resume_count = 0
    counter_reads = 0
    frequency_reads = 0
    fault_count = 0
    saved_registers = []
    counter_value = 0x100000000
    preserved = (UC_ARM64_REG_X0, UC_ARM64_REG_X9, UC_ARM64_REG_X10, UC_ARM64_REG_X11, UC_ARM64_REG_X12, UC_ARM64_REG_X30)

    def inject_exception(engine, address, syndrome):
        status = engine.reg_read(UC_ARM64_REG_PSTATE)
        engine.cpr_write(3, 0, 4, 0, 0, status)
        engine.cpr_write(3, 0, 4, 0, 1, address)
        engine.cpr_write(3, 0, 5, 2, 0, syndrome)
        engine.cpr_write(3, 0, 6, 0, 0, 0)
        vectors = engine.cpr_read(3, 0, 12, 0, 0)
        engine.reg_write(UC_ARM64_REG_PSTATE, status | 0x3C0)
        engine.reg_write(UC_ARM64_REG_PC, vectors + 0x200)

    def interrupt(engine, number, context):
        nonlocal trap_count, saved_registers
        address = load_address + symbols["diagnostics_brk_instruction"]
        if engine.reg_read(UC_ARM64_REG_PC) not in (address, address + 4):
            raise AssertionError("Unexpected emulator exception outside BRK probe")
        saved_registers = [engine.reg_read(register) for register in preserved]
        trap_count += 1
        inject_exception(engine, address, 0x02000000 if options.get("bad_syndrome") else 0xF2004D49)

    def resumed(engine, address, size, context):
        nonlocal resume_count
        resume_count += 1
        if [engine.reg_read(register) for register in preserved] != saved_registers:
            raise AssertionError("BRK handler did not preserve its working registers")

    def faulted(engine, address, size, context):
        nonlocal fault_count
        fault_count += 1

    def counter_faulted(engine, address, size, context):
        nonlocal counter_reads
        counter_reads += 1
        inject_exception(engine, address, 0x02000000)

    def system_register(engine, register, coprocessor, context):
        nonlocal counter_value, counter_reads, frequency_reads
        identity = (coprocessor.op0, coprocessor.op1, coprocessor.crn, coprocessor.crm, coprocessor.op2)
        if identity == (3, 3, 14, 0, 0):
            frequency_reads += 1
            engine.reg_write(register, options.get("frequency", 19200000))
            return 1
        if identity == (3, 3, 14, 0, 2):
            counter_reads += 1
            counter_value += options.get("step", 2000)
            engine.reg_write(register, counter_value)
            return 1
        return 0

    def memory_access(engine, access, address, size, value, context):
        nonlocal writes
        if size > 1 and address % size:
            raise AssertionError(f"Unaligned access at {address:#x}, size {size}")
        if access == UC_MEM_WRITE:
            if framebuffer_address <= address and address + size <= framebuffer_address + 3240 * 720:
                writes += 1
            elif not (payload_end - 16384 <= address and address + size <= payload_end):
                raise AssertionError(f"Write outside payload/framebuffer at {address:#x}")

    def halt(engine, address, size, context):
        nonlocal stopped
        stopped = True
        engine.emu_stop()

    cpu.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, memory_access)
    if diagnostic:
        cpu.hook_add(UC_HOOK_INTR, interrupt)
        cpu.hook_add(UC_HOOK_INSN, system_register, None, 1, 0, UC_ARM64_INS_MRS)
        continuation = load_address + symbols["diagnostics_brk_instruction"] + 4
        cpu.hook_add(UC_HOOK_CODE, resumed, begin=continuation, end=continuation)
        fault_address = load_address + symbols["diagnostics_fault"]
        cpu.hook_add(UC_HOOK_CODE, faulted, begin=fault_address, end=fault_address)
        if options.get("counter_fault"):
            counter_address = load_address + symbols["diagnostics_counter"] + 4
            cpu.hook_add(UC_HOOK_CODE, counter_faulted, begin=counter_address, end=counter_address)
    halt_address = load_address + symbols["screen_halt"]
    cpu.hook_add(UC_HOOK_CODE, halt, begin=halt_address, end=halt_address)
    cpu.emu_start(load_address, payload_end, timeout=60000000, count=100000000)
    if not stopped:
        raise AssertionError("Payload did not reach its halt loop")
    pixels = bytes(cpu.mem_read(framebuffer_address, framebuffer_size))
    if should_draw:
        if not writes or pixels == initial or pixels[3240 * 720:] != initial[3240 * 720:]:
            raise AssertionError("Missing drawing or unexpected writes below row 720")
        if pixels[:3] != bytes(3) or pixels[680 * 3240 + 90 * 3:680 * 3240 + 90 * 3 + 3] != bytes([255]) * 3:
            raise AssertionError("Unexpected grayscale checker output")
    elif writes or pixels != initial:
        raise AssertionError("Rejected DTB unexpectedly changed framebuffer")
    if diagnostic and should_draw:
        if trap_count != 1:
            raise AssertionError("Expected exactly one modeled BRK exception")
        expected_faults = int(bool(options.get("bad_syndrome") or options.get("counter_fault")))
        if fault_count != expected_faults or resume_count != int(not options.get("bad_syndrome")):
            raise AssertionError("Unexpected exception/ERET path")
        if expected_faults:
            check_text_row(payload, symbols, pixels, 20, "EXCEPTION HALTED")
        else:
            check_text_row(payload, symbols, pixels, 100, "BRK ERET OK")
            frequency = options.get("frequency", 19200000)
            message = "BAD FREQUENCY" if not 0 < frequency <= 1000000000 else "COUNTER STALLED" if options.get("step", 2000) == 0 else "COUNTER BACKWARDS" if options.get("step", 2000) < 0 else "COUNTER OK"
            check_text_row(payload, symbols, pixels, 340, message)
    return {"framebuffer_stores": writes, "halted": stopped, "modeled_brk_exceptions": trap_count,
            "eret_returns": resume_count, "fault_handler_calls": fault_count,
            "counter_reads": counter_reads, "frequency_reads": frequency_reads}, pixels


def check_text_row(payload, symbols, pixels, row, message):
    expected = bytearray(3240 * 64)
    column = 60
    for character in message:
        glyph = None
        if "A" <= character <= "Z":
            offset = symbols["glyphs"] + (ord(character) - ord("A")) * 7
            glyph = payload[offset:offset + 7]
        if "0" <= character <= "9":
            offset = symbols["digits"] + (ord(character) - ord("0")) * 7
            glyph = payload[offset:offset + 7]
        if glyph:
            for vertical in range(56):
                for horizontal in range(40):
                    if glyph[vertical // 8] & (16 >> (horizontal // 8)):
                        offset = vertical * 3240 + (column + horizontal) * 3
                        expected[offset:offset + 3] = bytes([255]) * 3
        column += 48
    if pixels[row * 3240:(row + 64) * 3240] != expected:
        raise AssertionError(f"Unexpected rendered diagnostic line: {message}")


def save_preview(path, pixels):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    scanlines = b"".join(b"\0" + pixels[row * 3240:(row + 1) * 3240] for row in range(720))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1080, 720, 8, 2, 0, 0, 0))
    path.write_bytes(png + chunk(b"IDAT", zlib.compress(scanlines)) + chunk(b"IEND", b""))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build_directory", type=Path)
    parser.add_argument("--report-prefix", default="emulation")
    args = parser.parse_args()
    workspace = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(workspace / "artifacts" / "python-deps"))
    directory = args.build_directory.resolve(strict=True)
    if not directory.is_relative_to(workspace / "artifacts"):
        raise ValueError("Build directory must be under workspace artifacts")
    if not args.report_prefix or Path(args.report_prefix).name != args.report_prefix:
        raise ValueError("Report prefix must be a simple filename")
    report_path = directory / (args.report_prefix + ".json")
    preview_path = directory / (args.report_prefix + "-preview.png")
    if report_path.exists() or preview_path.exists():
        raise ValueError("Emulation outputs already exist; refusing to overwrite")
    payload = (directory / "screen.bin").read_bytes()
    validate_payload(payload)
    symbols = symbols_from_elf((directory / "screen.elf").read_bytes())
    if symbols["_start"] != 0 or symbols["_image_end"] != len(payload):
        raise ValueError("ELF symbols disagree with raw image")
    manifest = json.loads((directory / "package" / "manifest.json").read_text())
    image = (directory / "package" / "mido-arm64-screen-test.img").read_bytes()
    if hashlib.sha256(image).hexdigest() != manifest["image_sha256"] or hashlib.sha256(payload).hexdigest() != manifest["payload_sha256"]:
        raise ValueError("Build hash mismatch")
    _, parts = parse_boot(image)
    if parts["kernel"][:len(payload)] != payload:
        raise ValueError("Packaged machine code differs from tested payload")
    cases = [
        ("valid-el1", {}, True, {}),
        ("valid-four-byte-aligned-reg", {"shifted": True}, True, {}),
        ("valid-el2-relocated", {"reverse": True}, True, {"level": 2, "load_address": 0x80080000}),
        ("wrong-width", {"width": 720}, False, {}),
        ("wrong-stride", {"stride": 4352}, False, {}),
        ("wrong-base", {"base": 0x90000000}, False, {}),
        ("wrong-format", {"format_name": "x8r8g8b8"}, False, {}),
        ("wrong-marker", {"marker": "unrelated"}, False, {}),
        ("missing-framebuffer", {"with_framebuffer": False}, False, {}),
        ("wrong-reference", {"reference": 2}, False, {}),
        ("small-reservation", {"region_size": 128}, False, {}),
        ("large-reservation", {"region_size": 0x02000000}, False, {}),
        ("cache-enabled", {}, False, {"cache": True}),
    ]
    if manifest.get("diagnostics"):
        cases[2] = ("el2-rejected", {"reverse": True}, False, {"level": 2, "load_address": 0x80080000})
        cases.extend([
            ("valid-el1-relocated", {}, True, {"load_address": 0x80080000}),
            ("counter-stalled", {}, True, {"diagnostic_options": {"step": 0}}),
            ("counter-backwards", {}, True, {"diagnostic_options": {"step": -1}}),
            ("frequency-zero", {}, True, {"diagnostic_options": {"frequency": 0}}),
            ("frequency-too-large", {}, True, {"diagnostic_options": {"frequency": 1000000001}}),
            ("unexpected-brk-syndrome", {}, True, {"diagnostic_options": {"bad_syndrome": True}}),
            ("counter-read-exception", {}, True, {"diagnostic_options": {"counter_fault": True}}),
        ])
    results = {}
    for name, changes, expected, settings in cases:
        result, pixels = simulate(payload, symbols, fixture_tree(**changes), expected, **settings)
        results[name] = result
        print(f"PASS: {name}: {result}", flush=True)
        if name == "valid-el1":
            save_preview(preview_path, pixels)
    report = {"image_sha256": manifest["image_sha256"], "scope": "Synthetic CPU/FDT only; BRK vector entry and counter values are injected by the harness, handler instructions and ERET execute in the emulator. Not a phone, TrustZone or display-driver test.", "cases": results}
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
