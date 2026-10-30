import os
from pathlib import Path
import struct
import tempfile
import unittest

from tools.inspect_xnu import inspect
from tools.mido_vm_checkpoint_plan import postmap_plan
from tools.mido_vm_postmap_reference import PostmapReference, POSTMAP_STAGES
from tools.mido_vm_translation_audit import walk, run, VIRTUAL, PHYSICAL, TOP


class PostmapReferenceTests(unittest.TestCase):
    def kernel_path(self):
        path = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", Path(__file__).resolve().parents[1] /
                                   "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"))
        if not path.exists():
            self.skipTest("Pinned kernel unavailable")
        return path

    def reference(self, count=1):
        kernel = self.kernel_path().read_bytes()
        postmap_plan(kernel)
        return PostmapReference(inspect(kernel)["segments"], VIRTUAL, PHYSICAL, TOP, count)

    def test_exact_boundaries_before_dynamic_tables(self):
        plan = postmap_plan(self.kernel_path().read_bytes())
        self.assertEqual(tuple(plan), tuple(POSTMAP_STAGES))
        self.assertEqual(plan["vm-protection-returned"], 0xfffffff007446894)
        self.assertEqual(plan["vm-lowglobals-cleared"], 0xfffffff007446918)

    def test_unreviewed_kernel_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exact reviewed"):
            postmap_plan(b"unknown")

    def test_exact_lowglobal_link_and_zero_page_in_both_layouts(self):
        for count in (1, 2):
            reference = self.reference(count)
            previous = reference.expected("vm-protection-returned")
            before = reference.expected("vm-lowglobals-before-clear")
            after = reference.expected("vm-lowglobals-cleared")
            self.assertEqual(len(after), len(previous) + 4096)
            self.assertEqual(len(after), (8 + count) * 4096)
            self.assertEqual(before[-4096:], bytes([165]) * 4096)
            self.assertEqual(after[-4096:], bytes(4096))
            self.assertEqual(struct.unpack_from("<Q", after, 8192)[0],
                             (TOP + len(previous)) | 0x1800000000000003)
            self.assertEqual(previous[8200:], after[8200:-4096])

    def test_lowglobal_store_never_allows_other_addresses_or_values(self):
        reference = self.reference()
        previous = reference.expected("vm-protection-returned")
        value = (TOP + len(previous)) | 0x1800000000000003
        start = 0xfffffff007445650
        self.assertTrue(reference.accepts_lowglobal_link(TOP+8192, 8, value, start+0x12c0, start))
        self.assertFalse(reference.accepts_lowglobal_link(TOP+8200, 8, value, start+0x12c0, start))
        self.assertFalse(reference.accepts_lowglobal_link(TOP+8192, 8, value ^ (1 << 59), start+0x12c0, start))
        self.assertFalse(reference.accepts_lowglobal_link(TOP+8192, 8, value, start+0x12c4, start))

    def test_snapshot_outcomes_are_not_switch_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            report = run(self.kernel_path(), Path(directory) / "translations.json")
        self.assertEqual((report["passed"], report["total"]), (36, 36))
        self.assertFalse(report["immediate_switch_safe"])
        self.assertTrue(report["model_only"])
        for geometry in report["cases"].values():
            self.assertFalse(geometry["return-observer"]["available"])
            self.assertTrue(geometry["continuation-code"]["available"])
            self.assertTrue(geometry["live-stack"]["available"])

    def test_walker_rejects_wrong_tcr_and_partial_snapshot(self):
        snapshot = self.reference().expected("vm-lowglobals-cleared")
        with self.assertRaises(ValueError):
            walk(snapshot, VIRTUAL, tcr=0)
        with self.assertRaises(ValueError):
            walk(snapshot[:-1], VIRTUAL)
        self.assertFalse(walk(snapshot, 0x11200000)["mapped"])

    def test_block_permissions_and_physical_offset(self):
        snapshot = self.reference().expected("vm-lowglobals-cleared")
        result = walk(snapshot, VIRTUAL + 0x412345)
        self.assertEqual(result["physical"], PHYSICAL + 0x412345)
        self.assertEqual(result["leaf_level"], 2)
        self.assertTrue(result["executable"])
        self.assertFalse(result["writable"])
        self.assertFalse(result["user_accessible"])

    def test_hierarchical_permissions_are_not_ignored(self):
        snapshot = bytearray(self.reference().expected("vm-lowglobals-cleared"))
        offset = 4096 + 192 * 8
        original = struct.unpack_from("<Q", snapshot, offset)[0]
        struct.pack_into("<Q", snapshot, offset, original | (1 << 59) | (1 << 62))
        self.assertFalse(walk(snapshot, VIRTUAL + 0x412345)["executable"])
        self.assertFalse(walk(snapshot, 0xfffffff007c9b000)["writable"])

    def test_unmapped_lowglobal_page_and_outside_snapshot_table(self):
        snapshot = bytearray(self.reference().expected("vm-lowglobals-cleared"))
        self.assertEqual(walk(snapshot, 0xfffffff000000000)["reason"], "invalid-descriptor")
        struct.pack_into("<Q", snapshot, 8192, 0x124ff003)
        self.assertEqual(walk(snapshot, 0xfffffff000000000)["reason"], "table-outside-snapshot")


if __name__ == "__main__":
    unittest.main()
