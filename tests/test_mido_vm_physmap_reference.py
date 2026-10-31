import os
from pathlib import Path
import struct
import unittest

from tools.inspect_xnu import inspect
from tools.mido_vm_checkpoint_plan import physmap_plan
from tools.mido_vm_physmap_reference import PhysmapReference, PHYSMAP_STAGES, append_entry


VIRTUAL = 0xfffffff007000000
PHYSICAL = 0x11200000
TOP = 0x12401000
MEMORY = 0x2000000


class PhysmapReferenceTests(unittest.TestCase):
    def kernel(self):
        path = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", Path(__file__).resolve().parents[1] /
                                   "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"))
        if not path.exists():
            self.skipTest("Pinned kernel unavailable")
        return path.read_bytes()

    def entry(self, original=VIRTUAL, length=0x4000, slide=0, entries=()):
        return append_entry(entries, original, length, VIRTUAL+TOP-PHYSICAL+slide,
                            VIRTUAL, PHYSICAL, MEMORY)

    def test_four_boundaries_precede_activation(self):
        plan = physmap_plan(self.kernel())
        self.assertEqual(tuple(plan), tuple(PHYSMAP_STAGES))
        self.assertEqual(plan["vm-physmap-first-request"], 0xfffffff00744696c)
        self.assertEqual(plan["vm-physmap-first-entry"], 0xfffffff0074474e0)
        self.assertEqual(plan["vm-physmap-first-map-call"], 0xfffffff0074475e8)
        self.assertEqual(plan["vm-physmap-first-mapped"], 0xfffffff007446970)

    def test_unknown_kernel_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact reviewed"):
            physmap_plan(b"unknown")

    def test_first_mapping_preserves_physical_address_and_nonzero_length(self):
        entry = self.entry()
        self.assertEqual((entry.physical, entry.length), (PHYSICAL, 0x4000))
        self.assertEqual(entry.virtual, VIRTUAL+0x1400000)
        self.assertEqual(struct.unpack("<QQQ", entry.encode()),
                         (entry.physical, entry.virtual, entry.length))

    def test_block_alignment_for_all_page_offsets(self):
        for index in range(512):
            entry = self.entry(slide=index*4096)
            candidate = VIRTUAL+TOP-PHYSICAL+index*4096
            self.assertGreaterEqual(entry.virtual, candidate)
            self.assertLess(entry.virtual-candidate, 0x200000)
            self.assertEqual(entry.virtual & 0x1fffff, entry.physical & 0x1fffff)

    def test_sequential_entries_do_not_overlap(self):
        entries = []
        for index in range(8):
            entry = self.entry(original=VIRTUAL+index*0x4000, entries=entries)
            if entries:
                self.assertGreaterEqual(entry.virtual, entries[-1].virtual+entries[-1].length)
            entries.append(entry)
        with self.assertRaisesRegex(ValueError, "request"):
            self.entry(entries=entries)

    def test_length_rounds_up_without_mapping_past_arena(self):
        self.assertEqual(self.entry(length=4097).length, 8192)
        self.assertEqual(self.entry(original=VIRTUAL+MEMORY-4096, length=1).length, 4096)
        with self.assertRaisesRegex(ValueError, "request"):
            self.entry(original=VIRTUAL+MEMORY-4096, length=4097)

    def test_invalid_requests_rejected(self):
        for original, length in ((VIRTUAL+1, 4096), (VIRTUAL-4096, 4096),
                                 (VIRTUAL, 0), (VIRTUAL, -1), (VIRTUAL, MEMORY+1)):
            with self.subTest(original=original, length=length):
                with self.assertRaises(ValueError):
                    self.entry(original=original, length=length)

    def test_overflow_and_noncanonical_targets_rejected(self):
        for target in (0, (1 << 64)-4096, 1 << 64, VIRTUAL+1):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    append_entry([], VIRTUAL, 0x4000, target, VIRTUAL, PHYSICAL, MEMORY)

    def test_mapping_arguments_are_rw_nonexecuting_and_block_capable(self):
        kernel = self.kernel()
        ref = PhysmapReference(inspect(kernel)["segments"], VIRTUAL, PHYSICAL, TOP)
        target = VIRTUAL+0x1400000
        self.assertEqual(ref.first_arguments(VIRTUAL+TOP-PHYSICAL),
                         (target, 0x4000, target-VIRTUAL, 1, 0, 1, 3))

    def test_preparation_never_changes_inactive_tables(self):
        for count in (1, 2):
            ref = PhysmapReference(inspect(self.kernel())["segments"], VIRTUAL, PHYSICAL, TOP, count)
            before = ref.expected("vm-physmap-entry")
            for checkpoint in PHYSMAP_STAGES:
                if checkpoint == "vm-physmap-first-mapped":
                    continue
                self.assertEqual(ref.expected(checkpoint), before)
                self.assertEqual(len(before), 56*4096)

    def test_first_mapping_has_four_rw_xn_leaves_and_exact_extra_page(self):
        from tools.mido_vm_translation_audit import walk

        for count, slide in ((1, 0), (2, 0x3ffff000)):
            ref = PhysmapReference(inspect(self.kernel())["segments"], VIRTUAL, PHYSICAL, TOP, count)
            ref.physmap = VIRTUAL+TOP-PHYSICAL+slide
            entry = ref.first_entry(ref.physmap)
            snapshot = ref.expected("vm-physmap-first-mapped")
            self.assertEqual(len(snapshot), 57*4096)
            for index in range(4):
                result = walk(snapshot, entry.virtual+index*4096)
                self.assertTrue(result["mapped"])
                self.assertEqual(result["physical"], PHYSICAL+index*4096)
                self.assertTrue(result["writable"])
                self.assertFalse(result["executable"])
                self.assertFalse(result["user_accessible"])
                self.assertTrue(result["access_flag"])
            self.assertFalse(walk(snapshot, entry.virtual+0x4000)["mapped"])
            link, descriptor, leaves = ref.first_descriptors()
            helper = 0x10000
            ref.request = "__PHYSMAP_FIRST"
            self.assertTrue(ref.accepts(link, 8, descriptor, helper+0x128, helper))
            for address, value in leaves.items():
                self.assertTrue(ref.accepts(address, 8, value, helper+0x210, helper))
                self.assertFalse(ref.accepts(address, 8, value ^ (1 << 53), helper+0x210, helper))
                self.assertFalse(ref.accepts(address, 8, value, helper+0x214, helper))

    def test_boundary_slides_with_geometry_derived_count_reach_dynamic_rest_roots(self):
        from tools.mido_vm_geometry import l2_count
        from tools.mido_vm_physmap_complete_reference import CompletePhysmapReference
        from tools.mido_vm_translation_audit import walk

        segments = inspect(self.kernel())["segments"]
        for slide in (0x36e00000, 0x37bff000):
            with self.subTest(slide=slide):
                physmap = VIRTUAL + TOP - PHYSICAL + slide
                count = l2_count(VIRTUAL, PHYSICAL, TOP, physmap, physmap + 0x3000000, MEMORY)
                self.assertEqual(count, 1)
                ref = CompletePhysmapReference(segments, VIRTUAL, PHYSICAL, TOP, count)
                ref.physmap = physmap
                ref.end_kernel = VIRTUAL + 0xf6c000
                first = ref.first_entry(physmap)
                snapshot = ref.expected("vm-physmap-before-ttbr")
                self.assertEqual(len(snapshot), 59*4096)
                for index in range(4):
                    result = walk(snapshot, first.virtual + index*4096)
                    self.assertTrue(result["mapped"])
                    self.assertEqual(result["physical"], PHYSICAL + index*4096)
                    self.assertTrue(result["writable"])
                    self.assertFalse(result["executable"])
                    self.assertFalse(result["user_accessible"])
                    self.assertTrue(result["access_flag"])
                ref.request = "__PHYSMAP_REST"
                self.assertIn(TOP + 9*4096, ref.allowed_l2_roots())
                rest = ref.rest_entry()
                for address in (rest.virtual, rest.virtual + rest.length - 4096):
                    result = walk(snapshot, address)
                    self.assertTrue(result["mapped"])
                    self.assertEqual(result["physical"], TOP + address - rest.virtual)
                    self.assertTrue(result["writable"])
                    self.assertFalse(result["executable"])
                    self.assertFalse(result["user_accessible"])
                    self.assertTrue(result["access_flag"])

    def test_first_alias_can_use_dynamic_root_193_with_one_initial_root(self):
        from tools.mido_vm_geometry import l2_count
        from tools.mido_vm_translation_audit import walk

        segments = inspect(self.kernel())["segments"]
        for slide in (0x37c00000, 0x37dff000):
            with self.subTest(slide=slide):
                physmap = VIRTUAL + TOP - PHYSICAL + slide
                count = l2_count(VIRTUAL, PHYSICAL, TOP, physmap, physmap + 0x3000000, MEMORY)
                self.assertEqual(count, 1)
                ref = PhysmapReference(segments, VIRTUAL, PHYSICAL, TOP, count)
                ref.physmap = physmap
                entry = ref.first_entry(physmap)
                self.assertEqual((entry.virtual >> 30) & 255, 193)
                link, descriptor, leaves = ref.first_descriptors()
                root = TOP + 9*4096
                self.assertEqual(link, root + ((entry.virtual >> 21) & 511)*8)
                self.assertEqual(descriptor, (TOP + 56*4096) | 3)
                before = ref.expected("vm-physmap-entry")
                self.assertEqual(struct.unpack_from("<Q", before, 4096 + 193*8)[0] & 0xfffffffff000,
                                 root)
                snapshot = ref.expected("vm-physmap-first-mapped")
                self.assertEqual(len(snapshot), 57*4096)
                changed = {TOP + offset for offset in range(0, len(before), 8)
                           if before[offset:offset + 8] != snapshot[offset:offset + 8]}
                self.assertEqual(changed, {link})
                for index in range(4):
                    result = walk(snapshot, entry.virtual + index*4096)
                    self.assertTrue(result["mapped"])
                    self.assertEqual(result["physical"], PHYSICAL + index*4096)
                    self.assertEqual(result["trace"][1]["table"], root)
                    self.assertTrue(result["writable"])
                    self.assertFalse(result["executable"])
                    self.assertFalse(result["user_accessible"])
                    self.assertTrue(result["access_flag"])
                self.assertFalse(walk(snapshot, entry.virtual + 0x4000)["mapped"])
                helper = 0x10000
                ref.request = "__PHYSMAP_FIRST"
                self.assertTrue(ref.accepts(link, 8, descriptor, helper + 0x128, helper))
                wrong_link = TOP + 3*4096 + ((entry.virtual >> 21) & 511)*8
                self.assertFalse(ref.accepts(wrong_link, 8, descriptor, helper + 0x128, helper))
                self.assertFalse(ref.accepts(link, 4, descriptor, helper + 0x128, helper))
                for address, value in leaves.items():
                    self.assertTrue(ref.accepts(address, 8, value, helper + 0x210, helper))
                    self.assertFalse(ref.accepts(address, 8, value ^ (1 << 53), helper + 0x210, helper))

    def test_all_preallocated_root_pages_and_outside_root_rejection(self):
        from tools.mido_vm_translation_audit import walk

        segments = inspect(self.kernel())["segments"]
        base = VIRTUAL & ~0x3fffffff
        for count in (1, 2):
            ref = PhysmapReference(segments, VIRTUAL, PHYSICAL, TOP, count)
            initial = ref.expected("vm-physmap-entry")
            for root in range(48):
                ref.physmap = base + root*0x40000000 + 0x20000000
                entry = ref.first_entry(ref.physmap)
                link, _, _ = ref.first_descriptors()
                page = TOP + (2 + root if root < count else 8 + root)*4096
                self.assertEqual(link, page + ((entry.virtual >> 21) & 511)*8)
                self.assertEqual(struct.unpack_from("<Q", initial, 4096 + (192 + root)*8)[0] &
                                 0xfffffffff000, page)
                self.assertEqual(walk(ref.expected("vm-physmap-first-mapped"), entry.virtual)["physical"],
                                 PHYSICAL)
            for root in (-1, 48):
                ref.physmap = base + root*0x40000000 + 0x20000000
                with self.assertRaisesRegex(ValueError, "preallocated roots"):
                    ref.first_descriptors()
