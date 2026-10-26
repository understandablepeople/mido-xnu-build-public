import hashlib
import ast
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
from tools.stage_mido_platform_expert import PERSONALITY, stage_platform_expert


ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = Path.home() / "AppData/Local/Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64/bin"
IDENTITY = b"mido,synthetic-abi-only\0"
CONTRACT = (1, 1, 0, 19200000, 20, 0x0b000000, 0x0b002000)


class PlatformExpertStagingTests(unittest.TestCase):
    def test_cpu_completion_is_published_only_after_successful_platform_start(self):
        source = (ROOT / "devices/mido/xnu/runtime/MidoDiagnosticPlatform.cpp").read_text()
        start = source.split("bool MidoDiagnosticPlatform::start(IOService *provider)", 1)[1]
        start = start.split("long MidoDiagnosticPlatform::getGMTTimeOfDay", 1)[0]
        self.assertIn("if (!diagnostic_contract_matches(provider))\n        return false;", start)
        self.assertIn("if (!IOPlatformExpert::start(provider))\n        return false;\n"
                      "    ml_set_max_cpus(1);\n    return true;", start)
        self.assertEqual(source.count("ml_set_max_cpus("), 1)

    def populate(self, root):
        source = root / "source"
        (source / "iokit/Kernel").mkdir(parents=True)
        (source / "iokit/conf").mkdir()
        for name in ("files", "Makefile.arm64"):
            (source / "iokit/conf" / name).write_text("original\n")
        (source / "config").mkdir()
        (source / "config/MASTER.arm64.MIDO").write_text("pseudo-device mido_runtime\n")
        before = b'const char *gIOKernelConfigTables =\n    "("\n    "{ IOClass = IOPanicPlatform; }"\n    ")";\n'
        (source / "iokit/KernelConfigTables.cpp").write_bytes(before)
        return source, before

    def stage(self, source, before):
        with patch("tools.stage_mido_platform_expert.CATALOG_SHA256", hashlib.sha256(before).hexdigest()):
            return stage_platform_expert(source)

    def test_personality_is_additive_and_cpp_object_flag_is_correct(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, before = self.populate(Path(temporary))
            report = self.stage(source, before)
            after = (source / "iokit/KernelConfigTables.cpp").read_bytes()
            self.assertEqual(after.replace(PERSONALITY, b""), before)
            self.assertEqual(after.count(b"IOPanicPlatform"), 1)
            self.assertIn(b"'IONameMatch'     = 'mido,synthetic-abi-only'", after)
            self.assertIn(b"1000:32", after)
            serialized = "".join(ast.literal_eval(line.strip().removesuffix(";"))
                                 for line in after.decode().splitlines() if line.strip().startswith('"'))
            self.assertRegex(serialized, r"1000:32;\s*},\s*\{ IOClass = IOPanicPlatform;")
            self.assertNotRegex(serialized, r"}\s*\{")
            flags = (source / "iokit/conf/Makefile.arm64").read_text()
            self.assertIn("MidoDiagnosticPlatform.cpo_CFLAGS_ADD += -DMIDO_DIAGNOSTIC_PLATFORM=1", flags)
            self.assertNotIn("\nCFLAGS +=", flags)
            self.assertIn("MidoDiagnosticPlatform.cpp optional mido_runtime",
                          (source / "iokit/conf/files").read_text())
            self.assertEqual(len(report["files"]), 9)
            self.assertIn("mido_pmic_clock.o_CFLAGS_ADD += -DMIDO_DIAGNOSTIC_PLATFORM=1", flags)
            clock_flags = next(line for line in flags.splitlines() if line.startswith("mido_pmic_clock.o_"))
            self.assertIn("-DPEXPERT_KERNEL_PRIVATE=1", clock_flags)
            self.assertNotIn("PEXPERT_KERNEL_PRIVATE", next(line for line in flags.splitlines() if line.startswith("pmic_rtc.o_")))
            self.assertIn("pmic_rtc.c optional mido_runtime", (source / "iokit/conf/files").read_text())
            self.assertFalse(report["rtc_resource_published"])
            self.assertFalse(report["boot_approved"])
            with self.assertRaisesRegex(ValueError, "replace"):
                self.stage(source, before)

    def test_hash_mismatch_leaves_graph_and_target_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, before = self.populate(Path(temporary))
            with self.assertRaisesRegex(ValueError, "catalogue"):
                stage_platform_expert(source)
            self.assertEqual((source / "iokit/conf/files").read_text(), "original\n")
            self.assertEqual((source / "iokit/KernelConfigTables.cpp").read_bytes(), before)
            self.assertFalse((source / "iokit/Kernel/mido_platform").exists())

    def test_duplicate_graph_and_wrong_platform_rejected(self):
        for name, content, message in (("iokit/conf/files", "MidoDiagnosticPlatform\n", "already configured"),
                                       ("config/MASTER.arm64.MIDO", "pseudo-device mido_runtime_extra\n", "MIDO runtime")):
            with self.subTest(path=name), tempfile.TemporaryDirectory() as temporary:
                source, before = self.populate(Path(temporary))
                (source / name).write_text(content)
                with self.assertRaisesRegex(ValueError, message):
                    self.stage(source, before)
                self.assertFalse((source / "iokit/Kernel/mido_platform").exists())
                self.assertEqual((source / "iokit/KernelConfigTables.cpp").read_bytes(), before)

    def test_requires_all_diagnostic_dependencies(self):
        for crypto, irq, nonapple in ((False, False, False), (True, False, True), (True, True, False)):
            with self.subTest(crypto=crypto, irq=irq, nonapple=nonapple), self.assertRaisesRegex(ValueError, "diagnostic platform requires"):
                check(Path("unused"), "iphoneos", attempt_kernel=True, experimental_boot_crypto=crypto,
                      experimental_irq_timer=irq, mido_no_image4_boot=nonapple, experimental_platform_expert=True)

    def test_cli_opt_in_defaults_off(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as temporary:
                arguments = ["check", "--output-directory", temporary, "--sdk", "iphoneos"]
                if enabled:
                    arguments.append("--experimental-platform-expert")
                with patch("tools.check_xnu_build.sys.platform", "darwin"), patch("sys.argv", arguments), \
                        patch("sys.stdout", new_callable=io.StringIO), \
                        patch("tools.check_xnu_build.check", return_value={"pipeline_passed": True}) as invoke:
                    main()
                self.assertEqual(invoke.call_args.kwargs["experimental_platform_expert"], enabled)


class PlatformContractMachineCodeTests(unittest.TestCase):
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
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            wrapper = directory / "contract.c"
            wrapper.write_text('#include "platform_contract.h"\n'
                               'int platform_check(const void *identity, __SIZE_TYPE__ identity_size, '
                               'const void *property, __SIZE_TYPE__ property_size, unsigned int cpus, '
                               'int boot_cpu, __UINT64_TYPE__ frequency) { return '
                               'mido_platform_contract_matches(identity, identity_size, property, property_size, '
                               'cpus, boot_cpu, frequency); }\n')
            common = [str(TOOLCHAIN / "clang.exe"), "-march=armv8-a", "-mgeneral-regs-only", "-ffreestanding",
                      "-fno-stack-protector", "-Wall", "-Wextra", "-Werror", "-O2", "-I",
                      str(ROOT / "devices/mido/xnu/early")]
            for language in ("c", "c++"):
                subprocess.run(common + ["--target=arm64-apple-ios16.6", "-x", language, "-c", str(wrapper),
                                         "-o", str(directory / (language + ".o"))], check=True, capture_output=True)
            script = directory / "link.ld"
            script.write_text("ENTRY(platform_check)\nSECTIONS { . = 0x100000; .text : { *(.text*) *(.rodata*) } }\n")
            executable = directory / "contract.elf"
            subprocess.run(common + ["--target=aarch64-none-elf", "-nostdlib", "-fuse-ld=lld",
                                     "-Wl,-T," + str(script), str(wrapper), "-o", str(executable)],
                           check=True, capture_output=True)
            binary = directory / "contract.bin"
            subprocess.run([str(TOOLCHAIN / "llvm-objcopy.exe"), "-O", "binary", "-j", ".text",
                            str(executable), str(binary)], check=True, capture_output=True)
            cls.code = binary.read_bytes()

    def execute_contract(self, identity=IDENTITY, contract=CONTRACT, cpus=1, boot_cpu=0, frequency=19200000,
                         property_size=56, identity_size=None, null_property=False, null_identity=False):
        engine = self.unicorn.Uc(self.unicorn.UC_ARCH_ARM64, self.unicorn.UC_MODE_ARM)
        registers = self.registers
        engine.mem_map(0x100000, 4096)
        engine.mem_write(0x100000, self.code)
        engine.mem_map(0x300000, 8192)
        engine.mem_write(0x300000, identity)
        engine.mem_write(0x300101, struct.pack("<7Q", *contract))
        arguments = [0 if null_identity else 0x300000, len(identity) if identity_size is None else identity_size,
                     0 if null_property else 0x300101, property_size, cpus, boot_cpu & ((1 << 64) - 1), frequency]
        for index, value in enumerate(arguments):
            engine.reg_write(getattr(registers, f"UC_ARM64_REG_X{index}"), value)
        engine.reg_write(registers.UC_ARM64_REG_X30, 0x110000)
        engine.reg_write(registers.UC_ARM64_REG_SP, 0x302000)
        engine.emu_start(0x100000, 0x110000, count=10000)
        self.assertEqual(engine.reg_read(registers.UC_ARM64_REG_PC), 0x110000)
        self.assertEqual(engine.reg_read(registers.UC_ARM64_REG_SP), 0x302000)
        return engine.reg_read(registers.UC_ARM64_REG_W0)

    def test_exact_contract_and_unaligned_property_accepted(self):
        self.assertEqual(self.execute_contract(), 1)

    def test_real_phone_unknown_board_and_bad_string_rejected(self):
        for identity in (b"xiaomi,mido\0", b"AppleARMPE\0", IDENTITY[:-1], IDENTITY + b"extra", b"\0" * len(IDENTITY)):
            with self.subTest(identity=identity):
                self.assertEqual(self.execute_contract(identity=identity), 0)

    def test_every_contract_field_checked(self):
        for index in range(len(CONTRACT)):
            contract = list(CONTRACT)
            contract[index] += 1
            with self.subTest(field=index):
                self.assertEqual(self.execute_contract(contract=tuple(contract)), 0)

    def test_runtime_cpu_and_frequency_must_match(self):
        for options in ({"cpus": 0}, {"cpus": 2}, {"boot_cpu": 1}, {"boot_cpu": -1}, {"frequency": 0},
                        {"frequency": 24000000}):
            with self.subTest(options=options):
                self.assertEqual(self.execute_contract(**options), 0)

    def test_null_and_incorrect_lengths_rejected(self):
        for options in ({"null_property": True}, {"null_identity": True}, {"property_size": 0},
                        {"property_size": 55}, {"property_size": 57}, {"identity_size": 0}):
            with self.subTest(options=options):
                self.assertEqual(self.execute_contract(**options), 0)


if __name__ == "__main__":
    unittest.main()
