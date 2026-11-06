import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from patch_sources import kernel_source


ROOT = Path(__file__).resolve().parents[2]


class CxSourceTests(unittest.TestCase):
    def test_wifi_queries_precede_gpu_and_status_is_clock_gated(self):
        source = (ROOT / "mido/input/MidoInput.cpp").read_text()
        gpu_vote = source.index("mido_gpu_cx_vote(&rpm)")
        for request in ("mido_wcnss_audit(&rpm)", "mido_scm_probe()", "mido_wcnss_clocks()"):
            self.assertLess(source.index(request), gpu_vote)
        clocks = source.index("mido_gpu_clocks(gx_result)")
        status = source.index("mido_gpu_status(clocks_result)")
        self.assertLess(clocks, status)
        self.assertLess(status, source.index("IOSleep(50);", status))

    def test_patch_reconstructs_current_driver_and_header(self):
        for name, base, canonical in (
                ("MidoInput.cpp", "0107-mido-polled-input-battery.patch", "input"),
                ("mido_gpu_cx.h", "0115-mido-serialized-gpu-cx-vote.patch", "gpu"),
                ("mido_gpu_bhs.h", "0118-mido-gfx-bhs-preparation.patch", "gpu"),
                ("mido_gpu_bhs_runtime.h", "0118-mido-gfx-bhs-preparation.patch", "gpu"),
                ("mido_gpu_cx_power.h", "0121-mido-cx-domain-and-wcnss-discovery.patch", "gpu"),
                ("mido_wcnss_smem.h", "0121-mido-cx-domain-and-wcnss-discovery.patch", "wifi"),
                ("mido_wcnss_audit.h", "0121-mido-cx-domain-and-wcnss-discovery.patch", "wifi"),
                ("mido_gpu_gx_power.h", "0124-mido-gx-xo-power-and-scm-info.patch", "gpu"),
                ("mido_scm_probe.h", "0124-mido-gx-xo-power-and-scm-info.patch", "wifi"),
                ("mido_gpu_clocks.h", "0125-mido-gpu-branches-and-pas-support.patch", "gpu"),
                ("mido_gpu_status.h", "0125-mido-gpu-branches-and-pas-support.patch", "gpu"),
                ("mido_wcnss_clocks.h", "0125-mido-gpu-branches-and-pas-support.patch", "wifi")):
            self.assertEqual(kernel_source(ROOT, name, base),
                             (ROOT / "mido" / canonical / name).read_text())

    def test_vote_is_opt_in_and_serialized_after_both_touch_rails(self):
        source = (ROOT / "mido/input/MidoInput.cpp").read_text()
        rails = source.index("for (unsigned index = 0; index < 2; index++)")
        gate = source.index("if (gpu_cx == 1 && ok)")
        vote = source.index("mido_gpu_cx_vote(&rpm)")
        self.assertLess(rails, gate)
        self.assertLess(gate, vote)
        self.assertIn("unsigned gpu_cx = 0;", source)
        self.assertEqual(source.count("struct mido_rpm_io rpm = {};"), 1)
        self.assertEqual(source.count("mido_gpu_cx_vote("), 1)
        self.assertLess(vote, source.index("IOSleep(50);", vote))


@unittest.skipIf(os.name == "nt", "run native CX tests in WSL")
class CxNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        library = Path(cls.temporary.name) / "cx.so"
        compiler = shutil.which("cc") or shutil.which("clang")
        subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                        "-shared", "-fPIC", "-I", str(ROOT / "mido/input"),
                        "-I", str(ROOT / "mido/gpu"),
                        str(ROOT / "mido/tests/gpu_cx_host.c"), "-o", str(library)], check=True)
        cls.native = ctypes.CDLL(str(library))
        cls.native.host_vote.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint32)]
        cls.native.host_vote.restype = ctypes.c_int

    def test_exact_smpa2_level_vote_not_microvolts(self):
        output = (ctypes.c_uint32 * 11)()
        self.assertEqual(self.native.host_vote(0, output), 0)
        self.assertEqual(list(output), [0x61706d73, 2, 6, 0x475001,
                                       0x6e657773, 4, 1, 0x6c766c76, 4, 192, 1])

    def test_propagates_transport_failures_without_retry(self):
        for failure in range(-9, 0):
            output = (ctypes.c_uint32 * 11)()
            self.assertEqual(self.native.host_vote(failure, output), failure)
            self.assertEqual(output[10], 1)
