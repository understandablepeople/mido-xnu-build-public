"""Explicit offline configuration for the diagnostic both-TTBR roundtrip."""

from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

from tools.mido_elf import symbols_from_elf
from tools.mido_vm_activation_plan import activation_plan
from tools.mido_vm_physmap_carrier_config import _replace_definitions
from tools.mido_vm_transition_island import transition_island
from tools.mido_vm_ttbr0_dependencies import audit


RECORD = 0x12400900
MAGIC = 0x3130305445523054
SOURCE_SHA256 = "6fb52bf3a86e451b16080df0d1760638578e92b636f8536378400b6a645e8779"
ISLAND_SHA256 = "13e95cf657945e675541f9e42cad1a070d9b4e743b0436545b65a030e8e8e476"
PAYLOAD_BYTES = 236
LABEL_OFFSETS = {"": 0, "_restore_ttbr0": 0x58, "_capture": 0x6c,
                 "_restore": 0xb4, "_restored": 0xc8, "_branch": 0xe0,
                 "_reject": 0xe4, "_end": 0xec}
SOURCE = Path(__file__).resolve().parents[1] / "devices/mido/xnu/probe/ttbr0_return.S"


def _reviewed_source():
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("TTBR0 observer source differs from reviewed assembly")
    return SOURCE


def _layout(payload, symbols, island):
    expected = {"mido_ttbr0_return" + suffix: island["va"] + offset
                for suffix, offset in LABEL_OFFSETS.items()}
    expected.update(mido_ttbr0_return_record=RECORD, mido_ttbr0_return_magic=MAGIC)
    if (len(payload) != PAYLOAD_BYTES or len(payload) > island["budget"]
            or hashlib.sha256(payload).hexdigest() != ISLAND_SHA256
            or symbols != expected):
        raise ValueError("TTBR0 observer payload/layout or instruction labels differ")


def build_island(kernel, toolchain, output):
    """Compile only the pinned assembly into verified original zero padding."""
    report = transition_island(kernel)
    if not report["found"]:
        raise ValueError("No reviewed executable padding for TTBR0 diagnostic")
    source = _reviewed_source()
    toolchain = Path(toolchain)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    address = report["candidate"]["va"]
    subprocess.run([str(toolchain / "clang.exe"), "--target=aarch64-none-elf",
                    "-mcpu=cortex-a53", "-c", str(source), "-o", str(output / "return.o")],
                   check=True, capture_output=True)
    subprocess.run([str(toolchain / "ld.lld.exe"), f"-Ttext={address:#x}",
                    "-e", "mido_ttbr0_return", str(output / "return.o"),
                    "-o", str(output / "return.elf")], check=True, capture_output=True)
    subprocess.run([str(toolchain / "llvm-objcopy.exe"), "-O", "binary", "-j", ".text",
                    str(output / "return.elf"), str(output / "return.bin")],
                   check=True, capture_output=True)
    payload = (output / "return.bin").read_bytes()
    symbols = symbols_from_elf((output / "return.elf").read_bytes(), ("mido_ttbr0_return",))
    symbols = {name: value for name, value in symbols.items()
               if name.startswith("mido_ttbr0_return")}
    _layout(payload, symbols, report["candidate"])
    return payload, symbols


def configure_ttbr0_carrier(kernel, header, review, payload, symbols):
    """Extend complete-physmap input, not a TTBR1-only config; never activate."""
    if (review.get("vm_physmap_complete") is not True or review.get("vm_dynamic") is not True
            or review.get("vm_ttbr1_roundtrip") and not review.get("vm_ttbr0_roundtrip")):
        raise ValueError("TTBR0 diagnostic requires explicit complete physmap prefix, not TTBR1 config")
    plan = activation_plan(kernel)
    report = transition_island(kernel)
    if not report["found"]:
        raise ValueError("No reviewed executable padding")
    _reviewed_source()
    island = report["candidate"]
    _layout(payload, symbols, island)
    dependencies = audit(kernel)
    if not dependencies["passed"]:
        raise ValueError("TTBR0 dependency audit failed")
    target = plan["stages"]["vm-after-activation-sync"]
    stop = plan["next_bounded_work"]["instructions"][0]
    original = int.from_bytes(bytes.fromhex(stop["bytes"]), "little")
    if stop["address"] != target or original != 0xf9400aa0:
        raise ValueError("TTBR0 activation stop instruction differs")
    definitions = {
        "MIDO_VM_TTBR0_ROUNDTRIP": 1, "MIDO_VM_TTBR1_ROUNDTRIP": 1,
        "MIDO_EARLY_STOP_PA": 0x11200000 + target - 0xfffffff007000000,
        "MIDO_NATIVE_STOP_WORD": original, "MIDO_C_EXPECTED_X0": 0x12401000,
        "MIDO_TTBR1_ISLAND_VA": island["va"], "MIDO_TTBR1_ISLAND_PA": island["pa"],
        "MIDO_TTBR1_ISLAND_SIZE": len(payload), "MIDO_TTBR1_ISLAND_BUDGET": island["budget"],
        "MIDO_TTBR1_RECORD": RECORD, "MIDO_TTBR1_MAGIC": MAGIC,
        "MIDO_TTBR1_RECORD_WORDS": 10}
    header = _replace_definitions(header, set(definitions) | {"MIDO_TTBR1_ISLAND_BYTES"})
    header += "".join(f"#define {name} 0x{value:x}ULL\n" for name, value in definitions.items())
    header += "#define MIDO_TTBR1_ISLAND_BYTES {" + ",".join(f"0x{value:02x}" for value in payload) + "}\n"
    review = deepcopy(review)
    review.setdefault("values", {})["MIDO_EARLY_STOP_PA"] = definitions["MIDO_EARLY_STOP_PA"]
    for name in definitions.keys() & review["values"].keys():
        review["values"][name] = definitions[name]
    review.setdefault("post_c_definitions", {}).update(definitions)
    review.update(vm_ttbr0_roundtrip=True, vm_ttbr1_roundtrip=True, ttbr0_changed=True,
                  stop_va=target, original_stop_word=original,
                  scope="Both original TTBR setters and caller TLBI followed by diagnostic "
                        "bootstrap TTBR0 and TTBR1 restoration; not full activation",
                  stops_before=["Post-activation root publication", "Interrupt enable", "Storage or userland"],
                  ttbr1_island=dict(deepcopy(island), payload_sha256=ISLAND_SHA256,
                                    source_sha256=SOURCE_SHA256, payload_bytes=len(payload),
                                    symbols=deepcopy(symbols)),
                  ttbr1_record=dict(physical=RECORD, words=10, magic=MAGIC),
                  ttbr0_dependencies=deepcopy(dependencies),
                  full_activation=False, hardware_execution_proven=False, boot_approved=False)
    return header, review
