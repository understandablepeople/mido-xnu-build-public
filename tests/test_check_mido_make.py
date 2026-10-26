from copy import deepcopy
import unittest
from unittest.mock import patch

from tools.check_mido_make import (
    PREFIX, SOURCE_HASHES, VARIABLES, parse_values, platform_definitions,
    validate_sources, validate_values,
)


def fixture(config="DEVELOPMENT", platform="MacOSX"):
    memory = "-DARM_LARGE_MEMORY=1" if platform == "MacOSX" else "-UARM_LARGE_MEMORY"
    link = "0xfffffe0007004000" if platform == "MacOSX" else "0xfffffff007004000"
    machine = "-DARM64_BOARD_CONFIG_MIDO -mcpu=cortex-a53 -march=armv8-a -mstrict-align"
    flags = f"{machine} -arch arm64 {memory} -DVM_KERNEL_LINK_ADDRESS={link}"
    prefix = "kernel" if platform == "MacOSX" else "mach"
    return dict(zip(VARIABLES, ("MIDO BCM2837", "arm64", "-arch arm64", machine, flags, flags,
                               f"{prefix}.{config.lower()}.mido", memory, link, "1")))


class MidoMakeTests(unittest.TestCase):
    def test_four_platform_variant_combinations(self):
        for config in ("DEVELOPMENT", "DEBUG"):
            for platform in ("MacOSX", "iPhoneOS"):
                self.assertTrue(validate_values(fixture(config, platform), config, platform)["platform_memory_review_required"])

    def test_probe_output_roundtrip(self):
        values = fixture()
        text = "ordinary make output\n" + "\n".join(f"{PREFIX}{name}={value}" for name, value in values.items())
        self.assertEqual(parse_values(text), values)

    def test_missing_duplicate_unknown_output(self):
        for text in ("", f"{PREFIX}CFLAGS=first\n{PREFIX}CFLAGS=second", f"{PREFIX}other=value", f"{PREFIX}CFLAGS"):
            with self.assertRaises(ValueError):
                parse_values(text)

    def test_unsupported_scenarios(self):
        for config, platform in (("RELEASE", "MacOSX"), ("DEBUG", "DriverKit")):
            with self.assertRaisesRegex(ValueError, "unsupported"):
                validate_values(fixture(), config, platform)

    def test_arm64e_and_missing_registration(self):
        for name, value in (("ARCH_FLAGS_ARM64", "-arch arm64e"),
                            ("ARCH_STRING_FOR_CURRENT_MACHINE_CONFIG", "arm64e"),
                            ("SUPPORTED_ARM64_MACHINE_CONFIGS", "BCM2837")):
            values = fixture()
            values[name] = value
            with self.assertRaises(ValueError):
                validate_values(values, "DEVELOPMENT", "MacOSX")

    def test_changed_machine_baseline(self):
        values = fixture()
        values["MACHINE_FLAGS_ARM64_MIDO"] = "-mcpu=apple-a14"
        with self.assertRaisesRegex(ValueError, "machine flags"):
            validate_values(values, "DEVELOPMENT", "MacOSX")

    def test_missing_duplicate_or_conflicting_flags(self):
        for variable in ("CFLAGS", "SFLAGS"):
            for change in (lambda flags: flags.replace("-mstrict-align", ""),
                           lambda flags: flags + " -mcpu=cortex-a53",
                           lambda flags: flags + " -mcpu=apple-a14",
                           lambda flags: flags + " -march=armv8.5-a",
                           lambda flags: flags + " -DARM64_BOARD_CONFIG_T8103",
                           lambda flags: flags + " -arch arm64e"):
                values = fixture()
                values[variable] = change(values[variable])
                with self.subTest(variable=variable), self.assertRaises(ValueError):
                    validate_values(values, "DEVELOPMENT", "MacOSX")

    def test_unreviewed_page_and_branch_protection(self):
        for flag in ("-D__ARM_16K_PG__", "-D__ARM_16K_PG__=0", "-D__ARM_16K_PG__=1", "-mbranch-protection=standard"):
            values = fixture()
            values["CFLAGS"] += " " + flag
            with self.assertRaises(ValueError):
                validate_values(values, "DEVELOPMENT", "MacOSX")

    def test_memory_link_name_and_static_path(self):
        values = fixture()
        for name, value in (("ARM64_LINK_ADDR", "0"), ("LARGE_MEMORY_DEFINE", "-UARM_LARGE_MEMORY"),
                            ("BUILD_STATIC_LINK", "0"), ("KERNEL_FILE_NAME", "mach.development.mido")):
            changed = deepcopy(values)
            changed[name] = value
            with self.assertRaises(ValueError):
                validate_values(changed, "DEVELOPMENT", "MacOSX")

    def test_platform_definitions_exactly_once(self):
        text = "SUPPORTED_EMBEDDED_PLATFORMS := iPhoneOS\nSUPPORTED_SIMULATOR_PLATFORMS := iPhoneSimulator\nSUPPORTED_PLATFORMS := MacOSX $(SUPPORTED_EMBEDDED_PLATFORMS)\n"
        self.assertEqual(platform_definitions(text), text)
        for malformed in ("", text * 2):
            with self.assertRaisesRegex(ValueError, "definitions"):
                platform_definitions(malformed)

    def test_source_set_and_hash_guards(self):
        for sources in ({}, dict.fromkeys(SOURCE_HASHES, b"changed")):
            with self.assertRaises(ValueError):
                validate_sources(sources)

    def test_matching_hashes(self):
        with patch("tools.check_mido_make.hashlib.sha256") as checksum:
            checksum.return_value.hexdigest.side_effect = SOURCE_HASHES.values()
            validate_sources(dict.fromkeys(SOURCE_HASHES, b"fixture"))


if __name__ == "__main__":
    unittest.main()
