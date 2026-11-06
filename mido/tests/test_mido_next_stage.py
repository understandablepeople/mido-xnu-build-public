import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipIf(os.name == "nt", "run native protocol tests in WSL")
class NextStageTests(unittest.TestCase):
    def compile_and_run(self, name, include):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "host"
            subprocess.run([shutil.which("cc"), "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", "-I", str(ROOT / "mido" / include),
                            str(ROOT / "mido/tests" / name), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_bhs_plan_gates_preserves_bits_and_never_accesses_hardware(self):
        self.compile_and_run("gpu_bhs_host.c", "gpu")

    def test_runtime_default_no_writes_gates_and_stops_at_every_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "runtime"
            subprocess.run([shutil.which("c++"), "-std=c++14", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=address,undefined", "-I", str(ROOT / "mido/gpu"),
                            str(ROOT / "mido/tests/gpu_bhs_runtime_host.cpp"), "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_wcnss_fragmentation_exact_boundaries_bitmap_skip_and_failures(self):
        self.compile_and_run("wcnss_control_host.c", "wifi")
