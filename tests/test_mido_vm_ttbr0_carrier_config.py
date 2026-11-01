from copy import deepcopy
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.mido_vm_physmap_carrier_config import configure_physmap_carrier
from tools.mido_vm_transition_island import transition_island
from tools.mido_vm_ttbr0_carrier_config import (
    ISLAND_SHA256, LABEL_OFFSETS, MAGIC, PAYLOAD_BYTES, RECORD, SOURCE,
    SOURCE_SHA256, build_island, configure_ttbr0_carrier)
from tools.mido_vm_ttbr0_dependencies import audit


MODULE = "tools.mido_vm_ttbr0_carrier_config"


class TTBR0CarrierConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        kernel = Path(os.environ.get("MIDO_NATIVE4K_KERNEL", root /
            "artifacts/mido-native-4k-cloud-full-v1/mach.development.mido"))
        cls.toolchain = Path(os.environ.get("MIDO_NDK_TOOLCHAIN", Path.home() /
            "AppData/Local/Android/Sdk/ndk/28.2.13676358/toolchains/llvm/prebuilt/windows-x86_64/bin"))
        if not kernel.exists():
            raise unittest.SkipTest("Pinned native-4K kernel unavailable")
        if not (cls.toolchain / "clang.exe").exists():
            raise unittest.SkipTest("Android NDK unavailable")
        cls.kernel = kernel.read_bytes()
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.payload, cls.symbols = build_island(cls.kernel, cls.toolchain,
                                              Path(cls.temporary.name) / "island")
        review = {"values": {"MIDO_EARLY_VIRT_BASE": 0xfffffff007000000,
                             "MIDO_EARLY_STOP_PA": 0},
                  "post_c_definitions": {"MIDO_C_RECORD": 0x12400800,
                                         "MIDO_C_RETURN_LITERAL": 0x850},
                  "vm_dynamic": True, "boot_approved": False}
        cls.header, cls.review = configure_physmap_carrier(cls.kernel,
            "#define UNRELATED 7\n#define MIDO_C_OBSERVER 0x12400000ULL\n", review)

    def configure(self, header=None, review=None, payload=None, symbols=None):
        return configure_ttbr0_carrier(self.kernel,
            self.header if header is None else header,
            self.review if review is None else review,
            self.payload if payload is None else payload,
            self.symbols if symbols is None else symbols)

    def test_actual_ndk_payload_hash_size_and_all_labels(self):
        island = transition_island(self.kernel)["candidate"]
        self.assertEqual(hashlib.sha256(SOURCE.read_bytes()).hexdigest(), SOURCE_SHA256)
        self.assertEqual(hashlib.sha256(self.payload).hexdigest(), ISLAND_SHA256)
        self.assertEqual(len(self.payload), PAYLOAD_BYTES)
        self.assertEqual(PAYLOAD_BYTES, 236)
        self.assertLessEqual(len(self.payload), island["budget"])
        self.assertEqual(island["budget"], 256)
        expected = {"mido_ttbr0_return" + suffix: island["va"] + offset
                    for suffix, offset in LABEL_OFFSETS.items()}
        expected.update(mido_ttbr0_return_record=RECORD, mido_ttbr0_return_magic=MAGIC)
        self.assertEqual(self.symbols, expected)
        self.assertEqual(self.kernel[island["fileoff"]:island["fileoff"] + 256], bytes(256))

    def test_stop_magic_x0_and_ten_word_record(self):
        header, review = self.configure()
        self.assertEqual(review["stop_va"], 0xfffffff007446a54)
        self.assertEqual(review["original_stop_word"], 0xf9400aa0)
        self.assertEqual(review["ttbr1_record"], dict(physical=RECORD, words=10, magic=MAGIC))
        expected = {"MIDO_VM_TTBR0_ROUNDTRIP": 1, "MIDO_VM_TTBR1_ROUNDTRIP": 1,
                    "MIDO_NATIVE_STOP_WORD": 0xf9400aa0, "MIDO_C_EXPECTED_X0": 0x12401000,
                    "MIDO_EARLY_STOP_PA": 0x11646a54, "MIDO_TTBR1_RECORD": RECORD,
                    "MIDO_TTBR1_MAGIC": 0x3130305445523054, "MIDO_TTBR1_RECORD_WORDS": 10,
                    "MIDO_TTBR1_ISLAND_SIZE": 236}
        for name, value in expected.items():
            self.assertEqual(review["post_c_definitions"][name], value)
            self.assertIn(f"#define {name} 0x{value:x}ULL\n", header)
        self.assertTrue(review["vm_ttbr0_roundtrip"])
        self.assertTrue(review["vm_ttbr1_roundtrip"])
        self.assertTrue(review["ttbr0_changed"])
        for name in ("full_activation", "hardware_execution_proven", "boot_approved"):
            self.assertFalse(review[name])
        self.assertIn("Both original TTBR setters", review["scope"])
        self.assertEqual(review["ttbr1_island"]["symbols"], self.symbols)

    def test_dependency_audit_all_three_geometries(self):
        with patch(MODULE + ".audit", wraps=audit) as dependency:
            _, review = self.configure()
        dependency.assert_called_once_with(self.kernel)
        report = review["ttbr0_dependencies"]
        self.assertTrue(report["passed"])
        self.assertEqual([(case["l2_count"], case["slide"]) for case in report["cases"].values()],
                         [(1, 0), (2, 0x3ffff000), (1, 0x37000000)])

    def test_dependency_failure_propagates(self):
        with patch(MODULE + ".audit", side_effect=ValueError("dependency failed")):
            with self.assertRaisesRegex(ValueError, "dependency failed"):
                self.configure()
        with patch(MODULE + ".audit", return_value={"passed": False}):
            with self.assertRaisesRegex(ValueError, "audit failed"):
                self.configure()

    def test_explicit_complete_dynamic_prefix_required(self):
        for flag in ("vm_dynamic", "vm_physmap_complete"):
            for value in (None, False, 1, "yes"):
                candidate = deepcopy(self.review)
                if value is None:
                    candidate.pop(flag)
                else:
                    candidate[flag] = value
                with self.subTest(flag=flag, value=value), self.assertRaisesRegex(ValueError, "explicit complete"):
                    self.configure(review=candidate)
        with self.assertRaises(ValueError):
            self.configure(review={})

    def test_ttbr1_only_configuration_is_not_input(self):
        candidate = deepcopy(self.review)
        candidate["vm_ttbr1_roundtrip"] = True
        with self.assertRaisesRegex(ValueError, "not TTBR1 config"):
            self.configure(review=candidate)

    def test_mutated_truncated_and_oversize_payload_rejected(self):
        candidates = [self.payload[:-4], self.payload + bytes(24)]
        for offset in (0, 0x58, 0xb4, 235):
            candidate = bytearray(self.payload)
            candidate[offset] ^= 1
            candidates.append(bytes(candidate))
        for candidate in candidates:
            with self.subTest(size=len(candidate)), self.assertRaisesRegex(ValueError, "payload/layout"):
                self.configure(payload=candidate)

    def test_each_label_mutation_and_missing_label_rejected(self):
        for name in self.symbols:
            for missing in (False, True):
                candidate = dict(self.symbols)
                if missing:
                    candidate.pop(name)
                else:
                    candidate[name] += 4
                with self.subTest(name=name, missing=missing), self.assertRaises(ValueError):
                    self.configure(symbols=candidate)
        with self.assertRaises(ValueError):
            self.configure(symbols=dict(self.symbols, mido_ttbr0_return_extra=0))

    def test_source_hash_required_by_build_and_configure(self):
        with patch.object(Path, "read_bytes", return_value=b"unreviewed source"):
            with self.assertRaisesRegex(ValueError, "source differs"):
                self.configure()
            with self.assertRaisesRegex(ValueError, "source differs"):
                build_island(self.kernel, self.toolchain, Path(self.temporary.name) / "bad-source")

    def test_unknown_kernel_and_missing_padding_rejected(self):
        with self.assertRaises(ValueError):
            configure_ttbr0_carrier(b"unknown", self.header, self.review, self.payload, self.symbols)
        with patch(MODULE + ".transition_island", return_value={"found": False}):
            with self.assertRaisesRegex(ValueError, "padding"):
                self.configure()
            with self.assertRaisesRegex(ValueError, "padding"):
                build_island(self.kernel, self.toolchain, Path(self.temporary.name) / "no-padding")

    def test_build_rejects_unreviewed_compiler_payload(self):
        read_bytes = Path.read_bytes

        def corrupted_binary(path):
            result = read_bytes(path)
            if path.name == "return.bin":
                return bytes([result[0] ^ 1]) + result[1:]
            return result

        with patch.object(Path, "read_bytes", corrupted_binary):
            with self.assertRaisesRegex(ValueError, "payload/layout"):
                build_island(self.kernel, self.toolchain, Path(self.temporary.name) / "bad-binary")

    def test_build_rejects_unreviewed_compiler_labels(self):
        from tools.mido_elf import symbols_from_elf

        def corrupted_labels(blob, required):
            symbols = symbols_from_elf(blob, required)
            symbols["mido_ttbr0_return_capture"] += 4
            return symbols

        with patch(MODULE + ".symbols_from_elf", side_effect=corrupted_labels):
            with self.assertRaisesRegex(ValueError, "instruction labels"):
                build_island(self.kernel, self.toolchain, Path(self.temporary.name) / "bad-labels")

    def test_header_spans_and_original_observer_are_preserved(self):
        header, review = self.configure()
        for line in self.header.splitlines():
            if line.startswith(("#define MIDO_VM_PROTECTION_SPANS", "#define MIDO_C_OBSERVER",
                                "#define UNRELATED")):
                self.assertIn(line + "\n", header)
        for name in ("MIDO_C_RECORD", "MIDO_C_RETURN_LITERAL"):
            self.assertEqual(review["post_c_definitions"][name], self.review["post_c_definitions"][name])
        self.assertIn("#define MIDO_TTBR1_ISLAND_BYTES {0x", header)

    def test_idempotence_and_deepcopy(self):
        original = deepcopy(self.review)
        symbols = deepcopy(self.symbols)
        kernel = bytearray(self.kernel)
        header, review = configure_ttbr0_carrier(kernel, self.header, self.review, self.payload, symbols)
        self.assertEqual(self.review, original)
        self.assertEqual(kernel, self.kernel)
        self.assertEqual(self.configure(header=header, review=review), (header, review))
        review["values"]["MIDO_EARLY_STOP_PA"] = 0
        review["post_c_definitions"]["MIDO_C_RECORD"] = 0
        review["ttbr1_island"]["symbols"]["mido_ttbr0_return"] = 0
        self.assertEqual(symbols, self.symbols)
        self.assertEqual(self.review, original)


if __name__ == "__main__":
    unittest.main()
