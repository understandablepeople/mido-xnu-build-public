import struct
import unittest

from tools.mido_ramdisk_fixture import reserve_ramdisk, selected_memory_root


class RamdiskFixtureTests(unittest.TestCase):
    def reserve(self, **options):
        arguments = dict(data=bytes(4096), start=0x22032000, memory_start=0x20000000,
                         memory_size=0x4000000, protected=[(0x20000000, 0x22032000)],
                         command_line="-v rd=md0")
        arguments.update(options)
        return reserve_ramdisk(**arguments)

    def test_native_arm64_property_and_reservation(self):
        result = self.reserve()
        self.assertEqual(struct.unpack("<QQ", result["apple_property"]), (0x22032000, 4096))
        self.assertEqual(result["end"], 0x22033000)
        self.assertFalse(result["filesystem_validated"])
        self.assertFalse(result["boot_approved"])

    def test_explicit_nonconflicting_root_selector_is_required(self):
        for value in ("-v", "rd=md1", "rd=md0 rootdev=md0", "rd=md0 rd=md0"):
            with self.assertRaises(ValueError):
                self.reserve(command_line=value)

    def test_overlap_outside_ram_and_alignment_are_rejected(self):
        for options in (dict(start=0x22031000), dict(start=0x24000000),
                        dict(start=0x22032001), dict(data=bytes(4097)),
                        dict(data=bytes(0)), dict(data=bytes(1024 * 1024 + 4096))):
            with self.assertRaises(ValueError):
                self.reserve(**options)

    def test_selection_requires_original_consistent_device_results(self):
        registration = [dict(returned_device=0x1000000)]
        lookup = [dict(device_index=0, returned_device=0x1000000)]
        result = selected_memory_root(0, "md0", 0x1000000, 0, registration, lookup)
        self.assertTrue(result["root_selected"])
        self.assertFalse(result["root_mounted"])
        self.assertFalse(result["disk_io_validated"])
        with self.assertRaises(ValueError):
            selected_memory_root(0, "md0", 0x1000001, 0, registration, lookup)
        with self.assertRaises(ValueError):
            selected_memory_root(0, "md0", 0x1000000, 0, [], lookup)
        with self.assertRaises(ValueError):
            selected_memory_root(1, "md0", 0x1000000, 0, registration, lookup)

    def test_inlined_lookup_needs_read_only_native_device_table_evidence(self):
        registrations = [dict(returned_device=0x1000000, base_page=0x1234, size_pages=1)]
        record = dict(block_device=0x1000000, flags=1, sector_size=512, base_page=0x1234, size_pages=1)
        result = selected_memory_root(0, "md0", 0x1000000, 0, registrations, [], record)
        self.assertTrue(result["root_selected"])
        for name, value in (("flags", 0), ("block_device", 2), ("base_page", 0), ("size_pages", 2)):
            with self.assertRaises(ValueError):
                selected_memory_root(0, "md0", 0x1000000, 0, registrations, [], dict(record, **{name: value}))
