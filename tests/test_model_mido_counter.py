import struct
import sys
import unittest
from pathlib import Path

from tools.model_mido_counter import MidoCounter
from tools.model_mido_gicv2 import MidoGicV2


class CounterTests(unittest.TestCase):
    def test_frequency_scaling_is_exact_and_host_provider_is_explicit(self):
        now = [1000000000]
        model = MidoCounter(monotonic_ns=lambda: now[0])
        self.assertEqual(model.counter(), 0)
        now[0] += 1000000000
        self.assertEqual(model.counter(), 19200000)
        now[0] += 500000000
        self.assertEqual(model.counter(), 28800000)
        report = model.report()
        self.assertFalse(report["instruction_timing_accurate"])
        self.assertFalse(report["rtc_wall_clock_provided"])

    def test_rejects_unknown_frequency_and_time_reversal(self):
        with self.assertRaises(ValueError):
            MidoCounter(frequency=62500000)
        now = [100]
        model = MidoCounter(monotonic_ns=lambda: now[0])
        now[0] = 99
        with self.assertRaisesRegex(ValueError, "backwards"):
            model.counter()

    def test_execution_clock_does_not_depend_on_host_delays(self):
        now = [100]
        model = MidoCounter(monotonic_ns=lambda: now[0], execution_hz=2016000000)
        model.charge(105)
        self.assertEqual(model.counter(), 1)
        now[0] += 100000000000
        self.assertEqual(model.counter(), 1)
        model.charge(2016000000)
        self.assertEqual(model.counter(), 19200001)

    def test_conservative_instruction_cost_is_explicit_not_hardware_claim(self):
        model = MidoCounter(execution_hz=2016000000, cycles_per_instruction=64)
        model.charge(105)
        self.assertEqual(model.counter(), 64)
        self.assertEqual(model.report()["assumed_cycles_per_instruction"], 64)
        self.assertFalse(model.report()["instruction_timing_accurate"])


class CounterInstructionTests(unittest.TestCase):
    def test_isr_reports_controller_irq_line_even_when_cpu_irq_is_masked(self):
        cpu, clock, gic = self.event_cpu()
        cpu.reg_write(self.registers.UC_ARM64_REG_PSTATE, 0x84)
        cpu.mem_write(0x100000, struct.pack("<I", 0xd538c100))
        for compare, mask, expected in ((5000, 0xf0, 0), (0, 0xf0, 0x80), (0, 0, 0)):
            gic.timer_compare = compare
            gic.registers[1, 4] = mask
            cpu.emu_start(0x100000, 0x100004, count=1)
            self.assertEqual(cpu.reg_read(self.registers.UC_ARM64_REG_X0), expected)
            self.assertEqual(cpu.reg_read(self.registers.UC_ARM64_REG_PSTATE), 0x84)

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

    def test_native_mrs_and_timer_use_the_same_frequency_and_counter(self):
        cpu = self.unicorn.Uc(self.unicorn.UC_ARCH_ARM64, self.unicorn.UC_MODE_ARM)
        cpu.ctl_set_cpu_model(self.registers.UC_CPU_ARM64_A53)
        cpu.cpr_write(3, 3, 14, 0, 0, 62500000)
        now = [0]
        clock = MidoCounter(monotonic_ns=lambda: now[0])
        clock.install(cpu)
        now[0] = 100000000
        gic = MidoGicV2(clock.counter)
        clock.attach_timer(gic)
        gic.map(cpu, register_timer_hooks=False)
        gic.timer_write(0, 100, clock.counter())
        code = struct.pack("<4I", 0xd53be000, 0xd53be021, 0xd53be042, 0xd53be303)
        cpu.mem_map(0x100000, 4096)
        cpu.mem_write(0x100000, code)
        cpu.emu_start(0x100000, 0x100010, count=4)
        values = [cpu.reg_read(getattr(self.registers, f"UC_ARM64_REG_X{index}")) for index in range(4)]
        self.assertEqual(values, [19200000, 1920000, 1920000, 100])
        self.assertEqual(clock.reads, 2)

    def test_idle_wait_advances_only_to_an_enabled_timer_deadline(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                cpu, clock, gic = self.event_cpu()
                gic.timer_control = int(enabled)
                clock.watch_idle(cpu, 0x100000)
                cpu.mem_write(0x100000, struct.pack("<2I", 0xd503207f, 0xd503201f))
                cpu.emu_start(0x100000, 0x100008, count=2)
                self.assertEqual(cpu.reg_read(self.registers.UC_ARM64_REG_PC), 0x100004)
                self.assertEqual(clock.idle_ticks, 5000 if enabled else 0)
                self.assertEqual(clock.idle_wakeups, int(enabled))

    def test_sev_wfe_consumes_event_without_advancing_time(self):
        cpu, clock, gic = self.event_cpu()
        code = struct.pack("<3I", 0xd503209f, 0xd503205f, 0xd503201f)
        cpu.mem_write(0x100000, code)
        clock.watch_idle(cpu, 0x100000, 0xd503209f)
        clock.watch_idle(cpu, 0x100004, 0xd503205f)
        cpu.emu_start(0x100000, 0x10000c, count=3)
        self.assertEqual(clock.idle_ticks, 0)
        self.assertFalse(clock.event_pending)
        self.assertEqual(bytes(cpu.mem_read(0x100000, len(code))), code)

    def event_cpu(self):
        cpu = self.unicorn.Uc(self.unicorn.UC_ARCH_ARM64, self.unicorn.UC_MODE_ARM)
        cpu.ctl_set_cpu_model(self.registers.UC_CPU_ARM64_A53)
        cpu.reg_write(self.registers.UC_ARM64_REG_PSTATE, 4)
        clock = MidoCounter(execution_hz=2016000000)
        clock.install(cpu)
        gic = MidoGicV2(clock.counter)
        gic.registers[0, 0x100] = 1 << 20
        gic.registers[1, 4] = 0xf0
        gic.timer_control = 1
        gic.timer_compare = 5000
        clock.attach_timer(gic)
        gic.map(cpu, register_timer_hooks=False)
        cpu.mem_map(0x100000, 4096)
        return cpu, clock, gic
