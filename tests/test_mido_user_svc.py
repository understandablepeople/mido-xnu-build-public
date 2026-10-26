import importlib
import struct
import unittest

from tools.mido_user_svc import enter_user_svc


class UserSvcTests(unittest.TestCase):
    def test_original_svc_native_vector_and_eret_preserve_user_registers(self):
        try:
            unicorn = importlib.import_module("unicorn")
        except ImportError:
            self.skipTest("Unicorn not installed")
        registers = importlib.import_module("unicorn.arm64_const")
        cpu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
        cpu.ctl_set_cpu_model(registers.UC_CPU_ARM64_A53)
        cpu.ctl_tlb_mode(unicorn.UC_TLB_CPU)
        cpu.mem_map(0, 0x20000)
        cpu.mem_write(0x1000, bytes.fromhex("011000d41f2003d51f2003d5"))
        cpu.mem_write(0x8400, bytes.fromhex("a00480d2e0039fd6"))
        for address, descriptor in ((0x10000, 0x11003), (0x11000, 0x741),
                                    (0x12000, 0x13003), (0x13000, 0x701)):
            cpu.mem_write(address, struct.pack("<Q", descriptor))
        cpu.cpr_write(3, 6, 1, 1, 0, 1025)
        cpu.cpr_write(3, 4, 1, 1, 0, 1 << 31)
        cpu.reg_write(registers.UC_ARM64_REG_PSTATE, 0)
        cpu.reg_write(registers.UC_ARM64_REG_SP_EL1, 0x1e000)
        cpu.reg_write(registers.UC_ARM64_REG_SP, 0x1f000)
        cpu.reg_write(registers.UC_ARM64_REG_VBAR_EL1, 0xffffff8000008000)
        cpu.reg_write(registers.UC_ARM64_REG_X16, 20)
        for operand, value in ((0, 0x10000), (1, 0x12000), (2, 25 | (25 << 16) | (2 << 30))):
            cpu.cpr_write(3, 0, 2, 0, operand, value)
        cpu.cpr_write(3, 0, 10, 2, 0, 255)
        cpu.cpr_write(3, 0, 1, 0, 0, 1)
        exceptions = []
        executed = []
        def code(engine, address, size, context):
            executed.append(address)
            if address == 0x1008:
                engine.emu_stop()
        def trap(engine, number, context):
            exceptions.append(number)
            engine.emu_stop()
        cpu.hook_add(unicorn.UC_HOOK_CODE, code)
        cpu.hook_add(unicorn.UC_HOOK_INTR, trap)
        cpu.emu_start(0x1000, 0, count=100)
        self.assertEqual(exceptions, [2])
        original_memory = bytes(cpu.mem_read(0, 0x20000))
        state_before = tuple(cpu.reg_read(register) for register in (registers.UC_ARM64_REG_PC,
            registers.UC_ARM64_REG_PSTATE, registers.UC_ARM64_REG_X0, registers.UC_ARM64_REG_SP))
        with self.assertRaises(ValueError):
            enter_user_svc(cpu, lambda address, count: bytes(count) if address == 0x1000
                           else bytes(cpu.mem_read(address, count)), 0x1000)
        self.assertEqual(state_before, tuple(cpu.reg_read(register) for register in (registers.UC_ARM64_REG_PC,
            registers.UC_ARM64_REG_PSTATE, registers.UC_ARM64_REG_X0, registers.UC_ARM64_REG_SP)))
        delivery = enter_user_svc(cpu, lambda address, count: bytes(cpu.mem_read(address, count)), 0x1000)
        self.assertEqual(delivery["esr"], 0x56000080)
        self.assertFalse(delivery["syscall_result_emulated"])
        self.assertEqual(bytes(cpu.mem_read(0, 0x20000)), original_memory)
        self.assertEqual(cpu.reg_read(registers.UC_ARM64_REG_X0), 0)
        cpu.emu_start(delivery["vector_entry"], 0, count=100)
        self.assertEqual(exceptions, [2])
        self.assertEqual(executed, [0x1000, 0xffffff8000008400, 0xffffff8000008404, 0x1004, 0x1008])
        self.assertEqual(cpu.reg_read(registers.UC_ARM64_REG_X0), 37)
        self.assertEqual(cpu.reg_read(registers.UC_ARM64_REG_X16), 20)
        self.assertEqual(cpu.reg_read(registers.UC_ARM64_REG_SP), 0x1f000)
        self.assertEqual(cpu.reg_read(registers.UC_ARM64_REG_PSTATE), 0)
        with self.assertRaises(ValueError):
            enter_user_svc(cpu, lambda address, count: bytes(cpu.mem_read(address, count)), 0x1004)


if __name__ == "__main__":
    unittest.main()
