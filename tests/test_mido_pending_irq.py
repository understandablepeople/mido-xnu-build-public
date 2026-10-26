import unittest
import sys
from pathlib import Path

from tools.mido_pending_irq import enter_timer_irq, pending_timer_irq, enter_self_sgi, pending_self_sgi
from tools.model_mido_gicv2 import MidoGicV2


class PendingTimerTests(unittest.TestCase):
    def test_self_sgi_requires_its_own_enabled_unmasked_group_and_priority(self):
        model = MidoGicV2(self_sgi=True)
        model.registers[1, 4] = 0xff
        model.write(0, 0x100, 4, 1)
        model.write(0, 0xf00, 4, 2 << 24)
        self.assertTrue(pending_self_sgi(model, 4))
        self.assertFalse(pending_self_sgi(model, 0x84))
        self.assertFalse(pending_self_sgi(model, 5))
        for register in ((0, 0), (1, 0), (0, 0x80), (0, 0x100), (1, 4)):
            before = model.registers[register]
            model.registers[register] = 0
            self.assertFalse(pending_self_sgi(model, 4))
            model.registers[register] = before
        model.active_token = 20
        self.assertFalse(pending_self_sgi(model, 4))

    def setUp(self):
        self.model = MidoGicV2()
        self.model.registers[0, 0x100] = 1 << 20
        self.model.registers[1, 4] = 0xf0
        self.model.timer_control = 1
        self.model.timer_compare = 100

    def test_only_expired_unmasked_el1t_timer_is_eligible(self):
        self.assertTrue(pending_timer_irq(self.model, 100, 4))
        self.assertFalse(pending_timer_irq(self.model, 99, 4))
        for state in (0x84, 5, 0, 8):
            self.assertFalse(pending_timer_irq(self.model, 100, state))
        for control in (0, 2, 3):
            self.model.timer_control = control
            self.assertFalse(pending_timer_irq(self.model, 100, 4))

    def test_rejects_disabled_or_masked_gic(self):
        for register in ((0, 0), (1, 0), (0, 0x80), (0, 0x100), (1, 4)):
            with self.subTest(register=register):
                before = self.model.registers[register]
                self.model.registers[register] = 0
                self.assertFalse(pending_timer_irq(self.model, 100, 4))
                self.model.registers[register] = before
        self.model.registers[0, 0x414] = 0xf0
        self.assertFalse(pending_timer_irq(self.model, 100, 4))

    def test_never_overwrites_pending_or_active_tokens(self):
        self.model.active_token = 20
        self.assertFalse(pending_timer_irq(self.model, 100, 4))
        self.model.active_token = None
        self.model.registers[1, 0x0c] = 28
        self.assertFalse(pending_timer_irq(self.model, 100, 4))


class ExceptionEntryTests(unittest.TestCase):
    def test_self_sgi_delivery_consumes_pending_and_preserves_general_registers(self):
        model = MidoGicV2(self_sgi=True)
        model.registers[1, 4] = 0xff
        model.write(0, 0x100, 4, 1)
        model.write(0, 0xf00, 4, 2 << 24)
        outcome = enter_self_sgi(self.cpu, model, 123)
        self.assertEqual(outcome["interrupt_id"], 0)
        self.assertFalse(model.self_sgi_pending)
        self.assertEqual(self.cpu.reg_read(self.registers.UC_ARM64_REG_PC), 0x400080)
        for index in range(31):
            self.assertEqual(self.cpu.reg_read(getattr(self.registers, f"UC_ARM64_REG_X{index}")), 100 + index)
        self.assertEqual(model.read(1, 12, 4), 0)
        model.write(1, 16, 4, 0)
        self.assertIsNone(model.active_token)

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "artifacts/python-deps"))
        try:
            import unicorn
            from unicorn import arm64_const
        except ImportError:
            raise unittest.SkipTest("Unicorn is not installed")
        cls.unicorn = unicorn
        cls.registers = arm64_const

    def setUp(self):
        self.cpu = self.unicorn.Uc(self.unicorn.UC_ARCH_ARM64, self.unicorn.UC_MODE_ARM)
        self.cpu.ctl_set_cpu_model(self.registers.UC_CPU_ARM64_A53)
        self.model = MidoGicV2()
        self.model.registers[0, 0x100] = 1 << 20
        self.model.registers[1, 4] = 0xf0
        self.model.timer_control = 1
        self.model.timer_compare = 0
        for name, value in (("PSTATE", 4), ("SP_EL1", 0x300000), ("SP", 0x200000),
                            ("PC", 0x100000), ("VBAR_EL1", 0x400000)):
            self.cpu.reg_write(getattr(self.registers, "UC_ARM64_REG_" + name), value)
        for index in range(31):
            self.cpu.reg_write(getattr(self.registers, f"UC_ARM64_REG_X{index}"), 100 + index)

    def test_exception_only_changes_architectural_entry_state(self):
        outcome = enter_timer_irq(self.cpu, self.model)
        self.assertEqual(outcome["interrupted_pc"], 0x100000)
        for name, expected in (("PC", 0x400080), ("ELR_EL1", 0x100000),
                               ("SP_EL0", 0x200000), ("SP", 0x300000), ("PSTATE", 0x3c5)):
            self.assertEqual(self.cpu.reg_read(getattr(self.registers, "UC_ARM64_REG_" + name)), expected)
        self.assertEqual(self.cpu.cpr_read(3, 0, 4, 0, 0), 4)
        for index in range(31):
            self.assertEqual(self.cpu.reg_read(getattr(self.registers, f"UC_ARM64_REG_X{index}")), 100 + index)
        self.assertIsNone(self.model.active_token)
        self.assertEqual(self.model.read(1, 0x0c, 4), 20)
        self.model.write(1, 0x10, 4, 20)
        self.assertIsNone(self.model.active_token)

    def test_ineligible_exception_cannot_change_cpu_or_pending_token(self):
        self.cpu.reg_write(self.registers.UC_ARM64_REG_PSTATE, 0x84)
        with self.assertRaisesRegex(ValueError, "ineligible"):
            enter_timer_irq(self.cpu, self.model)
        self.assertEqual(self.cpu.reg_read(self.registers.UC_ARM64_REG_PC), 0x100000)
        self.assertEqual(self.model.registers[1, 0x0c], 1023)
