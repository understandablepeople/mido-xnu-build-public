import hashlib
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from audit_dyld_signature import audit


def make_cache(path):
    data = bytearray(32768)
    data[:16] = b'dyld_v1  arm64  '
    directory = bytearray(44 + 64)
    signature_size = 20 + len(directory)
    struct.pack_into('<QQ', data, 40, len(data), signature_size)
    struct.pack_into('>9I', directory, 0, 0xfade0c02, len(directory),
                     0x20000, 0, 44, 0, 0, 2, len(data))
    struct.pack_into('4B', directory, 36, 32, 2, 0, 14)
    for index in range(2):
        directory[44 + index * 32:76 + index * 32] = hashlib.sha256(
            data[index * 16384:(index + 1) * 16384]).digest()
    signature = struct.pack('>5I', 0xfade0cc0, signature_size, 1, 0, 20) + directory
    path.write_bytes(data + signature)


class SignatureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / 'cache'
        make_cache(self.path)

    def test_valid(self):
        result = audit(self.path)['directories'][0]
        self.assertEqual(result['checked'], 2)
        self.assertEqual(result['failures'], [])

    def test_modified_block(self):
        with self.path.open('r+b') as target:
            target.seek(17000)
            target.write(b'bad')
        result = audit(self.path)['directories'][0]
        self.assertEqual([failure['offset'] for failure in result['failures']], [16384])

    def test_range(self):
        result = audit(self.path, 16384, 32768)['directories'][0]
        self.assertEqual(result['checked'], 1)
        self.assertEqual(result['failures'], [])

    def test_truncated_signature(self):
        self.path.write_bytes(self.path.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, 'signature outside file'):
            audit(self.path)

    def test_bad_superblob(self):
        with self.path.open('r+b') as target:
            target.seek(32768)
            target.write(b'bad!')
        with self.assertRaisesRegex(ValueError, 'invalid signature superblob'):
            audit(self.path)


if __name__ == '__main__':
    unittest.main()
