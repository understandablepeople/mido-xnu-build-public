import hashlib
import os
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols
from tools.mido_native4k_profile import KERNEL_SHA256
from tools.mido_vm_physmap_complete_reference import (
    COMPLETE_PHYSMAP_STAGES, CompletePhysmapReference)
from tools.mido_vm_physmap_reference import PHYSMAP_STAGES, PhysmapReference
from tools.mido_vm_translation_audit import walk


VIRTUAL = 0xfffffff007000000
PHYSICAL = 0x11200000
TOP = 0x12401000
END_KERNEL = VIRTUAL + 0xf6c000


class CompletePhysmapReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", Path(__file__).resolve().parents[1] /
                                   "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"))
        if not path.exists():
            raise unittest.SkipTest("Pinned kernel unavailable")
        cls.kernel = path.read_bytes()
        cls.segments = inspect(cls.kernel)["segments"]

    def reference(self, count=1, physmap=None, top=TOP, end_kernel=END_KERNEL):
        reference = CompletePhysmapReference(self.segments, VIRTUAL, PHYSICAL, top, count)
        reference.physmap = VIRTUAL + top - PHYSICAL if physmap is None else physmap
        reference.end_kernel = end_kernel
        return reference

    def word(self, snapshot, physical):
        return struct.unpack_from("<Q", snapshot, physical - TOP)[0]

    def test_reviewed_pinned_calls_and_store_instructions(self):
        self.assertEqual(hashlib.sha256(self.kernel).hexdigest(), KERNEL_SHA256)
        symbols = macho_symbols(self.kernel)

        def instruction(symbol, displacement):
            address = symbols[symbol] + displacement
            segment = next(segment for segment in self.segments
                           if segment["vmaddr"] <= address < segment["vmaddr"] + segment["filesize"])
            return struct.unpack_from("<I", self.kernel,
                                      segment["fileoff"] + address - segment["vmaddr"])[0]

        calls = ((0x1358, "_arm_vm_page_granular_prot"),
                 (0x1384, "_arm_vm_physmap_slide"), (0x13c0, "_qsort.specialized.1"),
                 (0x13d4, "_memcpy"))
        for displacement, target in calls:
            word = instruction("_arm_vm_init", displacement)
            self.assertEqual(word & 0xfc000000, 0x94000000)
            immediate = word & 0x3ffffff
            if immediate & 0x2000000:
                immediate -= 0x4000000
            self.assertEqual(symbols["_arm_vm_init"] + displacement + immediate*4, symbols[target])
        for symbol, displacement, word in (
                ("_arm_vm_page_granular_helper", 0x128, 0xf83b7928),
                ("_arm_vm_page_granular_helper", 0x210, 0xf9000134),
                ("_arm_vm_page_granular_prot", 0x200, 0xf9000388),
                ("_arm_vm_page_granular_prot", 0x260, 0xc89ffd28),
                ("_arm_vm_page_granular_prot", 0x26c, 0xc89ffd28)):
            self.assertEqual(instruction(symbol, displacement), word)
        self.assertEqual(symbols["_arm_vm_page_granular_helper"] -
                         symbols["_arm_vm_page_granular_prot"], 0x300)

    def test_arguments_and_stage_offsets(self):
        reference = self.reference()
        self.assertEqual(reference.arguments("__PHYSMAP_HANDOFF"),
                         (END_KERNEL, 0x295000, 0, 1, 0, 1, 3))
        self.assertEqual(reference.arguments("__PHYSMAP_REST"),
                         (VIRTUAL + 0x1601000, 0xdff000, 0x400000, 1, 0, 1, 3))
        self.assertEqual([offset for _, offset in COMPLETE_PHYSMAP_STAGES.values()],
                         [0x1358, 0x135c, 0x1384, 0x1388, 0x13c0, 0x13c4, 0x13d4, 0x13d8, 0x13e4])

    def test_runtime_first_request_uses_completed_allocation_limit_and_uint64_arguments(self):
        reference = self.reference()
        reference.request = "__PHYSMAP_FIRST"
        self.assertEqual(reference.arguments(reference.request),
                         (VIRTUAL + 0x1400000, 0x4000, 0x1400000, 1, 0, 1, 3))
        self.assertEqual(reference.allocation_limit(), 59)
        self.assertEqual(reference.request, "__PHYSMAP_FIRST")
        self.assertEqual(reference.allowed_l2_roots(), {TOP + 8192})
        for request in ("__PHYSMAP_FIRST", "__PHYSMAP_HANDOFF", "__PHYSMAP_REST"):
            arguments = reference.arguments(request)
            self.assertTrue(all(0 <= value < 1 << 64 for value in arguments))
            start, _, offset, *_ = arguments
            expected_physical = PHYSICAL if request == "__PHYSMAP_FIRST" else (
                TOP if request == "__PHYSMAP_REST" else PHYSICAL + END_KERNEL - VIRTUAL)
            self.assertEqual((start - VIRTUAL + PHYSICAL - offset) & 0xffffffffffffffff,
                             expected_physical)

    def test_negative_slide_offsets_are_encoded_as_unsigned_register_values(self):
        reference = self.reference(physmap=VIRTUAL - 0x200000)
        self.assertEqual(reference.arguments("__PHYSMAP_FIRST")[2], (1 << 64) - 0x200000)
        entry = reference.rest_entry()
        self.assertEqual(reference.arguments("__PHYSMAP_REST")[2],
                         (entry.virtual - (VIRTUAL + TOP - PHYSICAL)) & 0xffffffffffffffff)
        with self.assertRaises(ValueError):
            reference.allocation_limit()

    def test_original_stages_and_mapping_are_unchanged(self):
        for count in (1, 2):
            reference = self.reference(count)
            original = PhysmapReference(self.segments, VIRTUAL, PHYSICAL, TOP, count)
            original.physmap = reference.physmap
            for checkpoint in PHYSMAP_STAGES:
                self.assertEqual(reference.expected(checkpoint), original.expected(checkpoint))
            initial = original.expected("vm-physmap-first-mapped")
            final = reference.expected("vm-physmap-before-ttbr")
            for offset in range(0, len(initial), 8):
                if initial[offset:offset + 8] != bytes(8):
                    self.assertEqual(final[offset:offset + 8], initial[offset:offset + 8])

    def test_exact_allocation_links_blocks_and_hint_edges(self):
        reference = self.reference()
        handoff = reference.expected("vm-physmap-handoff-mapped")
        final = reference.expected("vm-physmap-rest-mapped")
        self.assertEqual((len(handoff)//4096, len(final)//4096, reference.allocation_limit()),
                         (58, 59, 59))
        root = TOP + 8192
        self.assertEqual(self.word(handoff, root + ((VIRTUAL + 0x1200000) >> 21 & 511)*8),
                         (TOP + 57*4096) | 3)
        self.assertEqual(self.word(final, root + ((VIRTUAL + 0x1600000) >> 21 & 511)*8),
                         (TOP + 58*4096) | 3)
        for address in (VIRTUAL + 0x1000000, VIRTUAL + 0x1800000):
            result = walk(final, address)
            self.assertEqual(result["leaf_level"], 2)
            self.assertEqual(result["trace"][-1]["descriptor"],
                             (address - VIRTUAL + PHYSICAL - (0x400000 if address >= VIRTUAL + 0x1800000 else 0)) |
                             0x0060000000000601)
        for address, hinted in ((END_KERNEL, False), (VIRTUAL + 0xf70000, True),
                                (VIRTUAL + 0x1200000, False),
                                (VIRTUAL + 0x1601000, False), (VIRTUAL + 0x1610000, True),
                                (VIRTUAL + 0x17ff000, True)):
            result = walk(final, address)
            self.assertEqual(result["leaf_level"], 3)
            self.assertEqual(bool(result["trace"][-1]["descriptor"] & (1 << 52)), hinted)
        self.assertEqual(self.word(final, TOP + 57*4096 + 8), 0)
        self.assertEqual(self.word(final, TOP + 58*4096), 0)

    def test_all_new_translations_have_exact_physical_and_permissions(self):
        for count in (1, 2):
            reference = self.reference(count)
            final = reference.expected("vm-physmap-before-ttbr")
            for request in ("__PHYSMAP_HANDOFF", "__PHYSMAP_REST"):
                start, length, offset, *_ = reference.arguments(request)
                for address in range(start, start + length, 4096):
                    result = walk(final, address)
                    self.assertTrue(result["mapped"])
                    self.assertEqual(result["physical"], address - VIRTUAL + PHYSICAL - offset)
                    self.assertTrue(result["writable"])
                    self.assertFalse(result["executable"])
                    self.assertFalse(result["user_accessible"])
                    self.assertTrue(result["access_flag"])
                self.assertFalse(walk(final, start + length)["mapped"])

    def test_sort_and_publish_leave_tables_identical(self):
        reference = self.reference()
        first = reference.expected("vm-physmap-first-mapped")
        handoff = reference.expected("vm-physmap-handoff-mapped")
        final = reference.expected("vm-physmap-rest-mapped")
        self.assertEqual(reference.expected("vm-physmap-handoff-request"), first)
        self.assertEqual(reference.expected("vm-physmap-rest-request"), handoff)
        for checkpoint in tuple(COMPLETE_PHYSMAP_STAGES)[4:]:
            self.assertEqual(reference.expected(checkpoint), final)

    def test_exact_request_scoped_write_allowlist(self):
        reference = self.reference()
        helper = 0x100000
        sites = {"link": helper + 0x128, "page": helper + 0x210,
                 "block": helper - 0x300 + 0x200}
        all_sites = set(sites.values()) | {helper - 0x300 + 0x260, helper - 0x300 + 0x26c}
        previous_writes = {}
        for request in ("__PHYSMAP_HANDOFF", "__PHYSMAP_REST"):
            reference.request = request
            _, writes, _ = reference.complete_state(request)
            for address, (value, kind) in writes.items():
                self.assertTrue(reference.accepts(address, 8, value, sites[kind], helper))
                self.assertFalse(reference.accepts(address, 4, value, sites[kind], helper))
                self.assertFalse(reference.accepts(address + 1, 8, value, sites[kind], helper))
                self.assertFalse(reference.accepts(address, 8, value ^ (1 << 53), sites[kind], helper))
                for site in all_sites:
                    allowed = site == sites[kind]
                    self.assertEqual(reference.accepts(address, 8, value, site, helper), allowed)
                self.assertFalse(reference.accepts(address, 8, value, sites[kind] + 4, helper))
            for address, (value, kind) in previous_writes.items():
                self.assertFalse(reference.accepts(address, 8, value, sites[kind], helper))
            previous_writes = writes
        reference.request = "__PHYSMAP_FIRST"
        link, value, leaves = reference.first_descriptors()
        self.assertTrue(reference.accepts(link, 8, value, helper + 0x128, helper))
        for address, value in leaves.items():
            self.assertTrue(reference.accepts(address, 8, value, helper + 0x210, helper))

    def test_root_sets_include_dynamic_root_across_one_gib_boundary(self):
        for count in (1, 2):
            reference = self.reference(count, (VIRTUAL & ~0x3fffffff) + 0x3fe00000)
            reference.request = "__PHYSMAP_HANDOFF"
            self.assertEqual(reference.allowed_l2_roots(), {TOP + 8192})
            reference.request = "__PHYSMAP_FIRST"
            self.assertEqual(reference.allowed_l2_roots(), {TOP + 8192})
            reference.request = "__PHYSMAP_REST"
            expected_root = TOP + (3 if count == 2 else 9)*4096
            self.assertEqual(reference.allowed_l2_roots(), {expected_root})
            final = reference.expected("vm-physmap-before-ttbr")
            entry = reference.rest_entry()
            self.assertEqual(walk(final, entry.virtual)["physical"], TOP)
            self.assertEqual(reference.allocation_limit(), len(final)//4096)

    def test_invalid_observations_fail_closed(self):
        for end_kernel in (None, END_KERNEL + 1, END_KERNEL - 4096,
                           VIRTUAL + TOP - PHYSICAL + 4096):
            reference = self.reference(end_kernel=end_kernel)
            with self.subTest(end_kernel=end_kernel):
                with self.assertRaises(ValueError):
                    reference.arguments("__PHYSMAP_HANDOFF")
        reference = self.reference(physmap=VIRTUAL + 0x4000)
        with self.assertRaises(ValueError):
            reference.expected("vm-physmap-rest-mapped")
        reference = self.reference(physmap=(VIRTUAL & ~0x3fffffff) + 0x3bffe00000)
        with self.assertRaises(ValueError):
            reference.allocation_limit()

    def test_rest_can_span_two_roots_and_first_can_use_second_initial_root(self):
        cases = ((1, 0x3fc00000, {TOP + 8192, TOP + 9*4096}),
                 (2, 0x7fc00000, {TOP + 3*4096, TOP + 10*4096}))
        for count, displacement, roots in cases:
            reference = self.reference(count, (VIRTUAL & ~0x3fffffff) + displacement)
            reference.request = "__PHYSMAP_REST"
            self.assertEqual(reference.allowed_l2_roots(), roots)
            snapshot = reference.expected("vm-physmap-before-ttbr")
            entry = reference.rest_entry()
            for address in range(entry.virtual, entry.virtual + entry.length, 4096):
                self.assertEqual(walk(snapshot, address)["physical"], TOP + address - entry.virtual)

    def test_observation_changes_do_not_reuse_stale_state(self):
        reference = self.reference()
        original = reference.expected("vm-physmap-before-ttbr")
        reference.physmap = (VIRTUAL & ~0x3fffffff) + 0x3fc00000
        changed = reference.expected("vm-physmap-before-ttbr")
        self.assertNotEqual(changed, original)
        reference.physmap = VIRTUAL + TOP - PHYSICAL
        self.assertEqual(reference.expected("vm-physmap-before-ttbr"), original)
        reference.end_kernel = VIRTUAL + 0x1000000
        self.assertNotEqual(reference.expected("vm-physmap-before-ttbr"), original)
        reference.physmap = None
        with self.assertRaises(ValueError):
            reference.arguments("__PHYSMAP_REST")

    def test_complete_states_are_immutable_and_reused_by_every_store(self):
        reference = self.reference()
        helper = 0x100000
        sites = {"link": helper + 0x128, "page": helper + 0x210,
                 "block": helper - 0x300 + 0x200}
        with patch.object(reference, "_build_complete_state",
                          wraps=reference._build_complete_state) as build:
            for request in ("__PHYSMAP_HANDOFF", "__PHYSMAP_REST"):
                reference.request = request
                state = reference.complete_state(request)
                self.assertIs(reference.complete_state(request), state)
                self.assertIs(reference.allowed_l2_roots(), state[2])
                for address, (value, kind) in state[1].items():
                    self.assertTrue(reference.accepts(address, 8, value, sites[kind], helper))
                    for displacement in (0x260, 0x26c):
                        self.assertFalse(reference.accepts(address, 8, value,
                                                           helper - 0x300 + displacement, helper))
                self.assertEqual(build.call_count, 1 if request == "__PHYSMAP_HANDOFF" else 2)
            self.assertIs(reference.expected("vm-physmap-before-ttbr"), state[0])
            self.assertEqual(reference.allocation_limit(), 59)
            self.assertEqual(build.call_count, 2)
        self.assertIsInstance(state[0], bytes)
        self.assertIsInstance(state[2], frozenset)
        address = next(iter(state[1]))
        with self.assertRaises(TypeError):
            state[1][address] = (0, "page")
        with self.assertRaises(AttributeError):
            state[2].add(TOP)
        self.assertEqual(set(reference._complete_states), {
            (request, reference.physmap, reference.end_kernel, reference.l2_count)
            for request in ("__PHYSMAP_HANDOFF", "__PHYSMAP_REST")})

    def test_cache_is_instance_local_and_keyed_by_observed_geometry(self):
        reference = self.reference()
        request = "__PHYSMAP_REST"
        with patch.object(reference, "_build_complete_state",
                          wraps=reference._build_complete_state) as build:
            initial = reference.complete_state(request)
            initial_physmap = reference.physmap
            reference.physmap = (VIRTUAL & ~0x3fffffff) + 0x3fc00000
            relocated = reference.complete_state(request)
            self.assertIsNot(relocated, initial)
            reference.physmap = initial_physmap
            self.assertIs(reference.complete_state(request), initial)
            reference.end_kernel = VIRTUAL + 0x1000000
            self.assertIsNot(reference.complete_state(request), initial)
            reference.end_kernel = END_KERNEL
            self.assertIs(reference.complete_state(request), initial)
            self.assertEqual(build.call_count, 3)
        separate = self.reference()
        self.assertEqual(separate._complete_states, {})
        self.assertIsNot(separate.complete_state(request), initial)
        reference.end_kernel = None
        with self.assertRaises(ValueError):
            reference.complete_state(request)
        self.assertNotIn((request, reference.physmap, None, reference.l2_count),
                         reference._complete_states)

    def test_empty_handoff_and_aligned_rest_use_no_unnecessary_tables(self):
        top = PHYSICAL + 0x1200000
        reference = self.reference(top=top, end_kernel=VIRTUAL + 0x1200000)
        self.assertEqual(reference.arguments("__PHYSMAP_HANDOFF")[1], 0)
        reference.request = "__PHYSMAP_HANDOFF"
        self.assertEqual(reference.allowed_l2_roots(), set())
        self.assertEqual(reference.expected("vm-physmap-handoff-mapped"),
                         reference.expected("vm-physmap-first-mapped"))
        self.assertEqual(reference.allocation_limit(), 57)

    def test_rest_reuses_first_physmap_table_without_relinking(self):
        top = PHYSICAL + 0x1205000
        reference = self.reference(top=top)
        reference.request = "__PHYSMAP_REST"
        snapshot, writes, _ = reference.complete_state(reference.request)
        self.assertFalse(any(kind == "link" for _, kind in writes.values()))
        self.assertEqual(reference.allocation_limit(), 58)
        entry = reference.rest_entry()
        result = walk(snapshot, entry.virtual, top=top)
        self.assertEqual(result["physical"], top)
        self.assertEqual(result["trace"][-1]["table"], top + 56*4096)
        first = reference.first_entry(reference.physmap)
        for displacement in range(0, first.length, 4096):
            self.assertEqual(walk(snapshot, first.virtual + displacement, top=top)["physical"],
                             PHYSICAL + displacement)


if __name__ == "__main__":
    unittest.main()
