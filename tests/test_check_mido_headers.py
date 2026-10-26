from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.check_mido_headers import ESSENTIAL_SOURCES, SOURCE_HASHES, validate_sources, verify_generated


def populate(directory, config="DEVELOPMENT"):
    for name, value in (("mach_assert", 1), ("mach_ldebug", int(config == "DEBUG")),
                        ("mach_vm_debug", int(config == "DEBUG")), ("debug", int(config == "DEBUG")),
                        ("importance_inheritance", 1), ("config_dtrace", 1), ("mach_kdp", 1)):
        (directory / f"{name}.h").write_text(f"#define {name.upper()} {value}\n", encoding="utf-8")
    (directory / "Makefile").write_text("export CONFIG_DEFINES = -DCONFIG_PMAP_PPL\n"
                                        + "\n".join(f"$(SOURCE_DIR)/{path}" for path in ESSENTIAL_SOURCES), encoding="utf-8")


class MidoHeadersTests(unittest.TestCase):
    def test_link_dependency_headers_cannot_be_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in ("config_dtrace", "mach_kdp"):
                populate(directory)
                (directory / f"{name}.h").write_text(f"#define {name.upper()} 0\n", encoding="utf-8")
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                    verify_generated(directory, "DEVELOPMENT")

    def test_both_generated_variants(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for config in ("DEVELOPMENT", "DEBUG"):
                populate(directory, config)
                hashes = verify_generated(directory, config)
                self.assertEqual(len(hashes), 8)
                self.assertTrue(all(len(value) == 64 for value in hashes.values()))

    def test_debug_headers_cannot_pass_as_development(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            populate(directory, "DEBUG")
            with self.assertRaisesRegex(ValueError, "header"):
                verify_generated(directory, "DEVELOPMENT")

    def test_assertions_must_be_enabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            populate(directory)
            (directory / "mach_assert.h").write_text("#define MACH_ASSERT 0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "header"):
                verify_generated(directory, "DEVELOPMENT")

    def test_importance_inheritance_cannot_be_missing_or_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            populate(directory)
            (directory / "importance_inheritance.h").write_text("#define IMPORTANCE_INHERITANCE 0\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "importance_inheritance"):
                verify_generated(directory, "DEVELOPMENT")

    def test_missing_each_core_source_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for source in ESSENTIAL_SOURCES:
                populate(directory)
                makefile = directory / "Makefile"
                makefile.write_text(makefile.read_text().replace(f"$(SOURCE_DIR)/{source}", ""), encoding="utf-8")
                with self.subTest(source=source), self.assertRaisesRegex(ValueError, "core entry/pmap"):
                    verify_generated(directory, "DEVELOPMENT")

    def test_missing_pmap_option_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            populate(directory)
            makefile = directory / "Makefile"
            makefile.write_text(makefile.read_text().replace("-DCONFIG_PMAP_PPL", ""), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pmap implementation"):
                verify_generated(directory, "DEVELOPMENT")

    def test_unknown_variant_rejected(self):
        with self.assertRaisesRegex(ValueError, "unsupported"):
            verify_generated(Path("unused"), "RELEASE")

    def test_zero_pmap_option_is_not_enabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            populate(directory)
            makefile = directory / "Makefile"
            makefile.write_text(makefile.read_text().replace("-DCONFIG_PMAP_PPL", "-DCONFIG_PMAP_PPL=0"), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "pmap implementation"):
                verify_generated(directory, "DEVELOPMENT")

    def test_source_set_is_exact(self):
        with self.assertRaisesRegex(ValueError, "source set"):
            validate_sources({})

    def test_source_modification_rejected(self):
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            validate_sources(dict.fromkeys(SOURCE_HASHES, b"modified"))

    def test_source_hashes_accepted(self):
        with patch("tools.check_mido_headers.hashlib.sha256") as checksum:
            checksum.return_value.hexdigest.side_effect = SOURCE_HASHES.values()
            validate_sources(dict.fromkeys(SOURCE_HASHES, b"fixture"))


if __name__ == "__main__":
    unittest.main()
