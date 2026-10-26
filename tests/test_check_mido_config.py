import unittest
from unittest.mock import patch

from tools.check_mido_config import machine_flags, SOURCE_HASHES, validate_sources


FLAGS = "MACHINE_FLAGS_ARM64_MIDO = -DARM64_BOARD_CONFIG_MIDO -mcpu=cortex-a53 -march=armv8-a -mstrict-align\n"


class MidoConfigTests(unittest.TestCase):
    def test_exact_baseline_flags(self):
        self.assertEqual(machine_flags(FLAGS), ["-DARM64_BOARD_CONFIG_MIDO", "-mcpu=cortex-a53", "-march=armv8-a", "-mstrict-align"])

    def test_missing_duplicate_or_foreign_flags(self):
        for text in ("", FLAGS * 2, FLAGS.replace("armv8-a", "armv8.2-a"), FLAGS.replace("MIDO", "BCM2837"), FLAGS.replace(" -mstrict-align", "")):
            with self.subTest(text=text), self.assertRaises(ValueError):
                machine_flags(text)

    def test_source_file_set_is_exact(self):
        for sources in ({}, {"other": b""}, {**dict.fromkeys(SOURCE_HASHES, b""), "extra": b""}):
            with self.assertRaisesRegex(ValueError, "file set"):
                validate_sources(sources)

    def test_source_hashes_are_required(self):
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_sources(dict.fromkeys(SOURCE_HASHES, b"modified"))

    def test_all_matching_hashes_accepted(self):
        with patch("tools.check_mido_config.hashlib.sha256") as checksum:
            checksum.return_value.hexdigest.side_effect = SOURCE_HASHES.values()
            validate_sources(dict.fromkeys(SOURCE_HASHES, b"test"))
            self.assertEqual(checksum.call_count, 3)


if __name__ == "__main__":
    unittest.main()
