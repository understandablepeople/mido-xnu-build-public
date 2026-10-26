"""Explicit host-monotonic ARM counter model; not handset or CPU-cycle timing."""

import time


class MidoCounter:
    def __init__(self, frequency=19200000, monotonic_ns=None, execution_hz=None, execution_ranges=None,
                 cycles_per_instruction=1):
        if frequency != 19200000:
            raise ValueError("unsupported diagnostic counter frequency")
        self.frequency = frequency
        self.monotonic_ns = monotonic_ns or time.monotonic_ns
        self.origin = self.monotonic_ns()
        self.last = 0
        self.reads = 0
        self.hooks = []
        self.timer = None
        if execution_hz not in (None, 2016000000):
            raise ValueError("unsupported synthetic execution frequency")
        self.execution_hz = execution_hz
        self.execution_ranges = execution_ranges
        if cycles_per_instruction not in (1, 64):
            raise ValueError("unsupported synthetic instruction cost")
        self.cycles_per_instruction = cycles_per_instruction
        self.execution_started = False
        self.charged_instructions = 0
        self.idle_ticks = 0
        self.idle_wakeups = 0
        self.event_pending = False

    def charge(self, instructions):
        if instructions < 0:
            raise ValueError("negative instruction charge")
        self.charged_instructions += instructions

    def attach_timer(self, timer):
        if self.timer is not None or timer.counter_read != self.counter:
            raise ValueError("timer must share one diagnostic counter")
        self.timer = timer

    def counter(self):
        if self.execution_hz:
            value = self.charged_instructions * self.cycles_per_instruction * self.frequency // self.execution_hz + self.idle_ticks
            self.last = value
            return value
        elapsed = self.monotonic_ns() - self.origin
        value = elapsed * self.frequency // 1000000000
        if elapsed < 0 or value < self.last:
            raise ValueError("diagnostic monotonic counter moved backwards")
        self.last = value
        return value

    def install(self, cpu, track_execution=True):
        from unicorn import UC_HOOK_INSN
        from unicorn.arm64_const import UC_ARM64_INS_MRS, UC_ARM64_INS_MSR

        def read(engine, register, encoding, context):
            key = (encoding.op0, encoding.op1, encoding.crn, encoding.crm, encoding.op2)
            if key == (3, 3, 14, 0, 0):
                value = self.frequency
            elif key in ((3, 3, 14, 0, 1), (3, 3, 14, 0, 2)):
                value = self.counter()
                self.reads += 1
            elif key == (3, 0, 12, 1, 0):
                if self.timer is None:
                    raise ValueError("IRQ status accessed before diagnostic controller attachment")
                try:
                    from tools.mido_pending_irq import pending_timer_irq, pending_self_sgi
                except ModuleNotFoundError:
                    from mido_pending_irq import pending_timer_irq, pending_self_sgi
                value = 0x80 if (pending_timer_irq(self.timer, self.counter(), 4) or
                                 pending_self_sgi(self.timer, 4)) else 0
            elif key[:4] == (3, 3, 14, 3) and key[4] in (0, 1, 2):
                if self.timer is None:
                    raise ValueError("architectural timer accessed before diagnostic attachment")
                value = self.timer.timer_read(key[4], self.counter())
            else:
                return 0
            engine.reg_write(register, value)
            return 1

        def write(engine, register, encoding, context):
            key = (encoding.op0, encoding.op1, encoding.crn, encoding.crm, encoding.op2)
            if key == (3, 3, 14, 0, 0):
                if engine.reg_read(register) != self.frequency:
                    raise ValueError("kernel attempted to change diagnostic counter frequency")
                return 1
            if key[:4] == (3, 3, 14, 3) and key[4] in (0, 1, 2):
                if self.timer is None:
                    raise ValueError("architectural timer accessed before diagnostic attachment")
                self.timer.timer_write(key[4], engine.reg_read(register), self.counter())
                return 1
            return 0

        self.hooks.append(cpu.hook_add(UC_HOOK_INSN, read, aux1=UC_ARM64_INS_MRS))
        self.hooks.append(cpu.hook_add(UC_HOOK_INSN, write, aux1=UC_ARM64_INS_MSR))
        if track_execution:
            self.start_execution(cpu)

    def start_execution(self, cpu):
        from unicorn import UC_HOOK_BLOCK

        if self.execution_hz and not self.execution_started:
            def block(engine, address, size, context):
                self.charge(size // 4)
            for start, end in self.execution_ranges or ((1, 0),):
                self.hooks.append(cpu.hook_add(UC_HOOK_BLOCK, block, begin=start, end=end))
            self.execution_started = True

    def watch_idle(self, cpu, address, instruction=0xd503207f):
        if instruction not in (0xd503205f, 0xd503207f, 0xd503209f, 0xd50320bf):
            raise ValueError("unreviewed architectural idle hint")
        from unicorn import UC_HOOK_CODE
        from unicorn.arm64_const import UC_ARM64_REG_PSTATE
        try:
            from tools.mido_pending_irq import pending_timer_irq
        except ModuleNotFoundError:
            from mido_pending_irq import pending_timer_irq

        def idle(engine, pc, size, context):
            if instruction in (0xd503209f, 0xd50320bf):
                self.event_pending = True
                return
            if instruction == 0xd503205f and self.event_pending:
                self.event_pending = False
                self.idle_wakeups += 1
                return
            timer = self.timer
            if timer is None or not self.execution_hz:
                return
            state = engine.reg_read(UC_ARM64_REG_PSTATE)
            now = self.counter()
            if not pending_timer_irq(timer, max(now, timer.timer_compare), state & ~0x80):
                return
            self.idle_ticks += max(0, timer.timer_compare - now)
            self.idle_wakeups += 1

        self.hooks.append(cpu.hook_add(UC_HOOK_CODE, idle, begin=address, end=address))

    def report(self):
        return dict(frequency_hz=self.frequency, last_counter=self.last, native_counter_reads=self.reads,
                    source="basic-block instruction charge plus native WFI/WFE timer deadlines" if self.execution_hz else "host monotonic elapsed time, integer scaling from nanoseconds",
                    nominal_execution_hz=self.execution_hz, charged_instructions=self.charged_instructions,
                    assumed_cycles_per_instruction=self.cycles_per_instruction,
                    idle_ticks=self.idle_ticks, idle_wakeups=self.idle_wakeups,
                    instruction_timing_accurate=False, rtc_wall_clock_provided=False,
                    handset_timing_proven=False, boot_approved=False)
