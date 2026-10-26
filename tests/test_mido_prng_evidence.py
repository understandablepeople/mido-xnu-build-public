import hashlib
from pathlib import Path
import tempfile
import unittest

from tools.test_mido_prng_bridge import input_hashes, require_unchanged_inputs


class InputEvidenceTests(unittest.TestCase):
    def test_unchanged_inputs_match_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.c"
            source.write_bytes(b"original")
            expected = input_hashes(root, [source])
            self.assertEqual(expected, {"source.c": hashlib.sha256(b"original").hexdigest()})
            require_unchanged_inputs(root, expected)

    def test_source_header_or_harness_drift_is_not_certified(self):
        for name in ("source.c", "header.h", "harness.py"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / name
                path.write_bytes(b"compiled version")
                expected = input_hashes(root, [path])
                path.write_bytes(b"edited version")
                with self.assertRaisesRegex(ValueError, "changed during execution"):
                    require_unchanged_inputs(root, expected)

    def test_deleted_input_is_not_certified(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.c"
            source.write_bytes(b"original")
            expected = input_hashes(root, [source])
            source.unlink()
            with self.assertRaisesRegex(ValueError, "changed during execution"):
                require_unchanged_inputs(root, expected)
