import random
import struct
import unittest

from tools.mido_vm_reference_spans import encode, decode
from tests import test_mido_vm_executable_reference as executable_tests


class ReferenceSpanTests(unittest.TestCase):
    def test_sparse_and_wrapping_words_roundtrip(self):
        for words in ([], [0]*100, [1], [0, 7, 7, 7, 0],
                      [0xffffffffffffffff, 1, 3, 0, 9, 13, 17], list(range(4096))):
            self.assertEqual(decode(encode(words), len(words)), words)

    def test_random_words_roundtrip(self):
        randomizer = random.Random(8953)
        words = [randomizer.getrandbits(64) if randomizer.randrange(3) else 0 for _ in range(4096)]
        self.assertEqual(decode(encode(words), len(words)), words)

    def test_invalid_spans_rejected(self):
        for spans in ([dict(start=0,count=0,value=1,step=0)],
                      [dict(start=9,count=2,value=1,step=0)],
                      [dict(start=2,count=3,value=1,step=0),dict(start=4,count=1,value=2,step=0)]):
            with self.assertRaisesRegex(ValueError, "Invalid"):
                decode(spans, 10)

    def test_actual_seven_page_reference_is_exact_and_compact(self):
        reference = executable_tests.ExecutableReferenceTests().reference()
        expected = reference.expected("vm-data-mapped")
        words = list(struct.unpack(f"<{len(expected)//8}Q", expected))
        spans = encode(words)
        self.assertEqual(decode(spans, len(words)), words)
        self.assertLess(len(spans)*24, 4096)


if __name__ == "__main__":
    unittest.main()
