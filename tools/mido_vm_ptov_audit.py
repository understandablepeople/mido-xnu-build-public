"""Offline validation of the bounded native-4K physical-to-virtual table."""

from collections import Counter
import struct


def verify_ptov(data, entries, sorted_entries=False):
    """Check one or two expected mappings and zero padding without changing inputs.

    Ranges are half-open; an exclusive end of 2**64 is allowed. Sorted tables
    have descending lengths including padding, with no stability rule for ties.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)) or len(data) != 8 * 24:
        raise ValueError("PTOV data must be exactly 192 bytes")
    expected = tuple((entry.physical, entry.virtual, entry.length) for entry in entries)
    if len(expected) not in (1, 2):
        raise ValueError("PTOV requires one or two expected first/rest entries")
    records = tuple(struct.iter_unpack("<QQQ", data))
    active = tuple(record for record in records if record != (0, 0, 0))
    limit = 1 << 64
    minimum_virtual = limit - (1 << 38)

    def validate(mappings):
        for physical, virtual, length in mappings:
            if any(type(value) is not int for value in (physical, virtual, length)):
                raise ValueError("PTOV fields must be integers")
            if (not 0 <= physical < limit or not minimum_virtual <= virtual < limit
                    or not 0 < length < limit or (physical | virtual | length) & 4095
                    or physical + length > limit or virtual + length > limit):
                raise ValueError("Invalid PTOV alignment, length, bounds or canonical TTBR1 range")
        for index, first in enumerate(mappings):
            for second in mappings[index + 1:]:
                for field in (0, 1):
                    if (first[field] < second[field] + second[2]
                            and second[field] < first[field] + first[2]):
                        raise ValueError("PTOV physical or virtual ranges overlap")

    validate(expected)
    validate(active)
    if Counter(records) != Counter(expected + ((0, 0, 0),) * (8 - len(expected))):
        raise ValueError("PTOV records differ from exact expected multiset and zero padding")
    descending = all(first[2] >= second[2] for first, second in zip(records, records[1:]))
    if sorted_entries and not descending:
        raise ValueError("PTOV records are not sorted by descending length")
    return {"entries_verified": len(expected), "sorted_by_length": descending,
            "bytes_verified": 8 * 24}
