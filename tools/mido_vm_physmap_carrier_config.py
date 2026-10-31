"""Pinned pre-TTBR carrier templates with runtime-derived alias cells omitted."""

from copy import deepcopy
import re
import struct

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols
from tools.mido_vm_physmap_complete_plan import complete_physmap_plan
from tools.mido_vm_physmap_complete_reference import CompletePhysmapReference
from tools.mido_vm_reference_spans import decode, encode


VIRTUAL = 0xfffffff007000000
PHYSICAL = 0x11200000
TOP = 0x12401000
TABLE_PAGES = 59
CHECKPOINT = "vm-physmap-before-ttbr"


def template(kernel, count):
    """Return 59 physical table pages, with only eight alias L2 words zeroed."""
    complete_physmap_plan(kernel)
    if count not in (1, 2):
        raise ValueError("Unreviewed initial L2 count")
    reference = CompletePhysmapReference(inspect(kernel)["segments"], VIRTUAL, PHYSICAL, TOP, count)
    reference.end_kernel = VIRTUAL + 0xf6c000
    reference.physmap = VIRTUAL + TOP - PHYSICAL + (0x3ffff000 if count == 2 else 0)
    pages = bytearray(reference.expected(CHECKPOINT))
    if len(pages) != TABLE_PAGES*4096:
        raise ValueError("Complete physmap template escaped the exact 59-page model")
    first_link, _, _ = reference.first_descriptors()
    _, writes, _ = reference.complete_state("__PHYSMAP_REST")
    aliases = {first_link} | {address for address, (_, kind) in writes.items() if kind != "page"}
    if (len(aliases) != 8 or sum(kind == "link" for _, kind in writes.values()) != 1
            or sum(kind == "block" for _, kind in writes.values()) != 6):
        raise ValueError("Unreviewed physical-aperture alias cell layout")
    for address in aliases:
        struct.pack_into("<Q", pages, address - TOP, 0)
    return bytes(pages)


def _replace_definitions(header, names):
    lines = []
    continuation = False
    for line in header.splitlines():
        if continuation:
            continuation = line.rstrip().endswith("\\")
            continue
        match = re.match(r"^\s*#\s*define\s+([A-Za-z_]\w*)(?=\s|\(|$)", line)
        if match and match.group(1) in names:
            continuation = line.rstrip().endswith("\\")
            continue
        lines.append(line)
    return "\n".join(lines) + ("\n" if lines else "")


def configure_physmap_carrier(kernel, header, review):
    """Replace dynamic-prefix expectations; retain the existing return observer."""
    target = complete_physmap_plan(kernel)[CHECKPOINT]
    if review.get("values", {}).get("MIDO_EARLY_VIRT_BASE", VIRTUAL) != VIRTUAL:
        raise ValueError("Complete physmap carrier requires the pinned virtual base")
    symbols = macho_symbols(kernel)
    segment = next(segment for segment in inspect(kernel)["segments"]
                   if segment["vmaddr"] <= target < segment["vmaddr"] + segment["filesize"])
    original = struct.unpack_from("<I", kernel, segment["fileoff"] + target - segment["vmaddr"])[0]
    definitions = {
        "MIDO_VM_PHYSMAP_COMPLETE": 1,
        "MIDO_VM_DYNAMIC_PAGES": TABLE_PAGES,
        "MIDO_VM_AVAIL_EXPECTED": TOP + TABLE_PAGES*4096,
        "MIDO_C_EXPECTED_X0": TOP + 4096,
        "MIDO_VM_PROTECTION_WORDS": TABLE_PAGES*512,
        "MIDO_VM_PROTECTION_WORDS_TWO": TABLE_PAGES*512,
        "MIDO_PHYSMAP_TOP": TOP,
        "MIDO_PHYSMAP_PHYSICAL": PHYSICAL,
        "MIDO_PHYSMAP_VIRTUAL": VIRTUAL,
        "MIDO_PHYSMAP_TABLE_PAGES": TABLE_PAGES,
        "MIDO_PHYSMAP_PTOV_PA": PHYSICAL + symbols["_ptov_table"] - VIRTUAL,
        "MIDO_PHYSMAP_INDEX_PA": PHYSICAL + symbols["_ptov_index"] - VIRTUAL,
        "MIDO_EARLY_STOP_PA": PHYSICAL + target - VIRTUAL,
        "MIDO_NATIVE_STOP_WORD": original}
    span_definitions = {}
    for count, suffix in ((1, ""), (2, "_TWO")):
        pages = template(kernel, count)
        words = list(struct.unpack(f"<{TABLE_PAGES*512}Q", pages))
        spans = encode(words)
        if decode(spans, len(words)) != words:
            raise ValueError("Lossless complete physmap reference encoding differs")
        span_definitions["MIDO_VM_PROTECTION_SPANS" + suffix] = "{" + ",".join(
            f"{{{span['start']},{span['count']},0x{span['value']:x}ULL,0x{span['step']:x}ULL}}"
            for span in spans) + "}"
    header = _replace_definitions(header, set(definitions) | set(span_definitions))
    header += "".join(f"#define {name} 0x{value:x}ULL\n" for name, value in definitions.items())
    header += "".join(f"#define {name} {value}\n" for name, value in span_definitions.items())
    review = deepcopy(review)
    review.setdefault("values", {})["MIDO_EARLY_STOP_PA"] = definitions["MIDO_EARLY_STOP_PA"]
    for name in definitions.keys() & review["values"].keys():
        review["values"][name] = definitions[name]
    review.setdefault("post_c_definitions", {}).update(definitions)
    review.update(vm_physmap_complete=True, vm_protection_bytes=TABLE_PAGES*4096,
                  vm_protection_variant_bytes={"1": TABLE_PAGES*4096, "2": TABLE_PAGES*4096},
                  vm_physmap_checkpoint=CHECKPOINT, stop_va=target, original_stop_word=original,
                  scope="Original complete inactive physmap and PTOV publication; halt before TTBR replacement",
                  stops_before=["Translation-table replacement", "Unmasking interrupts", "Storage or userland"])
    return header, review
