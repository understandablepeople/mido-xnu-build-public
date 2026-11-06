import ctypes
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class Corner(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in
                ("corner", "ldo_mode", "voltage_uv", "vref", "cx_level", "mem_acc_corner")]


class Snapshot(ctypes.Structure):
    _fields_ = [("values", ctypes.c_uint32 * 12)]


class PatchTests(unittest.TestCase):
    def test_platform_patch_replays_and_embeds_canonical_headers(self):
        relative = "iokit/Kernel/arm/MidoPlatformExpert.cpp"
        base = (ROOT / "xnu/patches/0016-mido-device-tree-platform-expert.patch").read_text()
        section = base.split("+++ b/" + relative + "\n", 1)[1].split("\n--- ", 1)[0]
        source = "\n".join(line[1:] for line in section.splitlines() if line.startswith("+")) + "\n"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / relative
            target.parent.mkdir(parents=True)
            target.write_text(source)
            for name in ("0046-mido-iosurface-iomfb.patch", "0059-mido-iphone-identity.patch",
                         "0113-mido-gpu-power-audit.patch"):
                subprocess.run(["git", "apply", "--include=" + relative,
                                "--include=iokit/Kernel/arm/mido_gpu_*.h",
                                str(ROOT / "xnu/patches" / name)],
                               cwd=directory, capture_output=True, check=True)
            self.assertEqual(target.read_text().count("mido_gpu_audit();"), 1)
            for name in ("mido_gpu_power.h", "mido_gpu_audit.h"):
                self.assertEqual((target.parent / name).read_text(),
                                 (ROOT / "mido/gpu" / name).read_text())


@unittest.skipIf(os.name == "nt", "run native GPU tests in WSL")
class PowerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("clang")
        cxx = shutil.which("clang++")
        if not compiler or not cxx:
            raise unittest.SkipTest("native clang toolchain unavailable")
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        tests = ROOT / "mido/tests"
        library = Path(cls.temporary.name) / "gpu.so"
        subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-shared", "-fPIC", str(tests / "gpu_host.c"), "-o", str(library)], check=True)
        cls.native = ctypes.CDLL(str(library))
        cls.native.host_plan.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint,
                                        ctypes.POINTER(Corner)]
        cls.native.host_plan.restype = ctypes.c_int
        cls.native.host_snapshot.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_int,
                                            ctypes.POINTER(Snapshot)]
        cls.native.host_snapshot.restype = ctypes.c_int
        cls.native.host_blockers.argtypes = [ctypes.POINTER(Snapshot)]
        cls.native.host_blockers.restype = ctypes.c_uint32
        cls.native.host_read_count.restype = ctypes.c_uint
        cls.native.host_offset_error.restype = ctypes.c_int
        audit = Path(cls.temporary.name) / "audit.so"
        subprocess.run([cxx, "-std=c++14", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-shared", "-fPIC", str(tests / "gpu_audit_host.cpp"), "-o", str(audit)], check=True)
        cls.audit = ctypes.CDLL(str(audit))
        cls.audit.host_audit.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        cls.audit.host_audit.restype = ctypes.c_uint

    def test_all_five_bit_signed_magnitude_fuses(self):
        for corner, shift in enumerate((42, 37, 32), start=1):
            for fuse in range(32):
                delta = (fuse & 15) * 10000 * (-1 if fuse & 16 else 1)
                voltage = (580000, 650000, 720000)[corner - 1] + delta
                voltage += (35000, 25000, 0)[corner - 1]
                voltage = max((510000, 510000, 600000)[corner - 1], voltage)
                voltage = min((620000, 680000, 750000)[corner - 1], voltage)
                result = Corner()
                self.assertEqual(self.native.host_plan(1 << 11, fuse << shift, corner,
                                                       ctypes.byref(result)), 1)
                self.assertEqual((result.ldo_mode, result.voltage_uv), (1, voltage))
                self.assertEqual(result.vref, (voltage - 375000 + 4999) // 5000)

    def test_fuses_do_not_change_dependency_corner_maps(self):
        generator = random.Random(8953)
        for corner in range(1, 8):
            for unused in range(100):
                result = Corner()
                self.native.host_plan(generator.getrandbits(64), generator.getrandbits(64),
                                      corner, ctypes.byref(result))
                self.assertEqual(result.cx_level, (64, 64, 128, 192, 256, 320, 384)[corner - 1])
                self.assertEqual(result.mem_acc_corner, (1, 1, 1, 2, 2, 2, 2)[corner - 1])

    def test_disabled_fuse_and_higher_corners_use_bhs_without_voltage(self):
        for enabled in (0, 1 << 11):
            for corner in range(1, 8):
                if enabled and corner <= 3:
                    continue
                result = Corner()
                self.assertEqual(self.native.host_plan(enabled, (1 << 64) - 1, corner,
                                                       ctypes.byref(result)), 1)
                self.assertEqual((result.ldo_mode, result.voltage_uv, result.vref), (0, 0, 0))

    def test_invalid_corner_preserves_output(self):
        for corner in (0, 8, (1 << 32) - 1):
            result = Corner(*([0xdeadbeef] * 6))
            before = bytes(result)
            self.assertEqual(self.native.host_plan(0, 0, corner, ctypes.byref(result)), 0)
            self.assertEqual(bytes(result), before)
        self.assertEqual(self.native.host_plan(0, 0, 1, None), 0)

    def test_snapshot_reads_only_whitelisted_gcc_offsets(self):
        values = (ctypes.c_uint32 * 12)(*range(12))
        snapshot = Snapshot()
        self.assertEqual(self.native.host_snapshot(values, -1, ctypes.byref(snapshot)), 1)
        self.assertEqual(list(snapshot.values), list(range(12)))
        self.assertEqual(self.native.host_read_count(), 12)
        self.assertEqual(self.native.host_offset_error(), 0)

    def test_snapshot_stops_at_first_error_without_publishing_partial_state(self):
        values = (ctypes.c_uint32 * 12)(*range(12))
        for failure in range(12):
            snapshot = Snapshot((ctypes.c_uint32 * 12)(*([0xdeadbeef] * 12)))
            before = bytes(snapshot)
            self.assertEqual(self.native.host_snapshot(values, failure, ctypes.byref(snapshot)), 0)
            self.assertEqual(bytes(snapshot), before)
            self.assertEqual(self.native.host_read_count(), failure + 1)

    @staticmethod
    def ready():
        return Snapshot((ctypes.c_uint32 * 12)(0, 0, 0x80000000, 0x80000000,
                                               1, 1, 1, 1, 1, 0, 0, 2))

    def test_coarse_prerequisites_are_checked_independently(self):
        self.assertEqual(self.native.host_blockers(ctypes.byref(self.ready())), 0)
        for index, value, blocker in ((0, 1, 32), (2, 0, 1), (3, 0, 2),
                                      (2, 0x80000001, 1), (3, 0x80000002, 2),
                                      (9, 1, 8), (10, 1 << 31, 8), (11, 0, 16)):
            snapshot = self.ready()
            snapshot.values[index] = value
            self.assertEqual(self.native.host_blockers(ctypes.byref(snapshot)), blocker)
        for index in range(4, 9):
            for stopped in (0, 0x80000001):
                snapshot = self.ready()
                snapshot.values[index] = stopped
                self.assertEqual(self.native.host_blockers(ctypes.byref(snapshot)), 4)

    def test_supply_status_matches_selected_path(self):
        snapshot = self.ready()
        snapshot.values[10] = 1 << 9
        self.assertEqual(self.native.host_blockers(ctypes.byref(snapshot)), 16)
        snapshot.values[11] = 4
        self.assertEqual(self.native.host_blockers(ctypes.byref(snapshot)), 0)
        self.assertEqual(self.native.host_blockers(None), 63)

    def test_boot_argument_defaults_to_zero_hardware_access(self):
        self.assertEqual(self.audit.host_audit(0, 1, 0), 0)
        self.assertEqual(self.audit.host_audit(1, 0, 0), 0)
        for unsupported in (-1, 2, 100):
            self.assertEqual(self.audit.host_audit(1, unsupported, 0), 1)

    def test_opt_in_audit_never_modifies_fake_registers(self):
        self.assertEqual(self.audit.host_audit(1, 1, 1), 101)
        self.assertEqual(self.audit.host_audit(1, 1, 0), 104)

    def test_power_and_snapshot_sanitizers(self):
        executable = Path(self.temporary.name) / "gpu-sanitize"
        compiler = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
        subprocess.run([compiler, "-std=c11", "-O1", "-g",
                        "-Wall", "-Wextra", "-Werror", "-fsanitize=address,undefined",
                        "-fno-omit-frame-pointer", str(ROOT / "mido/tests/gpu_host.c"),
                        str(ROOT / "mido/tests/gpu_sanitize.c"), "-o", str(executable)], check=True)
        subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
