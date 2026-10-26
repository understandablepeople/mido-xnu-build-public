import importlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = Path.home() / "AppData/Local/Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64/bin"


class BootCheckpointMachineCodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (TOOLCHAIN / "clang.exe").is_file():
            raise unittest.SkipTest("local NDK cross-compiler is not installed")
        try:
            cls.unicorn = importlib.import_module("unicorn")
        except ImportError:
            sys.path.insert(0, str(ROOT / "artifacts/python-deps"))
            try:
                cls.unicorn = importlib.import_module("unicorn")
            except ImportError:
                raise unittest.SkipTest("Unicorn is not installed")
        cls.registers = importlib.import_module("unicorn.arm64_const")

    def test_actual_macro_writes_only_two_rectangles_and_preserves_boot_arguments(self):
        macro = (ROOT / "devices/mido/xnu/probe/boot_checkpoints.inc").read_text()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            assembly = directory / "marks.S"
            assembly.write_text(macro + "\n.text\n.global _start\n_start:\n"
                                "MIDO_EARLY_MARK 560\nMIDO_EARLY_MARK 584\nbr x30\n")
            executable = directory / "marks.elf"
            subprocess.run([str(TOOLCHAIN / "clang.exe"), "--target=arm64-apple-darwin",
                            "-march=armv8-a", "-c", str(assembly), "-o", str(directory / "marks.macho.o")],
                           check=True, capture_output=True)
            subprocess.run([str(TOOLCHAIN / "clang.exe"), "--target=aarch64-none-elf",
                            "-march=armv8-a", "-nostdlib", "-fuse-ld=lld", "-Wl,-Ttext=0x100000",
                            "-Wl,-e,_start", str(assembly), "-o", str(executable)], check=True,
                           capture_output=True)
            binary = directory / "marks.bin"
            subprocess.run([str(TOOLCHAIN / "llvm-objcopy.exe"), "-O", "binary", "-j", ".text",
                            str(executable), str(binary)], check=True, capture_output=True)
            instructions = binary.read_bytes()
        engine = self.unicorn.Uc(self.unicorn.UC_ARCH_ARM64, self.unicorn.UC_MODE_ARM)
        engine.mem_map(0x100000, 4096)
        engine.mem_write(0x100000, instructions)
        framebuffer = 0x90001000
        size = (3240 * 1920 + 4095) & ~4095
        initial = bytes([0x23]) * size
        engine.mem_map(framebuffer, size)
        engine.mem_write(framebuffer, initial)
        original = {}
        for index in range(31):
            register = getattr(self.registers, f"UC_ARM64_REG_X{index}")
            value = 0x12340000 + index if index != 30 else 0x110000
            engine.reg_write(register, value)
            original[index] = value
        engine.reg_write(self.registers.UC_ARM64_REG_SP, 0x777000)
        engine.reg_write(self.registers.UC_ARM64_REG_PSTATE, 0x3C5)
        engine.emu_start(0x100000, 0x110000, count=100000)
        self.assertEqual(engine.reg_read(self.registers.UC_ARM64_REG_PC), 0x110000)
        for index, value in original.items():
            if index not in (9, 10, 11, 12):
                self.assertEqual(engine.reg_read(getattr(self.registers, f"UC_ARM64_REG_X{index}")), value)
        self.assertEqual(engine.reg_read(self.registers.UC_ARM64_REG_SP), 0x777000)
        self.assertEqual(engine.reg_read(self.registers.UC_ARM64_REG_PSTATE) & 0x3FF, 0x3C5)
        expected = bytearray(initial)
        for row in (560, 584):
            for vertical in range(row, row + 16):
                offset = vertical * 3240 + 180
                expected[offset:offset + 192] = bytes([255]) * 192
        self.assertEqual(bytes(engine.mem_read(framebuffer, size)), expected)
        self.assertEqual(bytes(engine.mem_read(0x100000, len(instructions))), instructions)


if __name__ == "__main__":
    unittest.main()
