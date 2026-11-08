import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from patch_sources import kernel_source

ROOT = Path(__file__).resolve().parents[2]


@unittest.skipIf(os.name == "nt", "run native backend tests in WSL")
class BackendBridgeTests(unittest.TestCase):
    def test_registration_forwarding_absence_loss_and_fence_order(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "backend"
            subprocess.run([shutil.which("c++"), "-std=c++14", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", "-I", str(ROOT / "mido/gpu"),
                            "-I", str(ROOT / "mido/wifi"),
                            str(ROOT / "mido/tests/backend_bridge_host.cpp"), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
            subprocess.run([str(binary), "late-fence"], check=True)


class BridgeSourceTests(unittest.TestCase):
    def test_patch_reconstructs_all_canonical_bridge_sources(self):
        for folder, name in (("gpu", "MidoGPU.cpp"), ("gpu", "sweet_gpu.h"),
                             ("gpu", "mido_gpu_backend.h"), ("gpu", "mido_gpu_backend.cpp"),
                             ("wifi", "MidoWLAN.cpp"), ("wifi", "mido_wlan_backend.h"),
                             ("wifi", "mido_wlan_backend.cpp")):
            self.assertEqual(kernel_source(ROOT, name, "0128-mido-donor-backend-bridges.patch"),
                             (ROOT / "mido" / folder / name).read_text())

    def test_source_lists_and_pinned_dependency_are_present(self):
        patch = (ROOT / "xnu/patches/0128-mido-donor-backend-bridges.patch").read_text()
        for name in ("MidoGPU", "mido_gpu_backend", "MidoWLAN", "mido_wlan_backend"):
            self.assertIn("+iokit/Kernel/arm/" + name + ".cpp optional iokitcpp", patch)
        self.assertEqual(patch.count("+iokit/IOKit/network/"), 12)
        self.assertIn("+MidoWLAN.cpo_CFLAGS_ADD += -D__PRIVATE_SPI__", patch)
        stage = (ROOT / "xnu/patches/0128-stage-ionetworking.sh").read_text()
        self.assertIn("f9f7e57b2132b82de09a26ddcbf56fd8125b4933", stage)
        self.assertIn("refusing to overwrite existing sources", stage)

    def test_frontends_are_opt_in_and_do_not_hold_iokit_busy(self):
        gpu = (ROOT / "mido/gpu/MidoGPU.cpp").read_text()
        wlan = (ROOT / "mido/wifi/MidoWLAN.cpp").read_text()
        self.assertIn('"midogpubridge"', gpu)
        self.assertIn('"midowlan"', wlan)
        self.assertIn("if (!sweet_gpu_ready())", gpu)
        self.assertNotIn("adjustBusy(1)", wlan)
        self.assertIn("mido_wlan_backend_ready()", wlan)
        self.assertIn("kIOReturnOutputDropped", wlan)
        self.assertIn("return gWLAN->interfaceAttached();", wlan)

    def test_gpu_status_requires_backend_before_mapping(self):
        source = (ROOT / "mido/gpu/mido_gpu_status.h").read_text()
        # mode 1 needs the registered backend before any mapping; mode 2 is the explicit recoverable scan.
        self.assertIn("mode != 2 && !sweet_gpu_ready()", source)
        self.assertLess(source.index("mode != 2 && !sweet_gpu_ready()"), source.index("ml_io_map_unmappable("))
        self.assertIn("mido_mmio_read32_nofault(", source)


if __name__ == "__main__":
    unittest.main()
