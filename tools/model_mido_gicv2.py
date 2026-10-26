"""Bounded synthetic GICv2 MMIO for original kernel startup, not IRQ delivery."""


class MidoGicV2:
    def __init__(self, counter_read=None, self_sgi=False):
        self.counter_read = counter_read
        self.self_sgi = self_sgi
        self.self_sgi_pending = False
        self.registers = {(0, 0): 1, (0, 4): 2, (0, 0x80): 1 << 20,
                          (0, 0xc04): 0, (0, 0x414): 0, (0, 0x100): 0,
                          (1, 0): 1, (1, 4): 0, (1, 0x0c): 1023}
        self.events = []
        self.active_token = None
        self.timer_control = 0
        self.timer_compare = 0
        self.timer_hooks = []
        if self_sgi:
            self.registers[0, 0x80] |= 1
            self.registers[0, 0x400] = 0

    def timer_read(self, register, counter):
        if register == 1:
            return self.timer_control | (4 if self.timer_control & 1 and counter >= self.timer_compare else 0)
        if register == 0:
            return (self.timer_compare - counter) & 0xffffffff
        if register == 2:
            return self.timer_compare
        raise ValueError("unmodeled architectural timer register")

    def timer_write(self, register, value, counter):
        if register == 1:
            self.timer_control = value & 3
        elif register == 0:
            delta = value & 0xffffffff
            if delta & 0x80000000:
                delta -= 1 << 32
            self.timer_compare = (counter + delta) & ((1 << 64) - 1)
        elif register == 2:
            self.timer_compare = value & ((1 << 64) - 1)
        else:
            raise ValueError("unmodeled architectural timer register")
        self.events.append(dict(operation="timer-write", register=register, value=value))

    def read(self, region, offset, size):
        if size != 4 or (region, offset) not in self.registers:
            raise ValueError(f"unmodeled GIC read: {region}:{offset:#x}/{size}")
        value = self.registers[region, offset]
        if region == 1 and offset == 0x0c and value < 1020:
            if self.active_token is not None:
                raise ValueError("GIC token overwritten before EOI")
            self.active_token = value
            self.registers[1, 0x0c] = 1023
        self.events.append(dict(operation="read", region=region, offset=offset, value=value))
        return value

    def write(self, region, offset, size, value):
        permitted = ((0, 0x414), (0, 0x100), (1, 4), (1, 0x10))
        if self.self_sgi:
            permitted += ((0, 0x400), (0, 0xf00))
        if size != 4 or (region, offset) not in permitted:
            raise ValueError(f"unmodeled GIC write: {region}:{offset:#x}/{size}")
        if (region, offset) == (0, 0x100):
            if value != 1 << 20 and not (self.self_sgi and value == 1):
                raise ValueError("GIC model permits only virtual timer enable")
            self.registers[region, offset] |= value
        elif (region, offset) == (0, 0xf00):
            if value != 2 << 24 or not self.registers[0, 0x100] & 1:
                raise ValueError("unreviewed self-SGI target or disabled route")
            self.self_sgi_pending = True
        elif (region, offset) == (1, 0x10):
            if self.active_token != value:
                raise ValueError("GIC EOI does not match an active token")
            self.active_token = None
        else:
            self.registers[region, offset] = value
        self.events.append(dict(operation="write", region=region, offset=offset, value=value))

    def map(self, cpu, register_timer_hooks=True):
        from unicorn import UC_HOOK_INSN
        from unicorn.arm64_const import UC_ARM64_INS_MRS, UC_ARM64_INS_MSR

        def timer_access(engine, register, encoding, writing):
            key = (encoding.op0, encoding.op1, encoding.crn, encoding.crm)
            if key != (3, 3, 14, 3) or encoding.op2 not in (0, 1, 2):
                return 0
            counter = self.counter_read() if self.counter_read else engine.cpr_read(3, 3, 14, 0, 2)
            if writing:
                self.timer_write(encoding.op2, engine.reg_read(register), counter)
            else:
                engine.reg_write(register, self.timer_read(encoding.op2, counter))
            return 1

        if register_timer_hooks:
            self.timer_hooks.append(cpu.hook_add(UC_HOOK_INSN, timer_access, True, aux1=UC_ARM64_INS_MSR))
            self.timer_hooks.append(cpu.hook_add(UC_HOOK_INSN, timer_access, False, aux1=UC_ARM64_INS_MRS))
        for region, base in ((0, 0x0b000000), (1, 0x0b002000)):
            def read(engine, offset, size, context):
                return self.read(context, offset, size)
            def write(engine, offset, size, value, context):
                self.write(context, offset, size, value)
            cpu.mmio_map(base, 4096, read, region, write, region)

    def report(self):
        return dict(scope="synthetic NS GICv2 MMIO; no exception delivery or handset access",
                    assumptions=["firmware enables distributor and NS CPU interface",
                                 "PPI 20 is accessible Group 1 and level-sensitive"],
                    timer_enabled=bool(self.registers[0, 0x100] & (1 << 20)),
                    events=self.events, self_sgi_enabled=self.self_sgi,
                    self_sgi_pending=self.self_sgi_pending, irq_delivery_proven=False, hardware_verified=False)
