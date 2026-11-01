"""Explicit opt-in configuration for a reversible TTBR1-only diagnostic."""

from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

from tools.mido_elf import symbols_from_elf
from tools.mido_vm_activation_plan import activation_plan
from tools.mido_vm_activation_audit import walk
from tools.inspect_xnu import inspect
from tools.mido_native4k_profile import reference_tables
from tools.mido_vm_physmap_complete_reference import CompletePhysmapReference
from tools.mido_vm_physmap_carrier_config import _replace_definitions
from tools.mido_vm_transition_island import transition_island


RECORD = 0x12400900
MAGIC = 0x3130305445523154
SOURCE_SHA256 = "3314d04214dc5e149bb2e5665312ddb6baad50faa7b7b97d7a03889d8c79c3db"
ISLAND_SHA256 = "76d1f32c7a3f93d64467076f0c272137578a6825a86861736448a8b9242cba4f"


def build_island(kernel, toolchain, output):
    report = transition_island(kernel)
    if not report["found"]:
        raise ValueError("No reviewed executable padding for TTBR1 diagnostic")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1] / "devices/mido/xnu/probe/ttbr1_return.S"
    if hashlib.sha256(source.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError("TTBR1 observer source differs from reviewed assembly")
    address = report["candidate"]["va"]
    subprocess.run([str(toolchain / "clang.exe"), "--target=aarch64-none-elf",
                    "-mcpu=cortex-a53", "-c", str(source), "-o", str(output / "return.o")],
                   check=True, capture_output=True)
    subprocess.run([str(toolchain / "ld.lld.exe"), f"-Ttext={address:#x}",
                    "-e", "mido_ttbr1_return", str(output / "return.o"),
                    "-o", str(output / "return.elf")], check=True, capture_output=True)
    subprocess.run([str(toolchain / "llvm-objcopy.exe"), "-O", "binary", "-j", ".text",
                    str(output / "return.elf"), str(output / "return.bin")],
                   check=True, capture_output=True)
    payload = (output / "return.bin").read_bytes()
    symbols = symbols_from_elf((output / "return.elf").read_bytes(), ("mido_ttbr1_return",))
    if not payload or len(payload) > report["candidate"]["budget"]:
        raise ValueError("TTBR1 observer exceeds reviewed zero padding")
    return payload, {name: value for name, value in symbols.items() if name.startswith("mido_ttbr1_return")}


def configure_ttbr1_carrier(kernel, header, review, payload, symbols):
    plan = activation_plan(kernel)
    report = transition_island(kernel)
    if not review.get("vm_physmap_complete") or not review.get("vm_dynamic"):
        raise ValueError("TTBR1 diagnostic requires explicit complete physmap prefix")
    if not report["found"]:
        raise ValueError("No reviewed executable padding")
    island = report["candidate"]
    bootstrap = reference_tables(kernel,0x11200000,0xfffffff007000000,0x2000000)
    for address in (RECORD,RECORD+71):
        translated = walk(bootstrap,address,top=0x11352000)
        if not translated["writable"] or translated["physical"] != address:
            raise ValueError("Transition record lacks bootstrap identity mapping")
    mapping_audits = []
    for count,slide in ((1,0),(2,0x3ffff000),(1,0x37000000)):
        reference = CompletePhysmapReference(inspect(kernel)["segments"],0xfffffff007000000,0x11200000,0x12401000,count)
        reference.physmap = 0xfffffff008201000 + slide
        reference.end_kernel = 0xfffffff007f6c000
        snapshot = reference.expected("vm-physmap-before-ttbr")
        for address in (island["va"],island["end_va"]-4,plan["stages"]["vm-ttbr1-return"],
                        0xfffffff00722d838,0xfffffff00722d844,0xfffffff00722c000):
            translated = walk(snapshot,address)
            if not translated["executable"] or translated["physical"] != 0x11200000+address-0xfffffff007000000:
                raise ValueError("Transition execution lacks exact final RX mapping")
        mapping_audits.append(dict(initial_l2_count=count,slide=slide,final_rx_verified=True))
    if (hashlib.sha256(payload).hexdigest() != ISLAND_SHA256
            or len(payload) > island["budget"] or len(payload) & 3
            or symbols.get("mido_ttbr1_return") != island["va"]
            or symbols.get("mido_ttbr1_return_record") != RECORD
            or symbols.get("mido_ttbr1_return_magic") != MAGIC
            or symbols.get("mido_ttbr1_return_end") != island["va"] + len(payload)):
        raise ValueError("TTBR1 observer layout differs")
    offsets = {"flush":0x4c,"capture":0x5c,"restore":0x9c,"restored":0xb0,
               "branch":0xc8,"reject":0xcc,"end":0xd4}
    if any(symbols.get("mido_ttbr1_return_"+name) != island["va"]+offset
           for name,offset in offsets.items()):
        raise ValueError("TTBR1 observer instruction labels differ")
    target = plan["stages"]["vm-ttbr1-return"]
    original = 0x90ffe8f4
    definitions = {"MIDO_VM_TTBR1_ROUNDTRIP": 1, "MIDO_EARLY_STOP_PA": 0x11200000 + target - 0xfffffff007000000,
                   "MIDO_NATIVE_STOP_WORD": original, "MIDO_TTBR1_ISLAND_VA": island["va"],
                   "MIDO_TTBR1_ISLAND_PA": island["pa"], "MIDO_TTBR1_ISLAND_SIZE": len(payload),
                   "MIDO_TTBR1_ISLAND_BUDGET": island["budget"], "MIDO_TTBR1_RECORD": RECORD,
                   "MIDO_TTBR1_MAGIC": MAGIC}
    header = _replace_definitions(header, set(definitions) | {"MIDO_TTBR1_ISLAND_BYTES"})
    header += "".join(f"#define {name} 0x{value:x}ULL\n" for name, value in definitions.items())
    header += "#define MIDO_TTBR1_ISLAND_BYTES {" + ",".join(f"0x{value:02x}" for value in payload) + "}\n"
    review = deepcopy(review)
    review["values"]["MIDO_EARLY_STOP_PA"] = definitions["MIDO_EARLY_STOP_PA"]
    for name in definitions.keys() & review["values"].keys():
        review["values"][name] = definitions[name]
    review["post_c_definitions"].update(definitions)
    review.update(vm_ttbr1_roundtrip=True, stop_va=target, original_stop_word=original,
                  scope="Original TTBR1 setter followed by diagnostic restoration; TTBR0 unchanged",
                  stops_before=["Original TTBR0 setter", "Interrupt enable", "Storage or userland"],
                  ttbr1_island=dict(island, payload_sha256=hashlib.sha256(payload).hexdigest(),
                                    payload_bytes=len(payload), symbols=symbols),
                  ttbr1_record=dict(physical=RECORD, words=9, magic=MAGIC),
                  transition_mapping_audits=mapping_audits,
                  full_activation=False, hardware_execution_proven=False)
    return header, review
