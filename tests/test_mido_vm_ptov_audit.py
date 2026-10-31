from dataclasses import replace
import struct
import unittest

from tools.mido_vm_physmap_reference import PhysmapEntry
from tools.mido_vm_ptov_audit import verify_ptov


VIRTUAL = (1 << 64) - (1 << 38)
LIMIT = 1 << 64


class PtovAuditTests(unittest.TestCase):
    def setUp(self):
        self.first = PhysmapEntry(0x11200000, VIRTUAL, 0x4000)
        self.rest = PhysmapEntry(0x11208000, VIRTUAL + 0x200000, 0x8000)
        self.entries = (self.first, self.rest)

    def pack(self, entries, padding=True):
        records = [(entry.physical, entry.virtual, entry.length) for entry in entries]
        if padding:
            records += [(0, 0, 0)] * (8 - len(records))
        return b"".join(struct.pack("<QQQ", *record) for record in records)

    def test_exact_unsorted_and_sorted_tables(self):
        self.assertEqual(verify_ptov(self.pack(self.entries), self.entries),
                         dict(entries_verified=2, sorted_by_length=False, bytes_verified=192))
        self.assertEqual(verify_ptov(self.pack(self.entries[::-1]), self.entries, True),
                         dict(entries_verified=2, sorted_by_length=True, bytes_verified=192))

    def test_wrong_order_only_rejected_when_sort_required(self):
        data = self.pack(self.entries)
        verify_ptov(data, self.entries)
        with self.assertRaisesRegex(ValueError, "descending length"):
            verify_ptov(data, self.entries, True)

    def test_ties_allow_either_order(self):
        entries = (self.first, replace(self.rest, length=self.first.length))
        for order in (entries, entries[::-1]):
            with self.subTest(order=order):
                self.assertTrue(verify_ptov(self.pack(order), entries, True)["sorted_by_length"])

    def test_exact_multiset_allows_interspersed_padding_unless_sorted(self):
        data = bytes(24) + self.pack(self.entries)[:-24]
        verify_ptov(data, self.entries)
        with self.assertRaisesRegex(ValueError, "descending length"):
            verify_ptov(data, self.entries, True)

    def test_duplicate_missing_extra_and_wrong_records(self):
        candidates = ((self.first, self.first), (self.first,), (),
                      (self.first, self.rest, PhysmapEntry(0x12000000, VIRTUAL + 0x400000, 4096)),
                      (self.first, replace(self.rest, physical=0x12000000)),
                      (self.first, replace(self.rest, length=4096)))
        for entries in candidates:
            with self.subTest(entries=entries):
                with self.assertRaises(ValueError):
                    verify_ptov(self.pack(entries), self.entries)

    def test_partial_zero_padding_is_not_empty(self):
        data = self.pack(self.entries)
        for record in ((4096, 0, 0), (0, VIRTUAL, 0), (0, 0, 4096),
                       (4096, VIRTUAL, 0), (0, VIRTUAL + 0x400000, 4096)):
            with self.subTest(record=record):
                mutated = data[:48] + struct.pack("<QQQ", *record) + data[72:]
                with self.assertRaises(ValueError):
                    verify_ptov(mutated, self.entries)

    def test_exact_byte_count(self):
        data = self.pack(self.entries)
        for invalid in (b"", data[:-1], data + bytes(1), data + bytes(24), "x" * 192):
            with self.subTest(length=len(invalid)):
                with self.assertRaisesRegex(ValueError, "exactly 192 bytes"):
                    verify_ptov(invalid, self.entries)

    def test_one_entry_prefix_and_no_premature_second_entry(self):
        entries = (self.first,)
        for require_sorted in (False, True):
            with self.subTest(require_sorted=require_sorted):
                self.assertEqual(verify_ptov(self.pack(entries), entries, require_sorted),
                                 dict(entries_verified=1, sorted_by_length=True, bytes_verified=192))
                with self.assertRaisesRegex(ValueError, "exact expected multiset"):
                    verify_ptov(self.pack(self.entries), entries, require_sorted)

    def test_one_or_two_expected_entries_required(self):
        for entries in ((), self.entries + (self.rest,)):
            with self.subTest(entries=entries):
                with self.assertRaisesRegex(ValueError, "one or two"):
                    verify_ptov(self.pack(self.entries), entries)

    def test_alignment_lengths_canonical_range_and_overflow(self):
        candidates = (
            replace(self.rest, physical=self.rest.physical + 1),
            replace(self.rest, virtual=self.rest.virtual + 1),
            replace(self.rest, length=4097), replace(self.rest, length=0),
            replace(self.rest, virtual=0), replace(self.rest, virtual=VIRTUAL - 4096),
            replace(self.rest, virtual=LIMIT - 4096, length=8192),
            replace(self.rest, physical=LIMIT - 4096, length=8192),
        )
        for invalid in candidates:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    verify_ptov(self.pack((self.first, invalid)), self.entries)
                with self.assertRaises(ValueError):
                    verify_ptov(self.pack(self.entries), (self.first, invalid))

    def test_expected_fields_cannot_wrap_or_use_nonintegers(self):
        for field in ("physical", "virtual", "length"):
            for value in (-4096, LIMIT, LIMIT + 4096, 4096.0, True):
                with self.subTest(field=field, value=value):
                    invalid = replace(self.rest, **{field: value})
                    with self.assertRaises(ValueError):
                        verify_ptov(self.pack(self.entries), (self.first, invalid))

    def test_physical_and_virtual_overlap_rejected_independently(self):
        for invalid in (replace(self.rest, physical=self.first.physical),
                        replace(self.rest, physical=self.first.physical + 4096),
                        replace(self.rest, virtual=self.first.virtual),
                        replace(self.rest, virtual=self.first.virtual + 4096)):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "overlap"):
                    verify_ptov(self.pack((self.first, invalid)), self.entries)
                with self.assertRaisesRegex(ValueError, "overlap"):
                    verify_ptov(self.pack(self.entries), (self.first, invalid))

    def test_adjacent_ranges_and_exclusive_top_boundary_are_valid(self):
        adjacent = replace(self.rest, physical=self.first.physical + self.first.length,
                           virtual=self.first.virtual + self.first.length)
        entries = (self.first, adjacent)
        verify_ptov(self.pack(entries), entries)
        top = PhysmapEntry(LIMIT - 4096, LIMIT - 4096, 4096)
        entries = (self.first, top)
        verify_ptov(self.pack(entries), entries, True)
        zero_physical = replace(self.first, physical=0)
        entries = (zero_physical, self.rest)
        verify_ptov(self.pack(entries), entries)

    def test_inputs_are_not_modified(self):
        entries = list(self.entries)
        data = bytearray(self.pack(entries))
        original = bytes(data)
        verify_ptov(data, entries)
        self.assertEqual(data, original)
        self.assertEqual(entries, list(self.entries))


if __name__ == "__main__":
    unittest.main()
