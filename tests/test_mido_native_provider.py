from pathlib import Path
import io
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools.check_mido_native_provider import command_for, inspect, is_arm64_object_header, main


class NativeProviderCommandTests(unittest.TestCase):
    def test_object_header_requires_plain_arm64_not_arm64e(self):
        header = struct.pack("<8I", 0xfeedfacf, 0x0100000c, 0, 1, 0, 0, 0, 0)
        self.assertTrue(is_arm64_object_header(header))
        for subtype in (1, 2, 0x80000002):
            changed = bytearray(header)
            struct.pack_into("<I", changed, 8, subtype)
            self.assertFalse(is_arm64_object_header(changed))
        self.assertFalse(is_arm64_object_header(header[:31]))
        changed = bytearray(header)
        struct.pack_into("<I", changed, 12, 2)
        self.assertFalse(is_arm64_object_header(changed))

    def test_actual_kernel_and_darwin_target(self):
        command = command_for(Path("workspace"), Path("clang"), "mido_sha256.c")
        for flag in ("--target=arm64-apple-ios16.6", "-DKERNEL=1", "-DXNU_KERNEL_PRIVATE=1",
                     "-mgeneral-regs-only", "-Werror", "-fsyntax-only"):
            self.assertIn(flag, command)
        self.assertFalse(any("android" in item for item in command))

    def test_bootstrap_provider_has_explicit_diagnostic_opt_in(self):
        command = command_for(Path("workspace"), Path("clang"), "mido_boot_crypto.c")
        self.assertIn("-DMIDO_BOOT_CRYPTO_DIAGNOSTIC=1", command)
        self.assertIn("-DKERNEL=1", command)
        ordinary = command_for(Path("workspace"), Path("clang"), "mido_prng_bridge.c")
        self.assertNotIn("-DMIDO_BOOT_CRYPTO_DIAGNOSTIC=1", ordinary)

    def test_sdk_is_explicit_not_fabricated(self):
        command = command_for(Path("workspace"), Path("clang"), "mido_prng_bridge.c", Path("sdk"))
        self.assertEqual(command[command.index("-isysroot") + 1], str(Path("sdk")))

    def test_dependency_failure_stops_before_compiler_or_output_creation(self):
        with patch("tools.check_mido_native_provider.verify_dependency", side_effect=ValueError("Modified dependency")) as verify, \
                patch("tools.check_mido_native_provider.subprocess.run") as compiler:
            with self.assertRaisesRegex(ValueError, "Modified dependency"):
                inspect(Path("workspace"), Path("clang"), None, compile_directory=Path("objects"))
            verify.assert_called_once_with(Path("workspace/artifacts/bearssl-0.6.tar.gz"),
                                           Path("workspace/artifacts/bearssl-0.6"))
            compiler.assert_not_called()

    def test_no_implicit_sdk(self):
        command = command_for(Path("workspace"), Path("clang"), "mido_kmem_random.c")
        self.assertNotIn("-isysroot", command)

    def test_reject_unknown_unit(self):
        with self.assertRaisesRegex(ValueError, "Unknown"):
            command_for(Path("workspace"), Path("clang"), "foreign.c")

    def test_aes_adapters_and_bitsliced_dependencies_are_audited(self):
        for name in ("mido_aes_cbc.c", "mido_aes_ctr.c", "mido_aes_xts.c", "mido_aes_gcm.c", "mido_ccrng.c", "aes_ct.c", "aes_ct_enc.c",
                     "aes_ct_dec.c", "aes_ct_cbcenc.c", "aes_ct_cbcdec.c", "aes_ct_ctr.c", "gcm.c", "ghash_ctmul32.c"):
            command = command_for(Path("workspace"), Path("clang"), name, object_output=Path(name + ".o"))
            self.assertIn("-mgeneral-regs-only", command)
            self.assertIn("-Werror", command)
            self.assertIn("-c", command)
            self.assertTrue(any(Path(item).name == name for item in command))

    def test_actual_export_and_configuration_include_paths(self):
        command = command_for(Path("workspace"), Path("clang"), "mido_sha256.c",
                              source_root=Path("source"), object_root=Path("objects"))
        self.assertIn(str(Path("objects/EXPORT_HDRS/osfmk")), command)
        self.assertIn(str(Path("objects/DEVELOPMENT_ARM64_MIDO/osfmk/DEVELOPMENT")), command)
        self.assertIn(str(Path("source/EXTERNAL_HEADERS")), command)
        self.assertIn(str(Path("source/pexpert")), command)

    def test_cli_forwards_source_and_object_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "report.json"
            arguments = ["audit", "--compiler", "clang", "--sdk-root", directory,
                         "--source-root", "source", "--object-root", "objects", "--output", str(output)]
            with patch("sys.argv", arguments), patch("sys.stdout", new_callable=io.StringIO), \
                    patch("tools.check_mido_native_provider.inspect", return_value={"blockers": []}) as inspect:
                self.assertEqual(main(), 0)
            self.assertEqual(inspect.call_args.args[3:5], (Path("source").resolve(), Path("objects").resolve()))
            self.assertTrue(output.is_file())

    def test_compile_mode_produces_real_target_object_command(self):
        command = command_for(Path("workspace"), Path("clang"), "hmac_drbg.c", object_output=Path("object.o"))
        self.assertNotIn("-fsyntax-only", command)
        self.assertIn("-c", command)
        self.assertEqual(command[command.index("-o") + 1], "object.o")
        self.assertIn(str(Path("workspace/artifacts/bearssl-0.6/src/rand/hmac_drbg.c")), command)


if __name__ == "__main__":
    unittest.main()
