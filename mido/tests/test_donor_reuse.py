import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "donor_reuse", ROOT / "tools/mido_prepare_donors.py")
DONOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DONOR)


class DonorReuseTests(unittest.TestCase):
    def test_wifi_adapter_keeps_apple_interface_and_changes_backend(self):
        original = ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n"
                    "SailfishWLAN; sailfish_wlan_output; sailfishwlan;\n"
                    "IO80211Interface; SIOCSA80211;\n")
        adapted = DONOR.adapt_wifi_frontend(original)
        self.assertIn("MidoWLAN; mido_wlan_output; midowlan;", adapted)
        self.assertIn("IO80211Interface; SIOCSA80211;", adapted)
        self.assertNotIn("ARM64_BOARD_CONFIG_SWEET", adapted)

    def test_wifi_adapter_rejects_unexpected_source(self):
        with self.assertRaisesRegex(ValueError, "donor WLAN frontend changed"):
            DONOR.adapt_wifi_frontend("different source")

    def test_gpu_adapter_preserves_userspace_abi(self):
        original = ("#if defined(ARM64_BOARD_CONFIG_SWEET)\n"
                    "#include \"SweetSurface.h\"\n"
                    "SweetSurface *surface = sweet_surface_copy(id);\n"
                    "SweetGPU; sweet_gpu_submit; case 15:;\n")
        adapted = DONOR.adapt_gpu_frontend(original)
        self.assertIn("#if defined(MIDO)", adapted)
        self.assertIn("MidoSurface *surface = mido_surface_copy(id);", adapted)
        self.assertIn("SweetGPU; sweet_gpu_submit; case 15:;", adapted)
        self.assertNotIn("SweetSurface", adapted)

    def test_gpu_adapter_rejects_unexpected_source(self):
        with self.assertRaisesRegex(ValueError, "donor frontend changed"):
            DONOR.adapt_gpu_frontend("different source")

    def test_unselected_patch_is_not_applied(self):
        with tempfile.TemporaryDirectory() as directory:
            result = DONOR.apply_selected(
                directory, b"invalid patch, unrelated paths", ("bsd/dev/gpu.c",))
            self.assertFalse(result)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_selected_file_only_and_followup(self):
        first = (b"--- /dev/null\n+++ b/bsd/dev/gpu.c\n@@ -0,0 +1 @@\n+original\n"
                 b"--- /dev/null\n+++ b/private.txt\n@@ -0,0 +1 @@\n+excluded\n")
        later = (b"--- a/bsd/dev/gpu.c\n+++ b/bsd/dev/gpu.c\n"
                 b"@@ -1 +1 @@\n-original\n+final\n")
        with tempfile.TemporaryDirectory() as directory:
            self.assertTrue(DONOR.apply_selected(directory, first, ("bsd/dev/gpu.c",)))
            self.assertTrue(DONOR.apply_selected(directory, later, ("bsd/dev/gpu.c",)))
            self.assertEqual((Path(directory) / "bsd/dev/gpu.c").read_text(), "final\n")
            self.assertFalse((Path(directory) / "private.txt").exists())

    def test_existing_output_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "keep.txt"
            marker.write_text("keep")
            with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
                DONOR.prepare(ROOT / "not-used", Path(directory))
            self.assertEqual(marker.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
