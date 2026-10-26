import argparse
import ctypes
import unittest


Read32 = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                          ctypes.POINTER(ctypes.c_uint32))
ReadCommand = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32)
Counter = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_void_p)
Synchronize = ctypes.CFUNCTYPE(None, ctypes.c_void_p)


class Io(ctypes.Structure):
    _fields_ = [("context", ctypes.c_void_p), ("read32", Read32), ("read_command", ReadCommand),
                ("counter", Counter), ("synchronize", Synchronize)]


class State(ctypes.Structure):
    _fields_ = [("io", ctypes.POINTER(Io)), ("observer_offset", ctypes.c_uint32), ("ready", ctypes.c_uint32)]


class RegisterModel:
    def __init__(self):
        self.version = 0x20010000
        self.apid = 17
        self.mapping = {self.apid: 0x60 << 8}
        self.subtype = 1
        self.control = 0x80
        self.seconds = 0x01020304
        self.sequence = []
        self.status = 1
        self.value = 0
        self.ticks = 0
        self.step = 100
        self.status_reads = 0
        self.commands = []
        self.violations = []
        self.fail_reads = False
        self.fail_command = False
        self.reader = Read32(self.read32)
        self.commander = ReadCommand(self.command)
        self.clock = Counter(self.counter)
        self.sync = Synchronize(lambda context: None)
        self.io = Io(None, self.reader, self.commander, self.clock, self.sync)
        self.state = State()

    def counter(self, context):
        self.ticks = (self.ticks + self.step) & ((1 << 64) - 1)
        return self.ticks

    def read32(self, context, region, offset, value):
        if self.fail_reads:
            return -1
        if region == 0 and offset == 0:
            value[0] = self.version
        elif region == 0 and 0x800 <= offset < 0x1000 and offset % 4 == 0:
            value[0] = self.mapping.get((offset - 0x800) // 4, 0)
        elif region == 1 and offset == self.apid * 0x8000 + 8:
            self.status_reads += 1
            value[0] = self.status
        elif region == 1 and offset == self.apid * 0x8000 + 0x18:
            value[0] = self.value
        else:
            self.violations.append(("read", region, offset))
            return -1
        return 0

    def command(self, context, offset, command):
        if self.fail_command:
            return -1
        address = (command >> 4) & 0xff
        count = (command & 7) + 1
        expected = (1 << 27) | (address << 4) | (count - 1)
        if offset != self.apid * 0x8000 or command != expected or (address, count) not in ((5, 1), (0x46, 1), (0x48, 1), (0x48, 4)):
            self.violations.append(("command", offset, command))
            return -1
        self.commands.append((address, count))
        self.value = self.subtype if address == 5 else self.control if address == 0x46 else self.sequence.pop(0) if self.sequence else self.seconds
        return 0


class PmicRtcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = ctypes.CDLL(LIBRARY)
        cls.library.mido_pmic_rtc_attach.argtypes = [ctypes.POINTER(State), ctypes.POINTER(Io)]
        cls.library.mido_pmic_rtc_seconds.argtypes = [ctypes.POINTER(State), ctypes.POINTER(ctypes.c_uint32)]
        cls.library.mido_pmic_rtc_discover.argtypes = [ctypes.POINTER(Io), ctypes.POINTER(ctypes.c_uint32)]

    def test_discovery_needs_no_observer_access_and_preserves_failed_output(self):
        model = RegisterModel()
        offset = ctypes.c_uint32(0xdeadbeef)
        self.assertEqual(self.library.mido_pmic_rtc_discover(ctypes.byref(model.io), ctypes.byref(offset)), 0)
        self.assertEqual(offset.value, 17 * 0x8000)
        self.assertFalse(model.commands)
        self.assertFalse(model.violations)
        model.version = 0
        offset.value = 0xdeadbeef
        self.assertEqual(self.library.mido_pmic_rtc_discover(ctypes.byref(model.io), ctypes.byref(offset)), -2)
        self.assertEqual(offset.value, 0xdeadbeef)
        self.assertEqual(self.library.mido_pmic_rtc_discover(None, ctypes.byref(offset)), -1)
        self.assertEqual(self.library.mido_pmic_rtc_discover(ctypes.byref(model.io), None), -1)

    def attached(self):
        model = RegisterModel()
        self.assertEqual(self.library.mido_pmic_rtc_attach(ctypes.byref(model.state), ctypes.byref(model.io)), 0)
        self.assertEqual(model.state.observer_offset, 17 * 0x8000)
        self.assertFalse(model.violations)
        return model

    def read(self, model):
        value = ctypes.c_uint32(0xdeadbeef)
        status = self.library.mido_pmic_rtc_seconds(ctypes.byref(model.state), ctypes.byref(value))
        self.assertFalse(model.violations)
        return status, value.value

    def test_actual_seconds_are_returned_without_calendar_offset(self):
        model = self.attached()
        for seconds in (0, 65478350, 0x01020304, 0xffffffff):
            model.seconds = seconds
            self.assertEqual(self.read(model), (0, seconds))
        self.assertTrue(all(address in (5, 0x46, 0x48) for address, count in model.commands))

    def test_rollover_retries_the_complete_word(self):
        model = self.attached()
        model.sequence = [0x123456ff, 0, 0x12345700, 0]
        self.assertEqual(self.read(model), (0, 0x12345700))
        self.assertFalse(model.sequence)

    def test_repeated_rollover_is_bounded_and_does_not_change_output(self):
        model = self.attached()
        model.sequence = [0x123456ff, 0] * 3
        self.assertEqual(self.read(model), (-5, 0xdeadbeef))

    def test_disabled_clock_is_never_enabled(self):
        model = self.attached()
        model.control = 0
        self.assertEqual(self.read(model), (-6, 0xdeadbeef))
        model.state.ready = 1
        self.assertEqual(self.library.mido_pmic_rtc_attach(ctypes.byref(model.state), ctypes.byref(model.io)), -6)
        self.assertFalse(model.state.ready)

    def test_denied_failed_dropped_or_io_faults_preserve_output(self):
        for error in (2, 4, 8, 3, 5, 9):
            model = self.attached()
            model.status = error
            self.assertEqual(self.read(model), (-3, 0xdeadbeef))
        for attribute in ("fail_reads", "fail_command"):
            model = self.attached()
            setattr(model, attribute, True)
            self.assertEqual(self.read(model), (-3, 0xdeadbeef))

    def test_timeout_uses_counter_and_is_also_bounded_if_counter_stalls(self):
        for step in (0, 100, 1 << 63):
            model = self.attached()
            model.status = 0
            model.step = step
            model.status_reads = 0
            self.assertEqual(self.read(model), (-4, 0xdeadbeef))
            self.assertLessEqual(model.status_reads, 4096)

    def test_counter_wrap_does_not_make_a_transaction_unbounded(self):
        model = self.attached()
        model.status = 0
        model.ticks = (1 << 64) - 200
        model.status_reads = 0
        self.assertEqual(self.read(model), (-4, 0xdeadbeef))
        self.assertLess(model.status_reads, 30)

    def test_unknown_version_missing_duplicate_or_out_of_aperture_mapping(self):
        for mapping in ({}, {17: 0x60 << 8, 18: 0x60 << 8}, {256: 0x60 << 8}):
            model = RegisterModel()
            model.mapping = mapping
            self.assertEqual(self.library.mido_pmic_rtc_attach(ctypes.byref(model.state), ctypes.byref(model.io)), -2)
            self.assertFalse(model.commands)
        model = RegisterModel()
        model.version = 0x30000000
        self.assertEqual(self.library.mido_pmic_rtc_attach(ctypes.byref(model.state), ctypes.byref(model.io)), -2)
        self.assertFalse(model.commands)

    def test_wrong_peripheral_subtype_never_reads_or_writes_clock(self):
        model = RegisterModel()
        model.subtype = 3
        self.assertEqual(self.library.mido_pmic_rtc_attach(ctypes.byref(model.state), ctypes.byref(model.io)), -2)
        self.assertEqual(model.commands, [(5, 1)])

    def test_invalid_state_and_callbacks(self):
        model = RegisterModel()
        self.assertEqual(self.read(model), (-1, 0xdeadbeef))
        self.assertEqual(self.library.mido_pmic_rtc_attach(None, ctypes.byref(model.io)), -1)
        model.io.read_command = ReadCommand()
        self.assertEqual(self.library.mido_pmic_rtc_attach(ctypes.byref(model.state), ctypes.byref(model.io)), -1)
        self.assertFalse(model.commands)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", required=True)
    args, remaining = parser.parse_known_args()
    LIBRARY = args.library
    unittest.main(argv=[__file__, *remaining], verbosity=2)
