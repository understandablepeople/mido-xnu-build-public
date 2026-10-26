import argparse
import ctypes
import sys
import unittest


Read32 = ctypes.CFUNCTYPE(ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32)
Write32 = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32)
Sync = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
Counter = ctypes.CFUNCTYPE(ctypes.c_uint64, ctypes.c_void_p)
Control = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32)
Compare = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint64)


class GicIo(ctypes.Structure):
    _fields_ = [("context", ctypes.c_void_p), ("read32", Read32), ("write32", Write32), ("synchronize", Sync)]


class GicState(ctypes.Structure):
    _fields_ = [("io", ctypes.POINTER(GicIo)), ("interrupt_count", ctypes.c_uint32),
                ("active_iar", ctypes.c_uint32), ("active", ctypes.c_uint32), ("ready", ctypes.c_uint32)]


class TimerIo(ctypes.Structure):
    _fields_ = [("context", ctypes.c_void_p), ("read_counter", Counter), ("write_control", Control),
                ("write_compare", Compare), ("synchronize", Sync)]


class GicModel:
    def __init__(self):
        self.events = []
        self.registers = {(0, 0): 1, (0, 4): 2, (1, 0): 1, (1, 12): 1023}
        self.reader = Read32(self.read)
        self.writer = Write32(lambda context, region, offset, value: self.events.append(("write", region, offset, value)))
        self.sync = Sync(lambda context: self.events.append(("sync",)))
        self.io = GicIo(None, self.reader, self.writer, self.sync)
        self.state = GicState()

    def read(self, context, region, offset):
        self.events.append(("read", region, offset))
        return self.registers.get((region, offset), 0)

    def writable(self):
        def write(context, region, offset, value):
            self.events.append(("write", region, offset, value))
            self.registers[region, offset] = value
        self.writer = Write32(write)
        self.io.write32 = self.writer


class TimerModel:
    def __init__(self, now=100):
        self.events = []
        self.now = now
        self.counter = Counter(self.read)
        self.control = Control(lambda context, value: self.events.append(("control", value)))
        self.compare = Compare(lambda context, value: self.events.append(("compare", value)))
        self.sync = Sync(lambda context: self.events.append(("sync",)))
        self.io = TimerIo(None, self.counter, self.control, self.compare, self.sync)

    def read(self, context):
        self.events.append(("counter",))
        return self.now


class EarlyIrqTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = ctypes.CDLL(LIBRARY)
        cls.library.mido_gic_attach.argtypes = [ctypes.POINTER(GicState), ctypes.POINTER(GicIo)]
        cls.library.mido_gic_take.argtypes = [ctypes.POINTER(GicState), ctypes.POINTER(ctypes.c_uint32)]
        cls.library.mido_gic_finish.argtypes = [ctypes.POINTER(GicState)]
        cls.library.mido_timer_arm_delta.argtypes = [ctypes.POINTER(TimerIo), ctypes.c_uint64]
        cls.library.mido_timer_stop.argtypes = [ctypes.POINTER(TimerIo)]
        cls.library.mido_gic_prepare_virtual_timer.argtypes = [ctypes.POINTER(GicState), ctypes.c_uint32]
        cls.library.mido_gic_dispatch_timer.argtypes = [ctypes.POINTER(GicState), ctypes.c_uint32, Sync, ctypes.c_void_p]
        cls.library.mido_gic_prepare_self_sgi.argtypes = [ctypes.POINTER(GicState)]
        cls.library.mido_gic_send_self_sgi.argtypes = [ctypes.POINTER(GicState)]
        cls.library.mido_gic_dispatch_timer_or_signal.argtypes = [ctypes.POINTER(GicState), Sync, Sync, ctypes.c_void_p]
        for name in ("mido_gic_attach", "mido_gic_take", "mido_gic_finish", "mido_timer_arm_delta", "mido_timer_stop"):
            getattr(cls.library, name).restype = ctypes.c_int

    def attached(self):
        model = GicModel()
        self.assertEqual(self.library.mido_gic_attach(ctypes.byref(model.state), ctypes.byref(model.io)), 0)
        model.events.clear()
        return model

    def test_prepare_timer_preserves_neighbour_priorities(self):
        model = self.attached()
        model.writable()
        model.registers[0, 0x80] = 1 << 27
        model.registers[0, 0x418] = 0x11223344
        self.assertEqual(self.library.mido_gic_prepare_virtual_timer(ctypes.byref(model.state), 27), 0)
        self.assertEqual(model.registers[0, 0x418], 0xa0223344)
        self.assertEqual(model.registers[0, 0x100], 1 << 27)
        self.assertEqual(model.registers[1, 4], 255)

    def test_self_sgi_preserves_priorities_and_targets_only_current_cpu(self):
        model = self.attached()
        model.writable()
        model.registers[0, 0x80] = (1 << 20) | 1
        model.registers[0, 0x400] = 0x11223344
        self.assertEqual(self.library.mido_gic_prepare_self_sgi(ctypes.byref(model.state)), 0)
        self.assertEqual(model.registers[0, 0x400], 0x11223380)
        self.assertEqual(self.library.mido_gic_send_self_sgi(ctypes.byref(model.state)), 0)
        self.assertEqual(model.registers[0, 0xf00], 2 << 24)
        self.assertFalse(any(event[:3] == ("write", 0, 0x80) for event in model.events))

    def test_self_sgi_rejects_secure_disabled_and_active_routes(self):
        for group, enabled, active in ((0, 1, 0), (1, 0, 0), (1, 1, 1)):
            model = self.attached()
            model.registers[0, 0x80] = group
            model.registers[0, 0x100] = enabled
            model.state.active = active
            self.assertNotEqual(self.library.mido_gic_send_self_sgi(ctypes.byref(model.state)), 0)
            self.assertFalse(any(event[0] == "write" for event in model.events))
        model = self.attached()
        self.assertEqual(self.library.mido_gic_prepare_self_sgi(ctypes.byref(model.state)), -3)
        self.assertFalse(any(event[0] == "write" for event in model.events))

    def test_self_sgi_requires_enable_readback(self):
        model = self.attached()
        model.registers[0, 0x80] = 1
        self.assertEqual(self.library.mido_gic_prepare_self_sgi(ctypes.byref(model.state)), -2)

    def test_signal_dispatch_eois_raw_token_before_native_handler(self):
        model = self.attached()
        token = 3 << 10
        model.registers[1, 12] = token
        timer = Sync(lambda context: model.events.append(("timer",)))
        signal = Sync(lambda context: model.events.append(("signal",)))
        self.assertEqual(self.library.mido_gic_dispatch_timer_or_signal(ctypes.byref(model.state), timer, signal, None), 0)
        self.assertNotIn(("timer",), model.events)
        self.assertLess(model.events.index(("write", 1, 16, token)), model.events.index(("signal",)))
        self.assertFalse(model.state.active)

    def test_dual_dispatch_retains_timer_order_and_rejects_unknown_ids(self):
        for identifier, expected in ((20, 0), (1, -3), (1023, 1)):
            model = self.attached()
            model.registers[1, 12] = identifier
            timer = Sync(lambda context: model.events.append(("timer",)))
            signal = Sync(lambda context: model.events.append(("signal",)))
            self.assertEqual(self.library.mido_gic_dispatch_timer_or_signal(ctypes.byref(model.state), timer, signal, None), expected)
            self.assertNotIn(("signal",), model.events)
            if identifier == 20:
                self.assertLess(model.events.index(("timer",)), model.events.index(("write", 1, 16, 20)))
            else:
                self.assertNotIn(("timer",), model.events)
                self.assertFalse(any(event[0] == "write" for event in model.events))

    def test_msm8953_timer_uses_saved_tree_ppi_twenty(self):
        model = self.attached()
        model.writable()
        model.registers[0, 0x80] = 1 << 20
        model.registers[0, 0x414] = 0x11223344
        self.assertEqual(self.library.mido_gic_prepare_virtual_timer(ctypes.byref(model.state), 20), 0)
        self.assertEqual(model.registers[0, 0x414], 0x112233a0)
        self.assertEqual(model.registers[0, 0x100], 1 << 20)
        model.registers[1, 12] = 20
        service = Sync(lambda context: model.events.append(("service",)))
        self.assertEqual(self.library.mido_gic_dispatch_timer(ctypes.byref(model.state), 20, service, None), 0)
        self.assertLess(model.events.index(("service",)), model.events.index(("write", 1, 16, 20)))

    def test_prepare_timer_refuses_secure_or_edge_route_without_writes(self):
        for group, configuration in ((0, 0), (1 << 27, 2 << 22)):
            model = self.attached()
            model.registers[0, 0x80] = group
            model.registers[0, 0xc04] = configuration
            self.assertEqual(self.library.mido_gic_prepare_virtual_timer(ctypes.byref(model.state), 27), -3)
            self.assertFalse(any(event[0] == "write" for event in model.events))

    def test_prepare_timer_requires_enable_readback(self):
        model = self.attached()
        model.registers[0, 0x80] = 1 << 27
        self.assertEqual(self.library.mido_gic_prepare_virtual_timer(ctypes.byref(model.state), 27), -2)

    def test_dispatch_services_timer_before_eoi(self):
        model = self.attached()
        model.registers[1, 12] = 27
        service = Sync(lambda context: model.events.append(("service",)))
        self.assertEqual(self.library.mido_gic_dispatch_timer(ctypes.byref(model.state), 27, service, None), 0)
        self.assertLess(model.events.index(("service",)), model.events.index(("write", 1, 16, 27)))
        self.assertFalse(model.state.active)

    def test_dispatch_unknown_interrupt_never_calls_service_or_eoi(self):
        model = self.attached()
        model.registers[1, 12] = 28
        service = Sync(lambda context: model.events.append(("service",)))
        self.assertEqual(self.library.mido_gic_dispatch_timer(ctypes.byref(model.state), 27, service, None), -3)
        self.assertNotIn(("service",), model.events)
        self.assertFalse(any(event[0] == "write" for event in model.events))
        self.assertTrue(model.state.active)

    def test_dispatch_spurious_never_calls_service_or_eoi(self):
        model = self.attached()
        service = Sync(lambda context: model.events.append(("service",)))
        self.assertEqual(self.library.mido_gic_dispatch_timer(ctypes.byref(model.state), 27, service, None), 1)
        self.assertNotIn(("service",), model.events)
        self.assertFalse(any(event[0] == "write" for event in model.events))

    def test_attach_reads_only(self):
        model = GicModel()
        self.assertEqual(self.library.mido_gic_attach(ctypes.byref(model.state), ctypes.byref(model.io)), 0)
        self.assertEqual(model.state.interrupt_count, 96)
        self.assertEqual(model.events, [("read", 0, 0), ("read", 1, 0), ("read", 0, 4)])

    def test_disabled_distributor(self):
        model = GicModel()
        model.registers[0, 0] = 0
        self.assertEqual(self.library.mido_gic_attach(ctypes.byref(model.state), ctypes.byref(model.io)), -2)
        self.assertEqual(model.events, [("read", 0, 0)])
        self.assertEqual(model.state.ready, 0)

    def test_disabled_cpu(self):
        model = GicModel()
        model.registers[1, 0] = 0
        self.assertEqual(self.library.mido_gic_attach(ctypes.byref(model.state), ctypes.byref(model.io)), -2)
        self.assertFalse(any(event[0] == "write" for event in model.events))

    def test_split_eoi_modes_rejected(self):
        for mode in (1 << 9, 1 << 10):
            model = GicModel()
            model.registers[1, 0] = mode | 1
            with self.subTest(mode=mode):
                self.assertEqual(self.library.mido_gic_attach(ctypes.byref(model.state), ctypes.byref(model.io)), -3)
                self.assertEqual(model.state.ready, 0)
                self.assertFalse(any(event[0] == "write" for event in model.events))

    def test_interrupt_count_is_bounded(self):
        for typer, expected in ((0, 32), (31, 1020), (0xFFFFFFFF, 1020)):
            model = GicModel()
            model.registers[0, 4] = typer
            self.assertEqual(self.library.mido_gic_attach(ctypes.byref(model.state), ctypes.byref(model.io)), 0)
            self.assertEqual(model.state.interrupt_count, expected)

    def test_sgi_eoi_preserves_raw_token(self):
        model = self.attached()
        token = (3 << 10) | 5
        model.registers[1, 12] = token
        identifier = ctypes.c_uint32(999)
        self.assertEqual(self.library.mido_gic_take(ctypes.byref(model.state), ctypes.byref(identifier)), 0)
        self.assertEqual(identifier.value, 5)
        self.assertEqual(model.state.active_iar, token)
        self.assertEqual(model.events, [("read", 1, 0), ("read", 1, 12), ("sync",)])
        model.events.clear()
        self.assertEqual(self.library.mido_gic_finish(ctypes.byref(model.state)), 0)
        self.assertEqual(model.events, [("read", 1, 0), ("sync",), ("write", 1, 16, token), ("sync",)])
        self.assertEqual(model.state.active, 0)

    def test_second_take_cannot_overwrite_active_token(self):
        model = self.attached()
        model.registers[1, 12] = 20
        identifier = ctypes.c_uint32()
        self.assertEqual(self.library.mido_gic_take(ctypes.byref(model.state), ctypes.byref(identifier)), 0)
        model.events.clear()
        self.assertEqual(self.library.mido_gic_take(ctypes.byref(model.state), ctypes.byref(identifier)), -4)
        self.assertEqual(model.events, [])
        self.assertEqual(model.state.active_iar, 20)

    def test_finish_without_active_irq_has_no_io(self):
        model = self.attached()
        self.assertEqual(self.library.mido_gic_finish(ctypes.byref(model.state)), -1)
        self.assertEqual(model.events, [])

    def test_all_special_ids_have_no_eoi(self):
        for special in range(1020, 1024):
            model = self.attached()
            model.registers[1, 12] = special
            identifier = ctypes.c_uint32(999)
            self.assertEqual(self.library.mido_gic_take(ctypes.byref(model.state), ctypes.byref(identifier)), 1)
            self.assertEqual(identifier.value, 999)
            self.assertEqual(model.state.active, 0)
            self.assertFalse(any(event[0] == "write" for event in model.events))

    def test_out_of_range_id_stops_further_acknowledgement(self):
        model = self.attached()
        model.registers[1, 12] = 100
        identifier = ctypes.c_uint32(999)
        self.assertEqual(self.library.mido_gic_take(ctypes.byref(model.state), ctypes.byref(identifier)), -5)
        self.assertEqual(identifier.value, 999)
        self.assertEqual(model.state.active, 1)
        self.assertEqual(self.library.mido_gic_finish(ctypes.byref(model.state)), -5)
        self.assertFalse(any(event[0] == "write" for event in model.events))

    def test_mode_change_before_finish_has_no_eoi(self):
        model = self.attached()
        model.registers[1, 12] = 20
        identifier = ctypes.c_uint32()
        self.assertEqual(self.library.mido_gic_take(ctypes.byref(model.state), ctypes.byref(identifier)), 0)
        model.registers[1, 0] = 513
        model.events.clear()
        self.assertEqual(self.library.mido_gic_finish(ctypes.byref(model.state)), -3)
        self.assertEqual(model.events, [("read", 1, 0)])
        self.assertEqual(model.state.active, 1)

    def test_unattached_state_has_no_io(self):
        model = GicModel()
        identifier = ctypes.c_uint32()
        self.assertEqual(self.library.mido_gic_take(ctypes.byref(model.state), ctypes.byref(identifier)), -2)
        self.assertEqual(model.events, [])

    def test_null_arguments(self):
        model = GicModel()
        self.assertEqual(self.library.mido_gic_attach(None, ctypes.byref(model.io)), -1)
        self.assertEqual(self.library.mido_gic_attach(ctypes.byref(model.state), None), -1)
        self.assertEqual(self.library.mido_gic_take(None, None), -1)
        self.assertEqual(self.library.mido_gic_finish(None), -1)
        self.assertEqual(self.library.mido_timer_arm_delta(None, 1), -1)
        self.assertEqual(self.library.mido_timer_stop(None), -1)
        self.assertEqual(model.events, [])

    def test_reattach_cannot_discard_pending_irq(self):
        model = self.attached()
        model.registers[1, 12] = 20
        identifier = ctypes.c_uint32()
        self.library.mido_gic_take(ctypes.byref(model.state), ctypes.byref(identifier))
        model.events.clear()
        self.assertEqual(self.library.mido_gic_attach(ctypes.byref(model.state), ctypes.byref(model.io)), -4)
        self.assertEqual(model.events, [])

    def test_timer_arm_sequence(self):
        model = TimerModel(100)
        self.assertEqual(self.library.mido_timer_arm_delta(ctypes.byref(model.io), 50), 0)
        self.assertEqual(model.events, [("counter",), ("control", 2), ("sync",), ("compare", 150), ("sync",), ("control", 1), ("sync",)])

    def test_timer_stop_is_disabled_and_masked(self):
        model = TimerModel()
        self.assertEqual(self.library.mido_timer_stop(ctypes.byref(model.io)), 0)
        self.assertEqual(model.events, [("control", 2), ("sync",)])

    def test_invalid_deltas_do_not_touch_timer(self):
        for delta in (0, 1 << 63, (1 << 64) - 1):
            model = TimerModel()
            self.assertEqual(self.library.mido_timer_arm_delta(ctypes.byref(model.io), delta), -1)
            self.assertEqual(model.events, [])

    def test_counter_overflow_reads_but_never_writes(self):
        model = TimerModel((1 << 64) - 10)
        self.assertEqual(self.library.mido_timer_arm_delta(ctypes.byref(model.io), 10), -1)
        self.assertEqual(model.events, [("counter",)])

    def test_last_nonwrapping_deadline(self):
        model = TimerModel((1 << 64) - 10)
        self.assertEqual(self.library.mido_timer_arm_delta(ctypes.byref(model.io), 9), 0)
        self.assertIn(("compare", (1 << 64) - 1), model.events)

    def test_missing_callbacks_rejected_before_io(self):
        for field, callback in (("read32", Read32), ("write32", Write32), ("synchronize", Sync)):
            model = GicModel()
            setattr(model.io, field, callback())
            with self.subTest(field=field):
                self.assertEqual(self.library.mido_gic_attach(ctypes.byref(model.state), ctypes.byref(model.io)), -1)
                self.assertEqual(model.events, [])
        for field, callback in (("read_counter", Counter), ("write_control", Control), ("write_compare", Compare), ("synchronize", Sync)):
            timer = TimerModel()
            setattr(timer.io, field, callback())
            with self.subTest(field=field):
                self.assertEqual(self.library.mido_timer_arm_delta(ctypes.byref(timer.io), 5), -1)
                self.assertEqual(self.library.mido_timer_stop(ctypes.byref(timer.io)), -1)
                self.assertEqual(timer.events, [])

    def test_mode_change_before_take_does_not_read_iar(self):
        model = self.attached()
        model.registers[1, 0] = 513
        identifier = ctypes.c_uint32(999)
        self.assertEqual(self.library.mido_gic_take(ctypes.byref(model.state), ctypes.byref(identifier)), -3)
        self.assertEqual(model.events, [("read", 1, 0)])
        self.assertEqual(identifier.value, 999)

    def test_failed_reattach_invalidates_ready_state(self):
        model = self.attached()
        model.registers[1, 0] = 0
        self.assertEqual(self.library.mido_gic_attach(ctypes.byref(model.state), ctypes.byref(model.io)), -2)
        self.assertEqual(model.state.ready, 0)
        model.events.clear()
        identifier = ctypes.c_uint32()
        self.assertEqual(self.library.mido_gic_take(ctypes.byref(model.state), ctypes.byref(identifier)), -2)
        self.assertEqual(model.events, [])

    def test_zero_interrupt_token_and_duplicate_finish(self):
        model = self.attached()
        model.registers[1, 12] = 0
        identifier = ctypes.c_uint32(999)
        self.assertEqual(self.library.mido_gic_take(ctypes.byref(model.state), ctypes.byref(identifier)), 0)
        self.assertEqual(identifier.value, 0)
        self.assertEqual(self.library.mido_gic_finish(ctypes.byref(model.state)), 0)
        self.assertIn(("write", 1, 16, 0), model.events)
        model.events.clear()
        self.assertEqual(self.library.mido_gic_finish(ctypes.byref(model.state)), -1)
        self.assertEqual(model.events, [])

    def test_modeled_timer_rearm_precedes_eoi(self):
        model = self.attached()
        timer = TimerModel()
        timer.events = model.events
        model.registers[1, 12] = 20
        identifier = ctypes.c_uint32()
        self.assertEqual(self.library.mido_gic_take(ctypes.byref(model.state), ctypes.byref(identifier)), 0)
        self.assertEqual(identifier.value, 20)
        self.assertEqual(self.library.mido_timer_arm_delta(ctypes.byref(timer.io), 19200), 0)
        self.assertEqual(self.library.mido_gic_finish(ctypes.byref(model.state)), 0)
        compare_index = model.events.index(("compare", 19300))
        eoi_index = model.events.index(("write", 1, 16, 20))
        self.assertLess(compare_index, eoi_index)
        self.assertEqual(model.state.active, 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--library", required=True)
    arguments = parser.parse_args()
    LIBRARY = arguments.library
    unittest.main(argv=[sys.argv[0], "-v"])
