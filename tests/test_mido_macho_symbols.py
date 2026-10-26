import struct
import unittest
from unittest.mock import patch

from tools.mido_macho_symbols import macho_symbols


class MachoSymbolTests(unittest.TestCase):
    def fixture(self, name=1, kind=0x0f, section=1, count=1):
        strings = b"\0_symbol\0"
        return (bytes(32) + struct.pack("<6I", 2, 24, 56, count, 72, len(strings))
                + struct.pack("<IBBHQ", name, kind, section, 0, 0x1000) + strings)

    @patch("tools.mido_macho_symbols.inspect", return_value=dict(commands=["symtab"]))
    def test_only_defined_section_symbols_are_returned(self, inspection):
        self.assertEqual(macho_symbols(self.fixture()), {"_symbol": 0x1000})
        self.assertEqual(macho_symbols(self.fixture(section=0)), {})
        self.assertEqual(macho_symbols(self.fixture(kind=0xe0)), {})

    @patch("tools.mido_macho_symbols.inspect", return_value=dict(commands=["symtab"]))
    def test_truncation_and_invalid_strings_are_rejected(self, inspection):
        for blob in (self.fixture()[:-1], self.fixture(name=100), self.fixture(count=1_000_001)):
            with self.assertRaises(ValueError):
                macho_symbols(blob)

    @patch("tools.mido_macho_symbols.inspect", return_value=dict(commands=[]))
    def test_missing_symbol_table_is_not_silent_success(self, inspection):
        with self.assertRaises(ValueError):
            macho_symbols(bytes(32))
