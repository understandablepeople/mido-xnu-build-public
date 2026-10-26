import hashlib
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from tools.prepare_iig_legacy_probe import (compile_layout, legacy_candidate, layout_probe,
                                           prepare_candidates, invocation_assertions)


class LegacyIigProbeTests(unittest.TestCase):
    def test_temporary_legacy_fallback_warns_without_replacing_implementation(self):
        root = Path(__file__).resolve().parents[1]
        original = (root / "tests/fixtures/IOBufferMemoryDescriptor-driverkit-286.iig.cpp").read_bytes()
        implementation = original.replace(b"\r\n", b"\n") + b"\n// diagnostic variant\n"
        profile = json.loads((root / "tools/iig_legacy_profiles.json").read_text())["IOBufferMemoryDescriptor.iig.cpp"]
        warning = io.StringIO()
        with patch("tools.prepare_iig_legacy_probe.IORPC_SHA256", hashlib.sha256(b"header").hexdigest()), contextlib.redirect_stderr(warning):
            candidate, report = legacy_candidate(implementation, b"header", profile, allow_unreviewed_legacy=True)
            self.assertEqual(candidate, implementation)
            self.assertFalse(report["hash_reviewed"])
            self.assertTrue(report["temporary_legacy_passthrough"])
            self.assertIn(report["input_sha256"], warning.getvalue())
            self.assertIn("WARNING", warning.getvalue())
            for changed in (
                implementation.replace(b"uint32_t sendSize;", b"uint64_t sendSize;"),
                implementation.replace(b"DriverKit-286", b"DriverKit-999"),
                implementation.replace(b"uint32_t sendSize;", b"uint32_t sendSize; void *kernelContent;"),
                implementation.replace(b"_Msg_Content content;", b"_Msg_Content missing;"),
            ):
                with self.assertRaises(ValueError):
                    legacy_candidate(changed, b"header", profile, allow_unreviewed_legacy=True)
            with self.assertRaisesRegex(ValueError, "unreviewed IORPC"):
                legacy_candidate(implementation, b"wrong header", profile, allow_unreviewed_legacy=True)

    def test_driverkit_286_preserves_actual_legacy_output(self):
        root = Path(__file__).resolve().parents[1]
        original = (root / "tests/fixtures/IOBufferMemoryDescriptor-driverkit-286.iig.cpp").read_bytes()
        profile = json.loads((root / "tools/iig_legacy_profiles.json").read_text())["IOBufferMemoryDescriptor.iig.cpp"]
        self.assertEqual(hashlib.sha256(original.replace(b"\r\n", b"\n")).hexdigest(),
                         profile["variants"][0]["input_sha256"])
        with patch("tools.prepare_iig_legacy_probe.IORPC_SHA256", hashlib.sha256(b"header").hexdigest()):
            candidate, report = legacy_candidate(original, b"header", profile)
            with self.assertRaisesRegex(ValueError, "unreviewed OSObject"):
                legacy_candidate(original + b"modified", b"header", profile)
            with self.assertRaisesRegex(ValueError, "unreviewed IORPC"):
                legacy_candidate(original, b"wrong header", profile)
        self.assertEqual(candidate, original.replace(b"\r\n", b"\n"))
        self.assertEqual(report["selected_legacy_branches"], {})
        assertions, count = invocation_assertions(candidate)
        self.assertEqual(count, 2)
        self.assertEqual(assertions.count(b"RPC overlay field"), 8)
        self.assertEqual(assertions.count(b"RPC inline content offset"), 2)
        self.assertNotIn(b"_Msg_With_Content", assertions)
        self.assertIn(b"sizeof(IORPCMessageMach) + 1 * sizeof(mach_msg_port_descriptor_t)", assertions)

    def test_inline_message_layout_is_not_silently_assumed(self):
        candidate = (b"struct Class_Call_Msg { IORPCMessageMach mach; int unknown; "
                     b"Class_Call_Msg_Content content; };\n} Class_Call_Invocation;")
        with self.assertRaisesRegex(ValueError, "inline RPC"):
            invocation_assertions(candidate)

    def test_driverkit_286_complex_inline_layout_warns_and_uses_compiler_size(self):
        banner = b"/* iig(DriverKit-286 Mar 29 2024 10:27:09) generated from IOMemoryDescriptor.iig */\n"
        candidate = (banner + b"struct IOMemoryDescriptor_Create_Msg {\n"
                     b"IORPCMessageMach mach;\n"
                     b"mach_msg_port_descriptor_t __object__descriptor;\n"
                     b"mach_msg_port_descriptor_t withDescriptors__descriptor[32];\n"
                     b"IOMemoryDescriptor_Create_Msg_Content content;\n};\n"
                     b"}\nIOMemoryDescriptor_Create_Invocation;")
        warning = io.StringIO()
        with contextlib.redirect_stderr(warning):
            assertions, count = invocation_assertions(candidate)
        self.assertEqual(count, 1)
        self.assertIn("WARNING: unreviewed RPC layout in IOMemoryDescriptor.iig.cpp", warning.getvalue())
        self.assertIn("withDescriptors__descriptor[32]", warning.getvalue())
        self.assertIn(b"withDescriptors__descriptor[32];", assertions)
        self.assertIn(b"#pragma pack(push, 4)", assertions)
        self.assertIn(b"#pragma pack(pop)", assertions)
        self.assertIn(b"== sizeof(IOMemoryDescriptor_Create_MidoInlinePrefix)", assertions)
        self.assertEqual(assertions.count(b"RPC overlay field"), 4)
        self.assertIn(b"RPC compiler-derived inline size", assertions)
        for invalid in (candidate.replace(b"DriverKit-286", b"DriverKit-999"),
                        candidate.replace(b"generated from IOMemoryDescriptor.iig", b"generated from Other.iig")):
            with self.assertRaisesRegex(ValueError, "inline RPC"):
                invocation_assertions(invalid)

    def test_eventlink_inline_message_counts_port_and_ool_descriptors(self):
        candidate = (b"struct IOEventLink_Create_Msg {\n"
                     b"IORPCMessageMach mach;\n"
                     b"mach_msg_port_descriptor_t __object__descriptor;\n"
                     b"mach_msg_ool_descriptor_t name__descriptor;\n"
                     b"mach_msg_port_descriptor_t userClient__descriptor;\n"
                     b"IOEventLink_Create_Msg_Content   content;\n};\n"
                     b"}\nIOEventLink_Create_Invocation;")
        assertions, count = invocation_assertions(candidate)
        self.assertEqual(count, 1)
        self.assertEqual(assertions.count(b"RPC overlay field"), 4)
        self.assertIn(b"sizeof(IORPCMessageMach) + 2 * sizeof(mach_msg_port_descriptor_t) + "
                      b"1 * sizeof(mach_msg_ool_descriptor_t)", assertions)
        self.assertNotIn(b"_Msg_With_Content", assertions)
        with self.assertRaisesRegex(ValueError, "inline RPC"):
            invocation_assertions(candidate.replace(b"mach_msg_ool_descriptor_t", b"unknown_descriptor_t"))

    def test_inline_message_counts_ool_port_arrays_and_empty_prefix(self):
        prefix = b"struct Example_Call_Msg { IORPCMessageMach mach; "
        suffix = b"Example_Call_Msg_Content content; };\n} Example_Call_Invocation;"
        for descriptor, expected in (
            (b"mach_msg_ool_ports_descriptor_t ports__descriptor; ", b"1 * sizeof(mach_msg_ool_ports_descriptor_t)"),
            (b"", b"0 * sizeof(mach_msg_port_descriptor_t)"),
        ):
            with self.subTest(descriptor=descriptor):
                assertions, count = invocation_assertions(prefix + descriptor + suffix)
                self.assertEqual(count, 1)
                self.assertIn(expected, assertions)

    def fixture(self):
        pairs = [
            (b"const struct Example_Msg * message;", b"const struct Example_Msg_With_Content * message;"),
            (b"const struct Example_Msg_Content * kernelContent;", None),
            (b"IORPCMessage * msg = rpc.kernelContent;", b"IORPCMessage * msg = IORPCMessageFromMach(rpc.message, false);"),
            (b"IORPC rpc = { .kernelContent = &buf.msg.content.__hdr };", b"IORPC rpc = { four_fields };"),
            (b"const Example_Msg_Content * messageContent = rpc.kernelContent;", b"const Example_Msg_With_Content * message = rpc.message;"),
        ] * 2 + [(b"#define MESSAGE_CONTENT(field) (messageContent->field)",
                   b"#define MESSAGE_CONTENT(field) (message->content.field)")]
        original = b"unmodified prefix\n"
        expected = original
        for kernel, legacy in pairs:
            original += b"#ifdef KERNEL\n" + kernel + b"\n"
            if legacy is not None:
                original += b"#else /* KERNEL */\n" + legacy + b"\n"
                expected += legacy + b"\n"
            original += b"#endif /* KERNEL */\n"
        suffix = b"if (rpc.sendSize < sizeof(message)) return kIOReturnIPCError;\nunmodified suffix\n"
        return original + suffix, expected + suffix

    def test_projection_preserves_other_code_and_selects_all_legacy_branches(self):
        original, expected = self.fixture()
        header = b"old ABI"
        with patch("tools.prepare_iig_legacy_probe.IMPLEMENTATION_SHA256", hashlib.sha256(original).hexdigest()), \
                patch("tools.prepare_iig_legacy_probe.IORPC_SHA256", hashlib.sha256(header).hexdigest()):
            candidate, report = legacy_candidate(original, header)
            self.assertEqual(candidate, expected)
            self.assertFalse(report["kernel_abi_modified"])
            self.assertFalse(report["boot_approved"])
            self.assertEqual(sum(report["selected_legacy_branches"].values()), 11)
            self.assertEqual(legacy_candidate(original.replace(b"\n", b"\r\n"), header)[0], expected)

    def test_nested_or_unknown_conditionals_are_rejected(self):
        original, expected = self.fixture()
        for extra in (b"#ifdef KERNEL\nunknown();\n#endif /* KERNEL */\n",
                      b"#ifdef KERNEL\n#if OTHER\nnested();\n#endif\n#endif /* KERNEL */\n"):
            data = original + extra
            with patch("tools.prepare_iig_legacy_probe.IMPLEMENTATION_SHA256", hashlib.sha256(data).hexdigest()), \
                    patch("tools.prepare_iig_legacy_probe.IORPC_SHA256", hashlib.sha256(b"header").hexdigest()):
                with self.assertRaisesRegex(ValueError, "unreviewed RPC|unexpected nested"):
                    legacy_candidate(data, b"header")

    def test_profile_pins_result_not_just_input(self):
        original, expected = self.fixture()
        oneway = b"void\nClass::Notify()\n{\n    kern_return_t ret;\n    ret = Invoke();\n}\n"
        original += oneway
        expected += oneway.replace(b"kern_return_t ret;", b"[[maybe_unused]] kern_return_t ret;")
        profile = {"input_sha256": hashlib.sha256(original).hexdigest(),
                   "output_sha256": hashlib.sha256(expected).hexdigest(),
                   "ignored_oneway_return_declarations": 1,
                   "selected_legacy_branches": {"invocation_field": 2, "content_accessor": 1,
                       "message_lookup": 2, "rpc_initializer": 2,
                       "typed_message_lookup": 2, "invocation_message_type": 2}}
        with patch("tools.prepare_iig_legacy_probe.IORPC_SHA256", hashlib.sha256(b"header").hexdigest()):
            self.assertEqual(legacy_candidate(original, b"header", profile)[0], expected)
            profile["output_sha256"] = "wrong result"
            with self.assertRaisesRegex(ValueError, "output hash"):
                legacy_candidate(original, b"header", profile)

    def test_all_class_probe_requires_complete_reviewed_set(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "exact reviewed set"):
                prepare_candidates(Path(directory), b"header")

    def test_per_method_assertions_check_all_rpc_fields_and_inline_content(self):
        assertions, count = invocation_assertions(b"} Class_Call_Invocation;\n} Class_Other_Invocation;")
        self.assertEqual(count, 2)
        self.assertEqual(assertions.count(b"RPC overlay field"), 8)
        self.assertEqual(assertions.count(b"RPC inline content offset"), 2)
        self.assertTrue(assertions.startswith(b"\n#if KERNEL\n"))
        for data in (b"no unions", b"} Same_Invocation;\n} Same_Invocation;"):
            with self.assertRaisesRegex(ValueError, "distinct invocation"):
                invocation_assertions(data)

    def test_compile_failure_or_timeout_is_not_approval(self):
        with patch("tools.prepare_iig_legacy_probe.subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 1, "", "layout mismatch")
            report = compile_layout(Path("clang"), Path("probe.cpp"))
            self.assertFalse(report["passed"])
            self.assertEqual(report["diagnostics"], "layout mismatch")
            self.assertEqual(run.call_args.kwargs["timeout"], 30)
            self.assertIn("--target=arm64-apple-ios16.0", run.call_args.args[0])
            run.side_effect = subprocess.TimeoutExpired("clang", 30)
            self.assertFalse(compile_layout(Path("clang"), Path("probe.cpp"))["passed"])

    def test_unreviewed_implementation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unreviewed OSObject"):
            legacy_candidate(b"arbitrary source", b"arbitrary header")

    def test_unreviewed_header_is_rejected(self):
        with patch("tools.prepare_iig_legacy_probe.IMPLEMENTATION_SHA256",
                   "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"):
            with self.assertRaisesRegex(ValueError, "unreviewed IORPC"):
                legacy_candidate(b"", b"arbitrary header")

    def test_missing_reviewed_branches_are_rejected_even_with_matching_hash(self):
        empty_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        with patch("tools.prepare_iig_legacy_probe.IMPLEMENTATION_SHA256", empty_hash), \
                patch("tools.prepare_iig_legacy_probe.IORPC_SHA256", empty_hash):
            with self.assertRaisesRegex(ValueError, "incomplete legacy"):
                legacy_candidate(b"", b"")

    def test_layout_probe_uses_actual_declaration_and_both_generated_unions(self):
        candidate = (b"ignored\nstruct OSObject_SetDispatchQueue_Msg_Content {};\n"
                     b"typedef union { int marker; } OSObject_SetDispatchQueue_Invocation;\n"
                     b"#if !KERNEL\nextern OSMetaClass")
        header = b"struct IORPC { void *message; void *reply; uint32_t sendSize, replySize; };"
        probe = layout_probe(candidate, header)
        self.assertIn(header, probe)
        self.assertIn(b"int marker", probe)
        self.assertNotIn(b"ignored", probe)
        self.assertIn(b"OSObject_CopyDispatchQueue_Invocation", probe)
        self.assertEqual(probe.count(b"overlay offset"), 8)
        self.assertEqual(probe.count(b"inline content matches descriptor walk"), 2)
        self.assertNotIn(b"model_descriptor", probe)


if __name__ == "__main__":
    unittest.main()
