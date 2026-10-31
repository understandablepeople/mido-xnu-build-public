import hashlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from tools.inspect_xnu import inspect
from tools.mido_macho_symbols import macho_symbols
from tools.mido_vm_physmap_carrier_config import template
from tools.mido_vm_physmap_complete_reference import CompletePhysmapReference


ROOT = Path(__file__).resolve().parents[1]
PHYSICAL = 0x11200000
VIRTUAL = 0xfffffff007000000
TOP = 0x12401000
PAGES = 59
WORDS = PAGES * 512
MASK = (1 << 64) - 1
CODE = 0x10080000
RETURN = 0x100ff000
STACK = 0x13200000
INPUT = 0x12a00000
OUTPUT = 0x12b00000
PTOV_FAILURE = 1 << 18
GEOMETRY_FAILURE = 1 << 19
SLIDES = (0, 0x1000, 0x1fe000, 0x1ff000, 0x200000, 0x12345000,
          0x36dff000, 0x36e00000, 0x37bff000, 0x37c00000,
          0x3bdff000, 0x3be00000, 0x3ffff000)
KERNEL_SHA256 = "9b67c800aaf870ab969fab329f0080bdb89eebc0635d199d14a693853e235187"


class PhysmapCompleteCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        dependencies = ROOT / "artifacts/native4k-audit-deps"
        if dependencies.is_dir():
            sys.path.insert(0, str(dependencies))
        try:
            from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
            from unicorn import arm64_const
        except ImportError as error:
            raise unittest.SkipTest(f"Unicorn unavailable: {error}")
        cls.unicorn = (Uc, UC_ARCH_ARM64, UC_MODE_ARM, arm64_const)
        toolchain = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / (
            "Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64/bin")
        for executable in ("clang.exe", "ld.lld.exe", "llvm-objcopy.exe", "llvm-nm.exe"):
            if not (toolchain / executable).is_file():
                raise unittest.SkipTest(f"Pinned NDK tool unavailable: {toolchain / executable}")
        kernel_path = Path(os.environ.get(
            "MIDO_NATIVE4K_KERNEL", str(ROOT / (
                "artifacts/mido-native4k-vm-physmap-batch-v2/baseline-fixture/kernel.macho"))))
        if not kernel_path.is_file():
            raise unittest.SkipTest(f"Pinned kernel unavailable: {kernel_path}")
        kernel = kernel_path.read_bytes()
        if hashlib.sha256(kernel).hexdigest() != KERNEL_SHA256:
            raise AssertionError("Standalone checker tests require the exact pinned kernel")
        symbols = macho_symbols(kernel)
        cls.segments = inspect(kernel)["segments"]
        cls.addresses = {
            "MIDO_VM_PHYSMAP_PA": PHYSICAL + symbols["_physmap_base"] - VIRTUAL,
            "MIDO_VM_STATIC_END_PA": PHYSICAL + symbols["_static_memory_end"] - VIRTUAL,
            "MIDO_VM_MEMORY_SIZE_PA": PHYSICAL + symbols["_mem_size"] - VIRTUAL,
            "MIDO_PHYSMAP_PTOV_PA": PHYSICAL + symbols["_ptov_table"] - VIRTUAL,
            "MIDO_PHYSMAP_INDEX_PA": PHYSICAL + symbols["_ptov_index"] - VIRTUAL,
        }
        if cls.addresses["MIDO_VM_PHYSMAP_PA"] != 0x11362618:
            raise AssertionError("Pinned physmap global PA differs")
        cls.templates = {count: template(kernel, count) for count in (1, 2)}
        cls.temporary = tempfile.TemporaryDirectory(prefix="mido-physmap-check-")
        cls.addClassCleanup(cls.temporary.cleanup)
        directory = Path(cls.temporary.name)
        definitions = dict(cls.addresses, MIDO_PHYSMAP_TOP=TOP,
                           MIDO_PHYSMAP_PHYSICAL=PHYSICAL, MIDO_PHYSMAP_VIRTUAL=VIRTUAL,
                           MIDO_PHYSMAP_TABLE_PAGES=PAGES)
        (directory / "early_entry_config.h").write_text("".join(
            f"#define {name} 0x{value:x}ULL\n" for name, value in definitions.items()),
            encoding="ascii")
        wrapper = directory / "batch.c"
        wrapper.write_text(
            "extern unsigned long long mido_physmap_expected_word(unsigned long long, unsigned long long);\n"
            "unsigned long long mido_test_batch(const unsigned long long *input, "
            "unsigned long long *output, unsigned long long count) {\n"
            "    for (unsigned long long index = 0; index < count; ++index)\n"
            "        output[index] = mido_physmap_expected_word(index, input[index]);\n"
            "    return count;\n}\n", encoding="ascii")
        source = ROOT / "devices/mido/xnu/probe/physmap_complete_check.c"
        objects = []
        for name, path in (("checker", source), ("batch", wrapper)):
            output = directory / f"{name}.o"
            subprocess.run([
                str(toolchain / "clang.exe"), "--target=aarch64-none-elf", "-mcpu=cortex-a53",
                "-mgeneral-regs-only", "-O2", "-ffreestanding", "-fno-builtin",
                "-fno-stack-protector", "-DMIDO_VM_PHYSMAP_COMPLETE=1", "-I", str(directory),
                "-c", str(path), "-o", str(output)], check=True, capture_output=True, text=True)
            objects.append(str(output))
        elf = directory / "check.elf"
        binary = directory / "check.bin"
        subprocess.run([str(toolchain / "ld.lld.exe"), f"-Ttext={CODE:#x}",
                        "-e", "mido_physmap_expected_word", *objects, "-o", str(elf)],
                       check=True, capture_output=True, text=True)
        subprocess.run([str(toolchain / "llvm-objcopy.exe"), "-O", "binary", str(elf),
                        str(binary)], check=True, capture_output=True, text=True)
        cls.payload = binary.read_bytes()
        symbol_output = subprocess.run(
            [str(toolchain / "llvm-nm.exe"), "--defined-only", str(elf)],
            check=True, capture_output=True, text=True).stdout
        cls.functions = {}
        for line in symbol_output.splitlines():
            fields = line.split()
            if len(fields) == 3:
                cls.functions[fields[2]] = int(fields[0], 16)
        for name in ("mido_physmap_expected_word", "mido_physmap_complete_status",
                     "mido_physmap_alias_pairs", "mido_test_batch"):
            if name not in cls.functions:
                raise AssertionError(f"Missing compiled checker symbol: {name}")
        if not 0 < len(cls.payload) < RETURN - CODE:
            raise AssertionError("Standalone payload escaped its separate code mapping")

    def setUp(self):
        emulator, architecture, mode, self.registers = self.unicorn
        self.cpu = emulator(architecture, mode)
        self.cpu.mem_map(PHYSICAL, 0x2000000)
        self.cpu.mem_map(CODE, 0x80000)
        self.cpu.mem_map(STACK, 0x4000)
        self.cpu.mem_write(CODE, self.payload)
        self.install(0)

    def call(self, name, *arguments):
        for index, value in enumerate(arguments):
            self.cpu.reg_write(getattr(self.registers, f"UC_ARM64_REG_X{index}"), value)
        self.cpu.reg_write(self.registers.UC_ARM64_REG_SP, STACK + 0x4000)
        self.cpu.reg_write(self.registers.UC_ARM64_REG_LR, RETURN)
        self.cpu.emu_start(self.functions[name], RETURN, count=30000000)
        self.assertEqual(self.cpu.reg_read(self.registers.UC_ARM64_REG_PC), RETURN,
                         "Standalone function exhausted its instruction budget")
        return self.cpu.reg_read(self.registers.UC_ARM64_REG_X0)

    def put(self, address, value, size=8):
        self.cpu.mem_write(address, value.to_bytes(size, "little"))

    def install(self, slide):
        self.physmap = VIRTUAL + TOP - PHYSICAL + slide
        self.count = (self.physmap + 0x3000000 - VIRTUAL + 0x3fffffff) >> 30
        reference = CompletePhysmapReference(self.segments, VIRTUAL, PHYSICAL, TOP, self.count)
        reference.physmap = self.physmap
        reference.end_kernel = VIRTUAL + 0xf6c000
        self.reference = reference
        self.expected = reference.expected("vm-physmap-before-ttbr")
        self.assertEqual(len(self.expected), PAGES * 4096)
        self.cpu.mem_write(TOP, self.expected)
        for name, value in (("MIDO_VM_PHYSMAP_PA", self.physmap),
                            ("MIDO_VM_STATIC_END_PA", self.physmap + 0x3000000),
                            ("MIDO_VM_MEMORY_SIZE_PA", 0x2000000)):
            self.put(self.addresses[name], value)
        first = reference.first_entry(self.physmap)
        rest = reference.rest_entry()
        self.ptov = struct.pack("<24Q", rest.physical, rest.virtual, rest.length,
                                first.physical, first.virtual, first.length, *([0] * 18))
        self.cpu.mem_write(self.addresses["MIDO_PHYSMAP_PTOV_PA"], self.ptov)
        self.put(self.addresses["MIDO_PHYSMAP_INDEX_PA"], 2, 4)

    def alias_words(self):
        first_link, _, _ = self.reference.first_descriptors()
        _, writes, _ = self.reference.complete_state("__PHYSMAP_REST")
        return {(address - TOP) // 8 for address in
                ({first_link} | {address for address, (_, kind) in writes.items() if kind != "page"})}

    def batch(self, contents):
        self.assertEqual(len(contents), PAGES * 4096)
        self.cpu.mem_write(INPUT, contents)
        self.assertEqual(self.call("mido_test_batch", INPUT, OUTPUT, WORDS), WORDS)
        return bytes(self.cpu.mem_read(OUTPUT, len(contents)))

    def test_pinned_globals_and_templates(self):
        self.assertEqual(self.addresses["MIDO_VM_PHYSMAP_PA"], 0x11362618)
        self.assertEqual(set(self.templates), {1, 2})
        for count, contents in self.templates.items():
            with self.subTest(count=count):
                self.assertEqual(len(contents), PAGES * 4096)

    def test_all_words_match_complete_model_across_slides(self):
        for slide in SLIDES:
            with self.subTest(slide=hex(slide)):
                self.install(slide)
                contents = self.templates[self.count]
                words = struct.unpack(f"<{WORDS}Q", contents)
                expected = struct.unpack(f"<{WORDS}Q", self.expected)
                changed = {index for index, (before, after) in enumerate(zip(words, expected))
                           if before != after}
                self.assertEqual(changed, self.alias_words())
                self.assertEqual(len(changed), 8)
                self.assertTrue(all(words[index] == 0 for index in changed))
                actual = self.batch(contents)
                if actual != self.expected:
                    index = next(index for index in range(WORDS)
                                 if actual[index * 8:index * 8 + 8] != self.expected[index * 8:index * 8 + 8])
                    self.fail(f"slide={slide:#x}, count={self.count}, word={index}: "
                              f"observed={struct.unpack_from('<Q', actual, index * 8)[0]:#x}, "
                              f"expected={expected[index]:#x}")

    def test_complete_status_accepts_model_metadata_across_slides(self):
        for slide in SLIDES:
            with self.subTest(slide=hex(slide)):
                self.install(slide)
                self.assertEqual(self.call("mido_physmap_complete_status"), 0)

    def test_alias_pairs_match_overrides_and_slow_helper(self):
        buffer = OUTPUT + 0x40010
        sentinel = bytes(range(160))
        for slide in SLIDES:
            with self.subTest(slide=hex(slide)):
                self.install(slide)
                self.cpu.mem_write(buffer - 16, sentinel)
                self.assertEqual(self.call("mido_physmap_alias_pairs", buffer), 0)
                output = bytes(self.cpu.mem_read(buffer - 16, len(sentinel)))
                self.assertEqual(output[:16], sentinel[:16])
                self.assertEqual(output[144:], sentinel[144:])
                words = struct.unpack("<16Q", output[16:144])
                pairs = dict(zip(words[::2], words[1::2]))
                self.assertEqual(len(pairs), 8)
                self.assertEqual(set(pairs), self.alias_words())
                self.assertTrue(all(index < WORDS for index in pairs))
                self.assertEqual(words[1::2], (0x12439003, 0x1243b003, *(
                    (0x12600000 + index * 0x200000) | 0x0060000000000601
                    for index in range(6))))
                contents = bytearray(self.templates[self.count])
                for index, value in pairs.items():
                    self.assertEqual(value, struct.unpack_from("<Q", self.expected, index * 8)[0])
                    self.assertEqual(self.call("mido_physmap_expected_word", index, MASK), value)
                    struct.pack_into("<Q", contents, index * 8, value)
                self.assertEqual(bytes(contents), self.expected)
                self.assertEqual(bytes(contents), self.batch(self.templates[self.count]))

    def test_invalid_geometry_alias_pairs_never_write_output(self):
        from unicorn import UC_HOOK_MEM_WRITE

        buffer = OUTPUT + 0x40010
        sentinel = bytes(range(160))
        mutations = (
            ("MIDO_VM_PHYSMAP_PA", MASK),
            ("MIDO_VM_PHYSMAP_PA", VIRTUAL + TOP - PHYSICAL + 1),
            ("MIDO_VM_PHYSMAP_PA", VIRTUAL + TOP - PHYSICAL - 4096),
            ("MIDO_VM_PHYSMAP_PA", VIRTUAL + TOP - PHYSICAL + 0x40000000),
            ("MIDO_VM_PHYSMAP_PA", 0xfffffffc00000000),
            ("MIDO_VM_STATIC_END_PA", MASK),
            ("MIDO_VM_STATIC_END_PA", 0),
            ("MIDO_VM_MEMORY_SIZE_PA", MASK),
            ("MIDO_VM_MEMORY_SIZE_PA", 0),
            ("MIDO_VM_MEMORY_SIZE_PA", 0x2001000),
        )
        for name, value in mutations:
            with self.subTest(global_name=name, value=hex(value)):
                self.install(0)
                self.put(self.addresses[name], value)
                self.cpu.mem_write(buffer - 16, sentinel)
                writes = []

                def record_write(engine, access, address, size, observed, context):
                    if not STACK <= address < address + size <= STACK + 0x4000:
                        writes.append((address, size))

                hook = self.cpu.hook_add(UC_HOOK_MEM_WRITE, record_write)
                try:
                    self.assertEqual(self.call("mido_physmap_alias_pairs", buffer), GEOMETRY_FAILURE)
                    self.assertEqual(self.call("mido_physmap_alias_pairs", 0), GEOMETRY_FAILURE)
                finally:
                    self.cpu.hook_del(hook)
                self.assertEqual(writes, [])
                self.assertEqual(bytes(self.cpu.mem_read(buffer - 16, len(sentinel))), sentinel)

    def test_alias_pairs_ignore_tables_ptov_and_index(self):
        buffer = OUTPUT + 0x40010
        for slide in (0, 0x37c00000, 0x3ffff000):
            with self.subTest(slide=hex(slide)):
                self.install(slide)
                self.assertEqual(self.call("mido_physmap_alias_pairs", buffer), 0)
                expected = bytes(self.cpu.mem_read(buffer, 128))
                self.cpu.mem_write(TOP, b"\xff" * (PAGES * 4096))
                self.cpu.mem_write(self.addresses["MIDO_PHYSMAP_PTOV_PA"], b"\xff" * 192)
                self.put(self.addresses["MIDO_PHYSMAP_INDEX_PA"], 0xffffffff, 4)
                self.cpu.mem_write(buffer, bytes(128))
                self.assertEqual(self.call("mido_physmap_alias_pairs", buffer), 0)
                self.assertEqual(bytes(self.cpu.mem_read(buffer, 128)), expected)

    def test_each_ptov_field_is_checked_including_zero_suffix(self):
        address = self.addresses["MIDO_PHYSMAP_PTOV_PA"]
        for slide in (0, 0x3ffff000):
            self.install(slide)
            for index in range(24):
                for corruption in (MASK, struct.unpack_from("<Q", self.ptov, index * 8)[0] ^ 1):
                    with self.subTest(count=self.count, field=index, corruption=hex(corruption)):
                        self.cpu.mem_write(address, self.ptov)
                        self.put(address + index * 8, corruption)
                        self.assertEqual(self.call("mido_physmap_complete_status"), PTOV_FAILURE)

    def test_wrong_index_is_rejected(self):
        for slide in (0, 0x3ffff000):
            self.install(slide)
            for value in (0, 1, 3, 8, 0xffffffff):
                with self.subTest(count=self.count, index=value):
                    self.put(self.addresses["MIDO_PHYSMAP_INDEX_PA"], value, 4)
                    self.assertEqual(self.call("mido_physmap_complete_status"), PTOV_FAILURE)

    def test_invalid_geometry_is_fail_closed(self):
        mutations = (
            ("MIDO_VM_PHYSMAP_PA", MASK),
            ("MIDO_VM_PHYSMAP_PA", self.physmap + 1),
            ("MIDO_VM_PHYSMAP_PA", VIRTUAL + TOP - PHYSICAL - 4096),
            ("MIDO_VM_PHYSMAP_PA", VIRTUAL + TOP - PHYSICAL + 0x40000000),
            ("MIDO_VM_STATIC_END_PA", MASK),
            ("MIDO_VM_STATIC_END_PA", self.physmap + 0x3001000),
            ("MIDO_VM_MEMORY_SIZE_PA", MASK),
            ("MIDO_VM_MEMORY_SIZE_PA", 0),
            ("MIDO_VM_MEMORY_SIZE_PA", 0x2001000),
        )
        for name, value in mutations:
            with self.subTest(global_name=name, value=hex(value)):
                self.install(0)
                self.put(self.addresses[name], value)
                self.assertEqual(self.call("mido_physmap_complete_status"), GEOMETRY_FAILURE)
                for index in sorted(self.alias_words()):
                    self.assertEqual(self.call("mido_physmap_expected_word", index, MASK), MASK)

    def test_out_of_range_indices_preserve_template_word(self):
        for index in (WORDS, WORDS + 1, MASK):
            for value in (0, MASK, 0x123456789abcdef0):
                with self.subTest(index=index, value=value):
                    self.assertEqual(self.call("mido_physmap_expected_word", index, value), value)

    def test_all_ones_template_only_changes_eight_aliases(self):
        for slide in (0, 0x3ffff000):
            with self.subTest(slide=hex(slide)):
                self.install(slide)
                expected = struct.unpack(f"<{WORDS}Q", self.expected)
                actual = struct.unpack(f"<{WORDS}Q", self.batch(b"\xff" * (PAGES * 4096)))
                aliases = self.alias_words()
                self.assertEqual({index for index, word in enumerate(actual) if word != MASK}, aliases)
                for index in aliases:
                    self.assertEqual(actual[index], expected[index])

    def test_table_and_overlapping_alias_corruption_cannot_supply_expectations(self):
        for slide in (0, 0x3ffff000):
            with self.subTest(slide=hex(slide)):
                self.install(slide)
                contents = self.templates[self.count]
                self.assertEqual(self.batch(contents), self.expected)
                self.cpu.mem_write(TOP, b"\xff" * (PAGES * 4096))
                self.assertEqual(self.batch(contents), self.expected)
                self.assertEqual(self.call("mido_physmap_complete_status"), 0)
                for index in self.alias_words():
                    self.put(TOP + index * 8, TOP | 3)
                self.assertEqual(self.batch(contents), self.expected)
                self.assertEqual(self.call("mido_physmap_complete_status"), 0)

    def test_overlapping_and_reordered_ptov_aliases_are_rejected(self):
        address = self.addresses["MIDO_PHYSMAP_PTOV_PA"]
        for contents in (self.ptov[:24] + self.ptov[:24] + self.ptov[48:],
                         self.ptov[24:48] + self.ptov[:24] + self.ptov[48:],
                         b"\xff" * 192):
            with self.subTest(contents=contents[:48].hex()):
                self.cpu.mem_write(address, contents)
                self.assertEqual(self.call("mido_physmap_complete_status"), PTOV_FAILURE)


if __name__ == "__main__":
    unittest.main()
