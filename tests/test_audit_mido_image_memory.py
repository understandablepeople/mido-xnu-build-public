from copy import deepcopy
import unittest
from unittest.mock import patch

from tools.audit_mido_image_memory import audit, extent


class ImageMemoryAuditTests(unittest.TestCase):
    def setUp(self):
        self.image = dict(sha256="kernel", entry_va=0x1000,
                          segments=[dict(vmaddr=0x1000, vmsize=0x1000, fileoff=0, filesize=0x800)])
        self.fixture = dict(purpose="synthetic offline transfer fixture", kernel_sha256="kernel",
                            physical_base=0x20000000, virtual_base=0x1000, memory_size=0x10000,
                            entry_pa=0x20000000, boot_args_pa=0x20002000, device_tree_pa=0x20003000,
                            top_of_kernel_data=0x20004000, handoff_blob_bytes=0x2000,
                            copy_plan=[[0, 0, 0x800, 0x1000]])
        self.inventory = dict(ram_banks=[extent(0x10000000, 0x70000000)],
                              fixed_reservations=[], unresolved_reservations=[])

    def run_audit(self, loader=None):
        with patch("tools.audit_mido_image_memory.inspect", return_value=self.image):
            return audit(b"kernel", self.fixture, self.inventory, loader)

    def test_clear_snapshot_never_approves_loading(self):
        result = self.run_audit()
        self.assertTrue(result["known_collision_check_passed"])
        for name in ("boot_approved", "platform_memory_approved", "transfer_of_control_allowed"):
            self.assertFalse(result[name])
        self.assertIsNone(result["recommended_load_address"])
        self.assertTrue(result["blockers"])

    def test_whole_ram_claim_not_just_kernel_is_checked(self):
        self.inventory["fixed_reservations"] = [dict(extent(0x2000F000, 0x1000), source="reserved")]
        self.assertFalse(self.run_audit()["known_collision_check_passed"])

    def test_dynamic_pool_stays_unresolved(self):
        self.inventory["unresolved_reservations"] = [dict(source="dynamic", requested_bytes=0x1000)]
        result = self.run_audit()
        self.assertEqual(len(result["unresolved_reservations"]), 1)
        self.assertTrue(any("dynamic/vendor" in item for item in result["blockers"]))

    def test_loader_collision(self):
        loader = dict(runtime_exclusion_candidate=extent(0x20008000, 0x1000),
                      scratch_exclusion_candidate=extent(0x30000000, 0x1000))
        self.assertFalse(self.run_audit(loader)["known_collision_check_passed"])
        loader["runtime_exclusion_candidate"]["end_exclusive"] += 1
        with self.assertRaises(ValueError):
            self.run_audit(loader)

    def test_ram_hole(self):
        self.inventory["ram_banks"] = [extent(0x20000000, 0x8000), extent(0x20009000, 0x7000)]
        self.assertFalse(self.run_audit()["declared_ram_contains_claim"])

    def test_adjacent_banks(self):
        self.inventory["ram_banks"] = [extent(0x20000000, 0x8000), extent(0x20008000, 0x8000)]
        self.assertTrue(self.run_audit()["declared_ram_contains_claim"])

    def test_mismatched_kernel_plan_entry_and_handoff(self):
        original = deepcopy(self.fixture)
        mutations = dict(kernel_sha256="other", copy_plan=[], entry_pa=0,
                         boot_args_pa=0x20000000, device_tree_pa=0x30000000)
        for name, value in mutations.items():
            self.fixture = deepcopy(original)
            self.fixture[name] = value
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.run_audit()

    def test_bad_extents(self):
        for start, size in ((True, 1), (0, 0), (-1, 1), ((1 << 64) - 1, 2)):
            with self.subTest(start=start, size=size), self.assertRaises(ValueError):
                extent(start, size)


if __name__ == "__main__":
    unittest.main()
