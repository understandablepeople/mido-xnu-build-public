import unittest

from tools.model_mido_gicv2 import MidoGicV2


class GicMmioTests(unittest.TestCase):
    def test_self_sgi_is_explicit_and_target_is_current_cpu_only(self):
        with self.assertRaises(ValueError):
            MidoGicV2().write(0, 0xf00, 4, 2 << 24)
        model = MidoGicV2(self_sgi=True)
        with self.assertRaises(ValueError):
            model.write(0, 0xf00, 4, 2 << 24)
        model.write(0, 0x100, 4, 1)
        for value in (0, 1, 1 << 24, (2 << 24) | 1):
            with self.assertRaises(ValueError):
                model.write(0, 0xf00, 4, value)
        model.write(0, 0xf00, 4, 2 << 24)
        self.assertTrue(model.self_sgi_pending)
        self.assertIsNone(model.active_token)
        self.assertEqual(model.registers[1, 0x0c], 1023)

    def test_timer_mask_compare_and_signed_relative_deadline(self):
        model = MidoGicV2()
        model.timer_write(0, 1000, 10)
        self.assertEqual(model.timer_compare, 1010)
        model.timer_write(1, 1, 10)
        self.assertEqual(model.timer_read(1, 1000), 1)
        self.assertEqual(model.timer_read(1, 1010), 5)
        model.timer_write(1, 2, 1010)
        self.assertEqual(model.timer_read(1, 1010), 2)
        model.timer_write(0, 0xffffffff, 20)
        self.assertEqual(model.timer_compare, 19)
        self.assertEqual(model.timer_read(0, 20), 0xffffffff)
    def test_enable_is_write_one_set(self):
        model = MidoGicV2()
        model.registers[0, 0x100] = 1 << 19
        model.write(0, 0x100, 4, 1 << 20)
        self.assertEqual(model.read(0, 0x100, 4), (1 << 19) | (1 << 20))
        self.assertFalse(model.report()["irq_delivery_proven"])

    def test_unmodeled_registers_and_widths_fail(self):
        for region, offset, size in ((0, 0, 8), (1, 0x1000, 4), (0, 0x200, 4)):
            with self.subTest(region=region, offset=offset), self.assertRaises(ValueError):
                MidoGicV2().read(region, offset, size)
        with self.assertRaises(ValueError):
            MidoGicV2().write(0, 0, 4, 1)

    def test_timer_only_and_eoi_requires_active_token(self):
        model = MidoGicV2()
        with self.assertRaises(ValueError):
            model.write(0, 0x100, 4, 1 << 28)
        with self.assertRaises(ValueError):
            model.write(1, 0x10, 4, 27)
        model.registers[1, 0x0c] = 27
        self.assertEqual(model.read(1, 0x0c, 4), 27)
        self.assertEqual(model.read(1, 0x0c, 4), 1023)
        with self.assertRaises(ValueError):
            model.write(1, 0x10, 4, 28)
        model.write(1, 0x10, 4, 27)
        self.assertIsNone(model.active_token)


if __name__ == "__main__":
    unittest.main()
