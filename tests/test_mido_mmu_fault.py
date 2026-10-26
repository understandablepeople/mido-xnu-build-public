import struct
import importlib
import unittest

from tools.mido_mmu_fault import enter_store_translation_abort, walk_upper


class UpperTranslationTests(unittest.TestCase):
    def walk(self, descriptors, address=0xfffffff018000000, tcr=(25 << 16) | (1 << 30)):
        def read(location, count):
            self.assertEqual(count, 8)
            return struct.pack("<Q", descriptors.get(location, 0))
        return walk_upper(read, tcr, 0x10000, address)

    def test_missing_native_entry_is_not_fabricated(self):
        report = self.walk({})
        self.assertEqual(report["status"], "invalid-descriptor")
        self.assertEqual(report["fault_level"], 1)
        self.assertNotIn("physical", report)

    def test_native_16k_table_path_and_rw_leaf(self):
        address = 0xfffffff018000000
        first = 0x10000 + ((address >> 36) & 7) * 8
        second = 0x14000 + ((address >> 25) & 2047) * 8
        third = 0x18000 + ((address >> 14) & 2047) * 8
        report = self.walk({first: 0x14003, second: 0x18003, third: 0x20000403})
        self.assertEqual(report["status"], "mapped")
        self.assertEqual(report["physical"], 0x20000000)
        self.assertTrue(report["access_flag"])
        self.assertEqual(report["access_permissions"], 0)
        self.assertEqual([entry["level"] for entry in report["levels"]], [1, 2, 3])

    def test_disabled_upper_walk(self):
        report = self.walk({}, tcr=(25 << 16) | (1 << 30) | (1 << 23))
        self.assertEqual(report["status"], "walk-disabled")
        self.assertEqual(report["levels"], [])

    def test_unknown_geometry_rejected(self):
        with self.assertRaises(ValueError):
            self.walk({}, tcr=25 << 16)


class NativeAbortReturnTests(unittest.TestCase):
    def test_real_vector_maps_missing_page_and_erets_to_original_store(self):
        try:
            unicorn = importlib.import_module("unicorn")
        except ImportError:
            self.skipTest("Unicorn not installed")
        registers = importlib.import_module("unicorn.arm64_const")
        cpu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
        cpu.ctl_set_cpu_model(registers.UC_CPU_ARM64_A53)
        cpu.ctl_tlb_mode(unicorn.UC_TLB_CPU)
        cpu.mem_map(0, 0x20000)
        cpu.mem_write(0x1000, bytes.fromhex("090100b9"))
        cpu.mem_write(0x8000, bytes.fromhex("6a0100f99f3a03d51f8708d59f3b03d5df3f03d5e0039fd6"))
        cpu.mem_write(0x10000, struct.pack("<Q", 0x11003))
        cpu.mem_write(0x11000, struct.pack("<Q", 0x701))
        cpu.mem_write(0x12000, struct.pack("<Q", 0x13003))
        cpu.cpr_write(3, 6, 1, 1, 0, (1 << 10) | 1)
        cpu.cpr_write(3, 4, 1, 1, 0, 1 << 31)
        cpu.reg_write(registers.UC_ARM64_REG_PSTATE, 0x3c4)
        cpu.reg_write(registers.UC_ARM64_REG_SP_EL1, 0x1e000)
        cpu.reg_write(registers.UC_ARM64_REG_SP, 0x1f000)
        cpu.reg_write(registers.UC_ARM64_REG_VBAR_EL1, 0x8000)
        cpu.reg_write(registers.UC_ARM64_REG_X8, 0xffffff8000000000)
        cpu.reg_write(registers.UC_ARM64_REG_X9, 0x12345678)
        cpu.reg_write(registers.UC_ARM64_REG_X10, 0x701)
        cpu.reg_write(registers.UC_ARM64_REG_X11, 0x13000)
        cpu.cpr_write(3, 0, 2, 0, 0, 0x10000)
        cpu.cpr_write(3, 0, 2, 0, 1, 0x12000)
        cpu.cpr_write(3, 0, 2, 0, 2, 25 | (25 << 16) | (2 << 30))
        cpu.cpr_write(3, 0, 10, 2, 0, 0xff)
        cpu.cpr_write(3, 0, 1, 0, 0, 1)
        exceptions = []
        def trapped(engine, number, context):
            exceptions.append(number)
            engine.emu_stop()
        hook = cpu.hook_add(unicorn.UC_HOOK_INTR, trapped)
        cpu.emu_start(0x1000, 0x1004, count=100)
        self.assertEqual(exceptions, [4])
        delivery = enter_store_translation_abort(cpu, lambda address, count: bytes(cpu.mem_read(address, count)),
                                                  0xb9000109)
        self.assertEqual(delivery["esr"], 0x97890046)
        self.assertEqual(delivery["translation"]["fault_level"], 2)
        cpu.emu_start(cpu.reg_read(registers.UC_ARM64_REG_PC), 0x1004, count=100)
        cpu.hook_del(hook)
        self.assertEqual(exceptions, [4])
        self.assertEqual(cpu.reg_read(registers.UC_ARM64_REG_PC), 0x1004)
        self.assertEqual(cpu.reg_read(registers.UC_ARM64_REG_PSTATE), 0x3c4)
        self.assertEqual(cpu.reg_read(registers.UC_ARM64_REG_SP), 0x1f000)
        self.assertEqual(bytes(cpu.mem_read(0, 4)), struct.pack("<I", 0x12345678))


if __name__ == "__main__":
    unittest.main()
