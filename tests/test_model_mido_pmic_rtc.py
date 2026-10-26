import unittest

from tools.model_mido_pmic_rtc import MidoPmicRtc


class PmicModelTests(unittest.TestCase):
    def test_explicit_seconds_advance_only_with_counter(self):
        ticks = [100]
        model = MidoPmicRtc(65478350, lambda: ticks[0])
        command = (1 << 27) | (0x48 << 4) | 3
        model.write(1, 17 * 0x8000, 4, command)
        self.assertEqual(model.read(1, 17 * 0x8000 + 0x18, 4), 65478350)
        ticks[0] += 2 * 19200000
        model.write(1, 17 * 0x8000, 4, command)
        self.assertEqual(model.read(1, 17 * 0x8000 + 0x18, 4), 65478352)
        self.assertFalse(model.report()["hardware_verified"])

    def test_apid_mapping_is_explicit_not_assumed_by_reader(self):
        model = MidoPmicRtc(0, lambda: 0, apid=203)
        self.assertEqual(model.read(0, 0, 4), 0x20010000)
        self.assertEqual(model.read(0, 0x800 + 203 * 4, 4), 0x6000)
        self.assertEqual(model.read(0, 0x800 + 17 * 4, 4), 0)

    def test_writes_unknown_registers_and_widths_are_rejected(self):
        model = MidoPmicRtc(0, lambda: 0)
        for request in ((0, 0, 4, 1), (1, 0, 4, 1), (1, 17 * 0x8000, 4, 0),
                        (1, 17 * 0x8000, 8, 1 << 27), (1, 17 * 0x8000, 4, (1 << 27) | (0x40 << 4))):
            with self.assertRaises(ValueError):
                model.write(*request)
        for request in ((0, 4, 4), (0, 0, 8), (1, 17 * 0x8000 + 0x18, 4)):
            with self.assertRaises(ValueError):
                model.read(*request)

    def test_invalid_inputs_are_not_replaced_with_host_date(self):
        for seconds in (None, -1, 1 << 32):
            with self.assertRaises(ValueError):
                MidoPmicRtc(seconds, lambda: 0)
