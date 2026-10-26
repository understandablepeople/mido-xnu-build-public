import importlib
import io
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tools.check_xnu_build import check, main
from tools.stage_mido_mapped_checkpoint import stage_mapped_checkpoint, UNITS


ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = Path.home() / "AppData/Local/Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64/bin"
CONTRACT = (1, 0x90001000, 6220800, 1080, 1920, 3240, 24)


class MappedCheckpointStagingTests(unittest.TestCase):
    def populate(self, root):
        source = root / "source"
        (source / "osfmk/kern").mkdir(parents=True)
        (source / "osfmk/conf").mkdir()
        for name in ("files", "Makefile.arm64"):
            (source / "osfmk/conf" / name).write_text("original\n")
        return source

    def test_explicit_per_object_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.populate(Path(temporary))
            report = stage_mapped_checkpoint(source)
            self.assertEqual(len(report["files"]), 5)
            self.assertFalse(report["boot_approved"])
            self.assertFalse(report["hardware_verified"])
            graph = (source / "osfmk/conf/files").read_text()
            flags = (source / "osfmk/conf/Makefile.arm64").read_text()
            for name in UNITS:
                if name.endswith(".c"):
                    self.assertIn(f"mido_framebuffer_{name} optional mido_runtime", graph)
                    self.assertIn(f"mido_framebuffer_{Path(name).stem}.o_CFLAGS_ADD", flags)
            self.assertNotIn("\nCFLAGS +=", flags)
            with self.assertRaisesRegex(ValueError, "replace"):
                stage_mapped_checkpoint(source)

    def test_missing_input_does_not_touch_graph(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.populate(Path(temporary))
            with self.assertRaises(OSError):
                stage_mapped_checkpoint(source, Path(temporary) / "missing")
            self.assertEqual((source / "osfmk/conf/files").read_text(), "original\n")
            self.assertFalse((source / "osfmk/kern/mido_framebuffer").exists())

    def test_duplicate_graph_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = self.populate(Path(temporary))
            (source / "osfmk/conf/Makefile.arm64").write_text("mido_framebuffer_old\n")
            with self.assertRaisesRegex(ValueError, "already configured"):
                stage_mapped_checkpoint(source)
            self.assertEqual((source / "osfmk/conf/files").read_text(), "original\n")

    def test_requires_bootstrap_opt_in(self):
        with self.assertRaisesRegex(ValueError, "explicit bootstrap"):
            check(Path("unused"), "iphoneos", experimental_mapped_checkpoint=True)

    def test_cli_opt_in_is_forwarded_and_default_stays_disabled(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as temporary:
                arguments = ["check", "--output-directory", temporary, "--sdk", "iphoneos"]
                if enabled:
                    arguments.append("--experimental-mapped-checkpoint")
                with patch("tools.check_xnu_build.sys.platform", "darwin"), \
                        patch("sys.argv", arguments), patch("sys.stdout", new_callable=io.StringIO), \
                        patch("tools.check_xnu_build.check", return_value={"pipeline_passed": True}) as invoke:
                    main()
                self.assertEqual(invoke.call_args.args[-1], enabled)


class MappedCheckpointMachineCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (TOOLCHAIN / "clang.exe").is_file():
            raise unittest.SkipTest("NDK compiler not installed")
        sys.path.insert(0, str(ROOT / "artifacts/python-deps"))
        try:
            cls.unicorn = importlib.import_module("unicorn")
        except ImportError:
            raise unittest.SkipTest("Unicorn not installed")
        cls.registers = importlib.import_module("unicorn.arm64_const")
        unit = ROOT / UNITS["mapped_checkpoint.c"]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            common = [str(TOOLCHAIN / "clang.exe"), "-march=armv8-a", "-mgeneral-regs-only",
                      "-ffreestanding", "-fno-stack-protector", "-Wall", "-Wextra", "-Werror", "-O2"]
            subprocess.run(common + ["--target=arm64-apple-ios16.6", "-c", str(unit),
                                     "-o", str(directory / "marker.macho.o")], check=True, capture_output=True)
            executable = directory / "marker.elf"
            subprocess.run(common + ["--target=aarch64-none-elf", "-nostdlib", "-fuse-ld=lld",
                                     "-Wl,-Ttext=0x100000", "-Wl,-e,mido_mapped_checkpoint",
                                     str(unit), "-o", str(executable)], check=True, capture_output=True)
            binary = directory / "marker.bin"
            subprocess.run([str(TOOLCHAIN / "llvm-objcopy.exe"), "-O", "binary", "-j", ".text",
                            str(executable), str(binary)], check=True, capture_output=True)
            cls.code = binary.read_bytes()

    def run_marker(self, contract=CONTRACT, mapped=0x50000000, null_contract=False, null_io=False,
                   null_map=False, null_sync=False):
        engine = self.unicorn.Uc(self.unicorn.UC_ARCH_ARM64, self.unicorn.UC_MODE_ARM)
        registers = self.registers
        engine.mem_map(0x100000, 4096)
        engine.mem_write(0x100000, self.code)
        engine.mem_map(0x200000, 4096)
        engine.mem_map(0x300000, 8192)
        engine.mem_write(0x300000, struct.pack("<7Q", *contract))
        engine.mem_write(0x300100, struct.pack("<2Q", 0 if null_map else 0x200000,
                                            0 if null_sync else 0x200100))
        size = (6220800 + 4095) & ~4095
        initial = bytes([0x23]) * size
        engine.mem_map(0x50000000, size)
        engine.mem_write(0x50000000, initial)
        calls = []

        def callback(machine, address, instruction_size, context):
            if address == 0x200000:
                calls.append(("map", machine.reg_read(registers.UC_ARM64_REG_X0),
                              machine.reg_read(registers.UC_ARM64_REG_X1)))
                machine.reg_write(registers.UC_ARM64_REG_X0, mapped)
            elif address == 0x200100:
                calls.append(("sync",))
            else:
                return
            machine.reg_write(registers.UC_ARM64_REG_PC, machine.reg_read(registers.UC_ARM64_REG_X30))

        engine.hook_add(self.unicorn.UC_HOOK_CODE, callback)
        engine.reg_write(registers.UC_ARM64_REG_X0, 0 if null_contract else 0x300000)
        engine.reg_write(registers.UC_ARM64_REG_X1, 0 if null_io else 0x300100)
        engine.reg_write(registers.UC_ARM64_REG_X30, 0x110000)
        engine.reg_write(registers.UC_ARM64_REG_SP, 0x302000)
        engine.emu_start(0x100000, 0x110000, count=100000)
        self.assertEqual(engine.reg_read(registers.UC_ARM64_REG_PC), 0x110000)
        self.assertEqual(engine.reg_read(registers.UC_ARM64_REG_SP), 0x302000)
        return engine.reg_read(registers.UC_ARM64_REG_W0), calls, bytes(engine.mem_read(0x50000000, size)), initial

    def test_only_expected_virtual_rectangle_is_written(self):
        status, calls, pixels, initial = self.run_marker()
        self.assertEqual(status, 0)
        self.assertEqual(calls, [("map", CONTRACT[1], CONTRACT[2]), ("sync",)])
        expected = bytearray(initial)
        for row in range(608, 624):
            offset = row * 3240 + 180
            expected[offset:offset + 192] = bytes([255]) * 192
        self.assertEqual(pixels, expected)

    def test_every_contract_field_is_checked_before_mapping(self):
        for index in range(len(CONTRACT)):
            with self.subTest(field=index):
                contract = list(CONTRACT)
                contract[index] += 1
                status, calls, pixels, initial = self.run_marker(tuple(contract))
                self.assertEqual(status, 0xffffffff)
                self.assertEqual(calls, [])
                self.assertEqual(pixels, initial)

    def test_bad_mapping_never_writes_or_synchronizes(self):
        for mapped in (0, 0x50000001, 0xfffffffffffffffc):
            with self.subTest(mapped=mapped):
                status, calls, pixels, initial = self.run_marker(mapped=mapped)
                self.assertEqual(status, 0xfffffffe)
                self.assertEqual(calls, [("map", CONTRACT[1], CONTRACT[2])])
                self.assertEqual(pixels, initial)

    def test_null_inputs_and_callbacks_never_map(self):
        for name in ("null_contract", "null_io", "null_map", "null_sync"):
            with self.subTest(null=name):
                status, calls, pixels, initial = self.run_marker(**{name: True})
                self.assertEqual(status, 0xffffffff)
                self.assertEqual(calls, [])
                self.assertEqual(pixels, initial)


if __name__ == "__main__":
    unittest.main()
