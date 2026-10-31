from copy import deepcopy
import os
from pathlib import Path
import re
import struct
import unittest

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols
from tools.mido_vm_physmap_carrier_config import (
    CHECKPOINT, PHYSICAL, TABLE_PAGES, TOP, VIRTUAL, configure_physmap_carrier, template)
from tools.mido_vm_physmap_complete_plan import complete_physmap_plan
from tools.mido_vm_physmap_complete_reference import CompletePhysmapReference
from tools.mido_vm_reference_spans import decode


class PhysmapCarrierConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", Path(__file__).resolve().parents[1] /
                                   "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"))
        if not path.exists():
            raise unittest.SkipTest("Pinned kernel unavailable")
        cls.kernel = path.read_bytes()
        cls.segments = inspect(cls.kernel)["segments"]
        cls.symbols = macho_symbols(cls.kernel)

    def reference(self, count, slide=None):
        reference = CompletePhysmapReference(self.segments, VIRTUAL, PHYSICAL, TOP, count)
        reference.end_kernel = VIRTUAL + 0xf6c000
        reference.physmap = VIRTUAL + TOP - PHYSICAL + (
            (0x3ffff000 if count == 2 else 0) if slide is None else slide)
        return reference

    def base(self):
        return {"values": {"MIDO_EARLY_VIRT_BASE": VIRTUAL, "MIDO_EARLY_STOP_PA": 0},
                "post_c_definitions": {"MIDO_C_RECORD": 0x12400080,
                                       "MIDO_C_RETURN_LITERAL": 0x100,
                                       "MIDO_VM_DYNAMIC_PAGES": 56},
                "vm_dynamic": True, "boot_approved": False,
                "cache_coherency_proven": False, "hardware_execution_proven": False}

    def definitions(self, header):
        definitions = {}
        for line in header.splitlines():
            match = re.match(r"#define (\w+) (.*)$", line)
            if match:
                self.assertNotIn(match[1], definitions)
                definitions[match[1]] = match[2]
        return definitions

    def test_templates_remove_exactly_eight_alias_cells_and_no_handoff_cells(self):
        for count in (1, 2):
            reference = self.reference(count)
            full = reference.expected(CHECKPOINT)
            stripped = template(self.kernel, count)
            self.assertIsInstance(stripped, bytes)
            self.assertEqual(len(stripped), 241664)
            first_link, _, _ = reference.first_descriptors()
            _, rest_writes, _ = reference.complete_state("__PHYSMAP_REST")
            expected = {first_link} | {address for address, (_, kind) in rest_writes.items()
                                       if kind in ("link", "block")}
            changed = {TOP + offset for offset in range(0, len(full), 8)
                       if full[offset:offset + 8] != stripped[offset:offset + 8]}
            self.assertEqual(changed, expected)
            self.assertEqual(len(changed), 8)
            for address in changed:
                self.assertEqual(struct.unpack_from("<Q", stripped, address - TOP)[0], 0)
                root = reference.root_for(reference.first_entry(reference.physmap).virtual, full)
                self.assertTrue(root <= address < root + 4096)
            _, handoff_writes, _ = reference.complete_state("__PHYSMAP_HANDOFF")
            for address, (value, _) in handoff_writes.items():
                self.assertEqual(struct.unpack_from("<Q", stripped, address - TOP)[0], value)
            for page in (56, 57, 58):
                self.assertEqual(stripped[page*4096:(page + 1)*4096],
                                 full[page*4096:(page + 1)*4096])

    def test_variable_alias_reconstruction_matches_full_tables_for_other_slides(self):
        for count, slides in ((1, (0, 0x1000, 0x1ff000, 0x34bff000)),
                              (2, (0x3ffff000, 0x40000000, 0x74bff000))):
            stripped = template(self.kernel, count)
            for slide in slides:
                with self.subTest(count=count, slide=slide):
                    reference = self.reference(count, slide)
                    reconstructed = bytearray(stripped)
                    link, value, _ = reference.first_descriptors()
                    struct.pack_into("<Q", reconstructed, link - TOP, value)
                    _, writes, _ = reference.complete_state("__PHYSMAP_REST")
                    for address, (value, kind) in writes.items():
                        if kind in ("link", "block"):
                            struct.pack_into("<Q", reconstructed, address - TOP, value)
                    self.assertEqual(bytes(reconstructed), reference.expected(CHECKPOINT))

    def test_exact_header_contract_and_pre_ttbr_stop(self):
        header, review = configure_physmap_carrier(self.kernel, "#define UNRELATED 7\n", self.base())
        definitions = self.definitions(header)
        target = complete_physmap_plan(self.kernel)[CHECKPOINT]
        expected = {
            "MIDO_VM_PHYSMAP_COMPLETE": 1, "MIDO_VM_DYNAMIC_PAGES": 59,
            "MIDO_VM_AVAIL_EXPECTED": 0x1243c000, "MIDO_C_EXPECTED_X0": 0x12402000,
            "MIDO_VM_PROTECTION_WORDS": 59*512, "MIDO_VM_PROTECTION_WORDS_TWO": 59*512,
            "MIDO_PHYSMAP_TOP": TOP, "MIDO_PHYSMAP_PHYSICAL": PHYSICAL,
            "MIDO_PHYSMAP_VIRTUAL": VIRTUAL, "MIDO_PHYSMAP_TABLE_PAGES": 59,
            "MIDO_PHYSMAP_PTOV_PA": 0x11351070, "MIDO_PHYSMAP_INDEX_PA": 0x113512c0,
            "MIDO_EARLY_STOP_PA": PHYSICAL + target - VIRTUAL}
        for name, value in expected.items():
            self.assertEqual(int(definitions[name].removesuffix("ULL"), 0), value)
            self.assertEqual(review["post_c_definitions"][name], value)
        self.assertEqual(review["stop_va"], self.symbols["_arm_vm_init"] + 0x13e4)
        self.assertEqual(review["vm_physmap_checkpoint"], CHECKPOINT)
        self.assertEqual(review["values"]["MIDO_EARLY_STOP_PA"], PHYSICAL + target - VIRTUAL)
        segment = next(segment for segment in self.segments
                       if segment["vmaddr"] <= target < segment["vmaddr"] + segment["filesize"])
        word = struct.unpack_from("<I", self.kernel, segment["fileoff"] + target - segment["vmaddr"])[0]
        self.assertEqual(review["original_stop_word"], word)
        self.assertEqual(int(definitions["MIDO_NATIVE_STOP_WORD"].removesuffix("ULL"), 0), word)
        self.assertTrue(review["vm_physmap_complete"])
        self.assertEqual(review["vm_protection_bytes"], 241664)
        self.assertEqual(review["vm_protection_variant_bytes"], {"1": 241664, "2": 241664})
        self.assertIn("Translation-table replacement", review["stops_before"])
        for name in ("boot_approved", "cache_coherency_proven", "hardware_execution_proven"):
            self.assertFalse(review[name])
        self.assertEqual(review["post_c_definitions"]["MIDO_C_RECORD"], 0x12400080)
        self.assertEqual(review["post_c_definitions"]["MIDO_C_RETURN_LITERAL"], 0x100)
        self.assertIn("#define UNRELATED 7\n", header)

    def test_generated_span_macros_decode_to_exact_templates(self):
        header, _ = configure_physmap_carrier(self.kernel, "", self.base())
        definitions = self.definitions(header)
        for count, suffix in ((1, ""), (2, "_TWO")):
            encoded = definitions["MIDO_VM_PROTECTION_SPANS" + suffix]
            spans = [dict(start=int(start), count=int(length), value=int(value, 16), step=int(step, 16))
                     for start, length, value, step in re.findall(
                         r"\{(\d+),(\d+),0x([0-9a-f]+)ULL,0x([0-9a-f]+)ULL\}", encoded)]
            self.assertTrue(spans)
            self.assertLess(len(spans), 500)
            decoded = struct.pack(f"<{TABLE_PAGES*512}Q", *decode(spans, TABLE_PAGES*512))
            self.assertEqual(decoded, template(self.kernel, count))

    def test_conflicting_duplicate_and_continued_macros_are_replaced_safely(self):
        header = ("#define MIDO_VM_PROTECTION_SPANS {old}\n"
                  " # define MIDO_VM_PROTECTION_SPANS \\\n"
                  "  {continued, \\\n"
                  "   obsolete}\n"
                  "#define MIDO_VM_PROTECTION_SPANS_TWO {old_two}\n"
                  "#define MIDO_VM_PROTECTION_WORDS 3\n"
                  "#define MIDO_VM_PROTECTION_WORDS_TWO 4\n"
                  "#define MIDO_VM_DYNAMIC_PAGES 56\n"
                  "#define MIDO_VM_PROTECTION_SPANS_KEEP 9\n")
        generated, review = configure_physmap_carrier(self.kernel, header, self.base())
        definitions = self.definitions(generated)
        self.assertNotIn("obsolete", generated)
        self.assertNotIn("{old", generated)
        self.assertEqual(definitions["MIDO_VM_PROTECTION_SPANS_KEEP"], "9")
        self.assertEqual(configure_physmap_carrier(self.kernel, generated, review), (generated, review))

    def test_unknown_kernel_invalid_count_and_wrong_geometry_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact reviewed"):
            template(b"unknown", 1)
        with self.assertRaisesRegex(ValueError, "exact reviewed"):
            configure_physmap_carrier(b"unknown", "", self.base())
        for count in (0, 3):
            with self.assertRaisesRegex(ValueError, "initial L2"):
                template(self.kernel, count)
        review = self.base()
        review["values"]["MIDO_EARLY_VIRT_BASE"] = VIRTUAL + 4096
        with self.assertRaisesRegex(ValueError, "pinned virtual"):
            configure_physmap_carrier(self.kernel, "", review)


if __name__ == "__main__":
    unittest.main()
