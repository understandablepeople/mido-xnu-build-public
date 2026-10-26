"""Explicit synthetic PM8953 read protocol, never handset RTC verification."""


class MidoPmicRtc:
    def __init__(self, seconds, counter_read, apid=17):
        if not isinstance(seconds, int) or not 0 <= seconds <= 0xffffffff:
            raise ValueError("explicit unsigned RTC seconds required")
        if not callable(counter_read) or not 0 <= apid < 256:
            raise ValueError("counter callback and in-window APID required")
        self.seconds = seconds
        self.counter_read = counter_read
        self.origin = counter_read()
        self.apid = apid
        self.status = 0
        self.data = 0
        self.events = []

    def read(self, region, offset, size):
        if size != 4 or offset & 3:
            raise ValueError("RTC model supports aligned 32-bit MMIO only")
        if region == 0 and offset == 0:
            return 0x20010000
        if region == 0 and 0x800 <= offset < 0x1000:
            return (0x60 << 8) if offset == 0x800 + 4 * self.apid else 0
        if region == 1 and offset == self.apid * 0x8000 + 8:
            return self.status
        if region == 1 and offset == self.apid * 0x8000 + 0x18 and self.status == 1:
            return self.data
        raise ValueError(f"unmodeled RTC read {region}:{offset:#x}/{size}")

    def validate_write(self, region, offset, size, value):
        commands = {(1 << 27) | (5 << 4): (5, 1),
                    (1 << 27) | (0x46 << 4): (0x46, 1),
                    (1 << 27) | (0x48 << 4): (0x48, 1),
                    (1 << 27) | (0x48 << 4) | 3: (0x48, 4)}
        if region != 1 or offset != self.apid * 0x8000 or size != 4 or value not in commands:
            raise ValueError("RTC model rejects all non-allowlisted observer read commands")
        return commands[value]

    def write(self, region, offset, size, value):
        address, count = self.validate_write(region, offset, size, value)
        current = (self.seconds + ((self.counter_read() - self.origin) & ((1 << 64) - 1)) // 19200000) & 0xffffffff
        self.data = 1 if address == 5 else 0x80 if address == 0x46 else current
        if count == 1:
            self.data &= 0xff
        self.status = 1
        self.events.append(dict(address=0x6000 + address, count=count, returned=self.data))

    def map(self, cpu):
        for region, base, size in ((0, 0x0200f000, 0x1000), (1, 0x02c00000, 0x800000)):
            def read(engine, offset, size, context):
                return self.read(context, offset, size)
            def write(engine, offset, size, value, context):
                self.write(context, offset, size, value)
            cpu.mmio_map(base, size, read, region, write, region)

    def report(self):
        return dict(scope="synthetic PM8953 observer protocol only", initial_seconds=self.seconds,
                    apid=self.apid, read_commands=self.events, hardware_verified=False,
                    calibrated_utc=False, pmic_writes=0)
