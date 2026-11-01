"""Actual island bytes, without hardware translation or coherency proof.

Integration contract: enter mido_ttbr1_return from patched arm_vm_init+0x13e8,
with the whole island mapped executable under BOTH old and new TTBR1.
The integration owner must independently verify final RX instruction fetch,
bootstrap low-identity record mapping, and the existing setters' mappings.
No permissions or page tables are modified here. Unicorn uses flat mappings;
these tests do not establish CPU-TLB translation or physical cache coherency.

Record at 0x12400900 (nine little-endian uint64s): magic 'T1RET001',
incoming TTBR1, TTBR0, TCR, SCTLR, DAIF, SP, VBAR, restored TTBR1.
Scratch x9..x17 and NZCV are clobbered; all other GPRs, SP, DAIF preserved.
"""

import importlib
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

from tools.mido_elf import symbols_from_elf


ROOT = Path(__file__).resolve().parents[1]
TOOLCHAIN = Path.home() / "AppData/Local/Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64/bin"
SOURCE = ROOT / "devices/mido/xnu/probe/ttbr1_return.S"
LINK_ADDRESS = 0x100000
OBSERVER = 0xfffffff008200000
RECORD = 0x12400900
MAGIC = 0x3130305445523154
TTBR0 = (3, 0, 2, 0, 0)
TTBR1 = (3, 0, 2, 0, 1)
TCR = (3, 0, 2, 0, 2)
SCTLR = (3, 0, 1, 0, 0)
VBAR = (3, 0, 12, 0, 0)
DSB = 0xd5033f9f
ISB = 0xd5033fdf
TLBI = 0xd508871f
WFE = 0xd503205f


class TTBR1ReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not (TOOLCHAIN / "clang.exe").is_file():
            raise unittest.SkipTest("Pinned NDK 28.2.13676358 unavailable")
        try:
            cls.unicorn = importlib.import_module("unicorn")
        except ImportError:
            sys.path.insert(0, str(ROOT / "artifacts/python-deps"))
            try:
                cls.unicorn = importlib.import_module("unicorn")
            except ImportError:
                raise unittest.SkipTest("Unicorn unavailable")
        cls.registers = importlib.import_module("unicorn.arm64_const")
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            executable = directory / "island.elf"
            subprocess.run([str(TOOLCHAIN / "clang.exe"), "--target=aarch64-none-elf",
                            "-mcpu=cortex-a53", "-nostdlib", "-fuse-ld=lld",
                            f"-Wl,-Ttext={LINK_ADDRESS:#x}", "-Wl,-e,mido_ttbr1_return",
                            str(SOURCE), "-o", str(executable)], check=True, capture_output=True)
            binary = directory / "island.bin"
            subprocess.run([str(TOOLCHAIN / "llvm-objcopy.exe"), "-O", "binary", "-j", ".text",
                            str(executable), str(binary)], check=True, capture_output=True)
            cls.code = binary.read_bytes()
            cls.symbols = symbols_from_elf(executable.read_bytes(), ("mido_ttbr1_return",))
            cls.relocations = subprocess.run([str(TOOLCHAIN / "llvm-readelf.exe"), "-r",
                                              str(executable)], check=True, capture_output=True,
                                             text=True).stdout

    def offset(self, suffix):
        return self.symbols["mido_ttbr1_return" + suffix] - LINK_ADDRESS

    def execute(self, base=0xfffffff007800000, ttbr0=0x11352000,
                ttbr1=0x12402000, daif=0x3c0, tcr=0x22a51a251a):
        engine = self.unicorn.Uc(self.unicorn.UC_ARCH_ARM64, self.unicorn.UC_MODE_ARM)
        registers = self.registers
        engine.ctl_set_cpu_model(registers.UC_CPU_ARM64_A53)
        engine.ctl_set_tlb_mode(self.unicorn.UC_TLB_VIRTUAL)
        engine.mem_map(base & ~4095, 4096, self.unicorn.UC_PROT_READ | self.unicorn.UC_PROT_EXEC)
        engine.mem_write(base, self.code)
        engine.mem_map(OBSERVER, 4096, self.unicorn.UC_PROT_READ | self.unicorn.UC_PROT_EXEC)
        engine.mem_map(RECORD & ~4095, 4096)
        sentinel = bytes([0xa5]) * 4096
        engine.mem_write(RECORD & ~4095, sentinel)
        original = {}
        for index in range(31):
            value = 0xaabb0000 + index
            original[index] = value
            engine.reg_write(getattr(registers, f"UC_ARM64_REG_X{index}"), value)
        stack = 0xfffffff007c9bff0
        engine.reg_write(registers.UC_ARM64_REG_SP, stack)
        engine.reg_write(registers.UC_ARM64_REG_PSTATE, daif | 5)
        for identity, value in ((TTBR0, ttbr0), (TTBR1, ttbr1), (TCR, tcr),
                                (SCTLR, 0x34d4593d), (VBAR, 0xfffffff00722c000)):
            engine.cpr_write(*identity, value)
        events, stores, writes, pcs, sps = [], [], [], [], []
        outcome = []

        def visit(machine, address, size, context):
            pcs.append(address)
            sps.append(machine.reg_read(registers.UC_ARM64_REG_SP))
            if address == OBSERVER:
                self.assertEqual(machine.cpr_read(*TTBR1), 0x11353000)
                outcome.append("observer")
                machine.emu_stop()
                return
            self.assertTrue(base <= address < base + len(self.code))
            word = struct.unpack_from("<I", self.code, address - base)[0]
            if word in (DSB, ISB, TLBI, WFE):
                events.append(("instruction", word))
            if word == WFE:
                outcome.append("reject")
                machine.emu_stop()

        def store(machine, access, address, size, value, context):
            self.assertTrue(RECORD <= address < address + size <= RECORD + 72)
            stores.append((address, size, value))
            events.append(("store", address))

        def system_write(machine, register, encoding, context):
            identity = (encoding.op0, encoding.op1, encoding.crn, encoding.crm, encoding.op2)
            value = machine.reg_read(register)
            writes.append((identity, value))
            events.append(("msr", identity, value))
            return False

        engine.hook_add(self.unicorn.UC_HOOK_CODE, visit)
        engine.hook_add(self.unicorn.UC_HOOK_MEM_WRITE, store)
        engine.hook_add(self.unicorn.UC_HOOK_INSN, system_write,
                        aux1=registers.UC_ARM64_INS_MSR)
        engine.emu_start(base, 0, count=200)
        self.assertEqual(len(outcome), 1, "Island failed to terminate within instruction bound")
        self.assertTrue(all(value == stack for value in sps))
        self.assertEqual(engine.reg_read(registers.UC_ARM64_REG_SP), stack)
        for index, value in original.items():
            if index not in range(9, 18):
                self.assertEqual(engine.reg_read(getattr(registers, f"UC_ARM64_REG_X{index}")), value)
        self.assertEqual(engine.cpr_read(*TTBR0), ttbr0)
        self.assertEqual(engine.cpr_read(*TCR), tcr)
        self.assertEqual(engine.cpr_read(*SCTLR), 0x34d4593d)
        self.assertEqual(engine.cpr_read(*VBAR), 0xfffffff00722c000)
        self.assertEqual(engine.reg_read(registers.UC_ARM64_REG_PSTATE) & 0x3c0, daif)
        memory = bytes(engine.mem_read(RECORD & ~4095, 4096))
        return dict(engine=engine, outcome=outcome[0], events=events, stores=stores,
                    writes=writes, memory=memory, sentinel=sentinel, pcs=pcs)

    def test_size_labels_and_no_link_time_relocations(self):
        self.assertLessEqual(len(self.code), 256)
        self.assertEqual(self.offset("_end"), len(self.code))
        self.assertEqual(self.symbols["mido_ttbr1_return_record"], RECORD)
        self.assertEqual(self.symbols["mido_ttbr1_return_magic"], MAGIC)
        self.assertIn("There are no relocations", self.relocations)
        self.assertEqual(struct.unpack_from("<2I", self.code, self.offset("_reject")),
                         (WFE, 0x17ffffff))

    def test_capture_restore_order_and_absolute_old_observer(self):
        result = self.execute()
        self.assertEqual(result["outcome"], "observer")
        self.assertEqual(result["writes"], [(TTBR1, 0x11353000)])
        record = struct.unpack_from("<9Q", result["memory"], RECORD & 4095)
        self.assertEqual(record, (MAGIC, 0x12402000, 0x11352000, 0x22a51a251a,
                                  0x34d4593d, 0x3c0, 0xfffffff007c9bff0,
                                  0xfffffff00722c000, 0x11353000))
        self.assertEqual([(address, size) for address, size, value in result["stores"]],
                         [(RECORD + offset, 8) for offset in range(0, 72, 8)])
        expected = bytearray(result["sentinel"])
        expected[0x900:0x948] = struct.pack("<9Q", *record)
        self.assertEqual(result["memory"], expected)
        events = result["events"]
        self.assertEqual(events[:4], [("instruction", word) for word in (DSB, TLBI, DSB, ISB)])
        restore = events.index(("msr", TTBR1, 0x11353000))
        self.assertEqual(events[restore - 1:restore + 5],
                         [("instruction", DSB), ("msr", TTBR1, 0x11353000)] +
                         [("instruction", word) for word in (ISB, TLBI, DSB, ISB)])
        self.assertEqual(events[-1], ("store", RECORD + 64))

    def test_position_independent_at_distinct_high_and_low_addresses(self):
        for base in (0x200000, 0xfffffff007600000, 0xfffffff0078fff00):
            with self.subTest(base=hex(base)):
                result = self.execute(base)
                self.assertEqual(result["outcome"], "observer")

    def test_each_bad_root_rejects_without_stores_or_system_writes(self):
        for name, expected in (("ttbr0", 0x11352000), ("ttbr1", 0x12402000)):
            for value in (0, expected + 4096, expected | 1, expected | (1 << 48)):
                with self.subTest(register=name, value=hex(value)):
                    self.assert_rejected(**{name: value})

    def test_each_unmasked_daif_bit_rejects_without_writes(self):
        for bit in (6, 7, 8, 9):
            self.assert_rejected(daif=0x3c0 & ~(1 << bit))
        self.assert_rejected(daif=0)

    def test_unreviewed_tcr_rejects_without_writes(self):
        for value in (0, 0x22a51a251a ^ 1, 0x22a51a251a ^ (1 << 16)):
            self.assert_rejected(tcr=value)

    def assert_rejected(self, **kwargs):
        result = self.execute(**kwargs)
        self.assertEqual(result["outcome"], "reject")
        self.assertEqual(result["writes"], [])
        self.assertEqual(result["stores"], [])
        self.assertEqual(result["events"], [("instruction", WFE)])
        self.assertEqual(result["memory"], result["sentinel"])
        self.assertEqual(result["engine"].cpr_read(*TTBR1), kwargs.get("ttbr1", 0x12402000))


if __name__ == "__main__":
    unittest.main()
