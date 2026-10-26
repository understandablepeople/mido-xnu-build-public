from contextlib import contextmanager
import hashlib
import struct
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.check_xnu_build import (HEADER_FILES, check, configuration_command, inspect_headers,
                                   modernize_frontend_flags, OBSOLETE_INIT_FLAG, phase_command,
                                   public_sdk_search_paths, modernize_compatibility_warning,
                                   export_mido_header, repair_disabled_mac_parameter, repair_memory_device_formats,
                                   compiled_objects, repair_startup_network_includes, repair_uio_alignment,
                                   repair_queue_line_formats, repair_vfs_buffer_diagnostics,
                                   repair_vfs_cache_diagnostics, run_phase, succeeded)
from tools.check_xnu_build import (repair_non_pac_pmap_padding, repair_metaclass_overrides,
                                   repair_kalloc_initializers, repair_kmem_guard_initializers)
from tools.check_xnu_build import inspect_iig_abi, inspect_iig_references
from tools.check_xnu_build import stage_firehose_header, enable_firehose_spi
from tools.check_xnu_build import repair_tunable_initializers, repair_sysctl_initializers
from tools.check_xnu_build import repair_socket_core_includes, repair_socket_flow_logging, repair_disabled_kperf_ast
from tools.check_xnu_build import repair_nvram_log_prefix, repair_clock_microsecond_formats
from tools.check_xnu_build import repair_disabled_kperf_timer, repair_mido_apple_tunables
from tools.check_xnu_build import repair_vnode_argument_offsets, repair_qsort_alignment


class XnuBuildTests(unittest.TestCase):
    def test_null_pointer_arithmetic_is_replaced_without_changing_other_source(self):
        cases = (
            (repair_vnode_argument_offsets, "d535fde0a15f480bd4ade024de39d3084476835ca0065ab295e51b511a131ed4",
             b"((int) (((char *) (&(((p_type)NULL)->field))) - ((char *) NULL)))",
             b"((int)__builtin_offsetof(__typeof__(*(p_type)NULL), field))"),
            (repair_qsort_alignment, "cc113c8ed0a9158a9c657cf1c30181f4205bbc822453bde39258f9367dff5fe5",
             b"((char *)a - (char *)0) % sizeof(long)", b"((uintptr_t)(a)) % sizeof(long)"),
        )
        for transform, expected, original, replacement in cases:
            data = b"before\n" + original + b"\nafter"
            with self.subTest(transform=transform.__name__):
                with patch("tools.check_xnu_build.hashlib.sha256") as digest:
                    digest.return_value.hexdigest.return_value = expected
                    self.assertEqual(transform(data), data.replace(original, replacement))
                    for invalid in (data + data, data.replace(original, replacement)):
                        with self.assertRaisesRegex(ValueError, "layout"):
                            transform(invalid)
                with self.assertRaisesRegex(ValueError, "source"):
                    transform(data)

    def test_disabled_kperf_timer_matches_existing_enum_gate(self):
        entry = b"\t[RUNNING_TIMER_KPERF] = kperf_timer_expire,\n"
        data = b"quantum_stays\n" + entry + b"size_assertion_stays\n"
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "45247c10581a8b895ac1311d2533ccff0c59fcd3af1b8917ff35d640c8de6e79"
            result = repair_disabled_kperf_timer(data)
            self.assertEqual(result, b"quantum_stays\n#if KPERF\n" + entry + b"#endif\nsize_assertion_stays\n")
            with self.assertRaisesRegex(ValueError, "timer table"):
                repair_disabled_kperf_timer(data + data)
        with self.assertRaisesRegex(ValueError, "processor timer source"):
            repair_disabled_kperf_timer(data)

    def test_mido_excludes_only_apple_tunable_include_and_application(self):
        header = b"#include <arm64/tunables/tunables.s>\n"
        call = b"\tAPPLY_TUNABLES x12, x13, x14\n"
        data = header + b"register_setup_stays\n" + call + b"mmu_setup_stays\n"
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "bf92967ea96e638f5a9a002cd4e478272f08616531d212caa919944c85e8a023"
            result = repair_mido_apple_tunables(data)
            self.assertEqual(result.count(b"#if !defined(MIDO)\n"), 2)
            self.assertEqual(result.replace(b"#if !defined(MIDO)\n", b"").replace(b"#endif\n", b""), data)
            self.assertNotIn(b".macro APPLY_TUNABLES", result)
            with self.assertRaisesRegex(ValueError, "tunable layout"):
                repair_mido_apple_tunables(data + data)
        with self.assertRaisesRegex(ValueError, "startup source"):
            repair_mido_apple_tunables(data)

    def test_nvram_prefix_preserves_unsigned_line_format_and_all_other_arguments(self):
        original = b'IOLog("%s:%s:%u - " fmt, __FILE_NAME__, __FUNCTION__, __LINE__, ##args);'
        data = original + b"\nunchanged\n" + original + b"\n" + original
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "ba6d8e74eb5b920a92a18236eed56b7dc95afd09da95116d3d52935714b2cc03"
            result = repair_nvram_log_prefix(data)
            self.assertEqual(result.count(b"(unsigned int)__LINE__"), 3)
            self.assertEqual(result.replace(b"(unsigned int)__LINE__", b"__LINE__"), data)
            for invalid in (original, data + original, result):
                with self.assertRaisesRegex(ValueError, "prefix layout"):
                    repair_nvram_log_prefix(invalid)
        with self.assertRaisesRegex(ValueError, "NVRAM logging source"):
            repair_nvram_log_prefix(data)

    def test_clock_formats_preserve_seconds_and_unsigned_microsecond_values(self):
        data = b'os_log("%lu s %d u", secs, microsecs);\n' * 21
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "001630fcf2089f7f8df7c39ee79f8ba9279b84aa06ec5d8883b016eb15fdc5b1"
            result = repair_clock_microsecond_formats(data)
            self.assertEqual(result.count(b"%u"), 21)
            self.assertEqual(result.replace(b"%u", b"%d"), data)
            for invalid in (data + b"%d", data.replace(b"%d", b"%u")):
                with self.assertRaisesRegex(ValueError, "format count"):
                    repair_clock_microsecond_formats(invalid)
        with self.assertRaisesRegex(ValueError, "clock diagnostic source"):
            repair_clock_microsecond_formats(data)

    def test_socket_dependencies_add_real_headers_only(self):
        cases = (
            (repair_socket_core_includes, "0eb60e42e57257412c7f822f6b3f5d1487adf724b7782cf52df07b4a7f95d9ac",
             b"#include <net/route.h>\n", b"#include <net/if_var.h>\n#include <os/log.h>\n#include <net/route.h>\n"),
            (repair_socket_flow_logging, "c14cb48ccae48a321e7e23d01e7c8011e623e070ece9eda68736e7caed16f7ff",
             b"#include <sys/socketvar.h>\n", b"#include <sys/socketvar.h>\n#include <os/log.h>\n"),
        )
        for transform, expected, before, after in cases:
            with self.subTest(transform=transform.__name__):
                with patch("tools.check_xnu_build.hashlib.sha256") as digest:
                    digest.return_value.hexdigest.return_value = expected
                    self.assertEqual(transform(before), after)
                    with self.assertRaisesRegex(ValueError, "include layout"):
                        transform(before + before)
                with self.assertRaisesRegex(ValueError, "source"):
                    transform(before)

    def test_disabled_kperf_guards_header_and_callback_without_stubbing(self):
        data = (b"#include <kperf/kperf_kpc.h>\n"
                b"\tif (reasons & AST_KPERF) {\n"
                b"\t\tthread_ast_clear(thread, AST_KPERF);\n"
                b"\t\tkperf_kpc_thread_ast(thread);\n\t}\n")
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "2667cac493a5a59c14647bf0652b310de98b2e66d97c225f36fcead39c703c0d"
            result = repair_disabled_kperf_ast(data)
            self.assertEqual(result.count(b"#if KPERF && KPC"), 2)
            self.assertEqual(result.count(b"kperf_kpc_thread_ast(thread);"), 1)
            self.assertEqual(result.replace(b"#if KPERF && KPC\n", b"").replace(b"\n#endif", b""), data)
            with self.assertRaisesRegex(ValueError, "AST layout"):
                repair_disabled_kperf_ast(data + data)
        with self.assertRaisesRegex(ValueError, "AST source"):
            repair_disabled_kperf_ast(data)

    def test_tunable_defaults_do_not_add_string_flag_to_dt_spec(self):
        continuation = b" " + bytes((92,)) + b"\n"
        boolean = b".var_is_bool = __startup_type_is_bool(type_t)," + continuation
        string = b".var_is_str = true," + continuation
        data = boolean + string + b"DT_SPEC\n" + boolean
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "41afcc8be3e13b2e865fa55be1da100894c74cbd84023ef781392efa746d75f5"
            result = repair_tunable_initializers(data)
            self.assertEqual(result.count(b".var_is_str = false"), 1)
            self.assertEqual(result.count(b".var_is_bool = false"), 1)
            self.assertTrue(result.endswith(b"DT_SPEC\n" + boolean))
            with self.assertRaisesRegex(ValueError, "initializer layout"):
                repair_tunable_initializers(data + data)
        with self.assertRaisesRegex(ValueError, "startup tunable header"):
            repair_tunable_initializers(data)

    def test_sysctl_defaults_preserve_other_initializer_values(self):
        data = (b".oid_parent     = &sysctl_##parent##_children,\n"
                b".oid_version    = SYSCTL_OID_VERSION,\n"
                b"EXTENSION_MACRO\n.oid_version    = SYSCTL_OID_VERSION,\n")
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "c8e3ae8a6a560c9d6abcad2f2ea83fe377f9f962179f28c30baab87c002477f4"
            result = repair_sysctl_initializers(data)
            restored = result.replace(b" " + bytes((92,)) + b"\n\t    .oid_link = { .sle_next = NULL },", b"")
            restored = restored.replace(b" " + bytes((92,)) + b"\n\t    .oid_refcnt = 0,", b"")
            self.assertEqual(restored, data)
            with self.assertRaisesRegex(ValueError, "initializer layout"):
                repair_sysctl_initializers(data + data)
        with self.assertRaisesRegex(ValueError, "sysctl header"):
            repair_sysctl_initializers(data)

    def test_firehose_spi_enables_real_declarations_without_modifying_header(self):
        data = b"DEFINES = -DAPPLE -DKERNEL -DKERNEL_PRIVATE -DXNU_KERNEL_PRIVATE " + bytes((92,)) + b"\n"
        result = enable_firehose_spi(data)
        self.assertEqual(result.replace(b"-DOS_FIREHOSE_SPI=1 ", b""), data)
        self.assertEqual(result.count(b"-DOS_FIREHOSE_SPI=1"), 1)
        for invalid in (b"unreviewed", data + data, result):
            with self.assertRaisesRegex(ValueError, "firehose define layout"):
                enable_firehose_spi(invalid)

    def test_firehose_header_is_hash_checked_before_any_file_write(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            with patch('tools.check_xnu_build.urllib.request.urlopen') as fetch:
                fetch.return_value.__enter__.return_value.read.return_value = b'not the pinned header'
                with self.assertRaisesRegex(ValueError, 'matching-distribution'):
                    stage_firehose_header(source)
                self.assertFalse((source / 'EXTERNAL_HEADERS/os/firehose_buffer_private.h').exists())

    def test_firehose_staging_refuses_existing_headers_without_network_access(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            target = source / 'EXTERNAL_HEADERS/os/firehose_buffer_private.h'
            target.parent.mkdir(parents=True)
            target.write_bytes(b'keep original')
            with patch('tools.check_xnu_build.urllib.request.urlopen') as fetch:
                with self.assertRaisesRegex(ValueError, 'existing firehose'):
                    stage_firehose_header(source)
                fetch.assert_not_called()
            self.assertEqual(target.read_bytes(), b'keep original')

    def test_reviewed_rpc_requires_explicit_kernel_attempt_before_setup(self):
        with patch('tools.check_xnu_build.setup') as setup:
            with self.assertRaisesRegex(ValueError, "explicit kernel attempt"):
                check(Path('unused'), 'iphoneos', reviewed_rpc=True)
            setup.assert_not_called()

    def test_vm_guard_explicit_zeros_preserve_tag_and_both_sites(self):
        data = b"kmem_guard_t guard = {\n\t\t.kmg_tag = tag,\n\t};\n" * 2
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "f65a4aefbbd0901ec16b39c8d78bcb8c43ea2a2bb7f9f2fbbc5a22d94e6a2ae1"
            result = repair_kmem_guard_initializers(data)
            self.assertEqual(result.count(b".kmg_tag = tag"), 2)
            for field in (b"kmg_type_hash", b"kmg_atomic", b"kmg_submap", b"kmg_context"):
                self.assertEqual(result.count(b"." + field + b" = 0,"), 2)
            with self.assertRaisesRegex(ValueError, "initializer layout"):
                repair_kmem_guard_initializers(data + data)
        with self.assertRaisesRegex(ValueError, "allocation header"):
            repair_kmem_guard_initializers(data)

    def test_typed_allocator_defaults_cover_private_and_external_views(self):
        continuation = b" " + bytes((92,)) + b"\n"
        data = (b"#define _KALLOC_TYPE_DEFINE(var, type, flags)" + continuation +
                b"    .kt_signature = KALLOC_TYPE_EMIT_SIG(type)," + continuation +
                b"    .kt_version = KT_V1," + continuation +
                b"    .kt_size_type = sizeof(type)," + continuation +
                b"    .kt_sig_type = KALLOC_TYPE_EMIT_SIG(type)," + continuation +
                b"    .kt_version = KT_V1," + continuation +
                b"#ifndef XNU_KERNEL_PRIVATE\nunchanged tail")
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "34289216bd95d4691f407996c97d5a64d665153b5470e605ec9391bf1661edd3"
            result = repair_kalloc_initializers(data)
            self.assertIn(b".kt_zshared = NULL, .kt_zsig = NULL,", result)
            self.assertIn(b".unused1 = NULL, .unused2 = NULL,", result)
            self.assertEqual(result.count(b".kt_stats = NULL"), 2)
            self.assertEqual(result.count(b".kt_size_hdr = 0"), 1)
            self.assertTrue(result.endswith(b"unchanged tail"))
        with self.assertRaisesRegex(ValueError, "allocation header"):
            repair_kalloc_initializers(data)

    def test_metaclass_override_annotations_do_not_change_signatures(self):
        declarations = (
            b"virtual void retain() const;", b"virtual void release() const;",
            b"virtual void release(int freeWhen) const;",
            b"virtual void taggedRetain(const void * tag = NULL) const;",
            b"virtual void taggedRelease(const void * tag = NULL) const;",
            b"const int    freeWhen) const;", b"virtual int getRetainCount() const;",
            b"virtual const OSMetaClass * getMetaClass() const;", b"~OSMetaClass();",
            b"virtual bool serialize(OSSerialize * serializer) const;",
        )
        data = b"\n".join(declarations) + b"\nvirtual void abstract_method() = 0;\n"
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "0b47cb07db5854013123fce2972592d63997c8a7bced80b7365bb04af4614647"
            result = repair_metaclass_overrides(data)
            self.assertEqual(result.count(b" override;"), 10)
            self.assertEqual(result.replace(b" override;", b";"), data)
            with self.assertRaisesRegex(ValueError, "override layout"):
                repair_metaclass_overrides(b"missing declarations")
        with self.assertRaisesRegex(ValueError, "metaclass header"):
            repair_metaclass_overrides(data)

    def test_iig_reference_inventory_distinguishes_four_abi_changes(self):
        data = b"\n".join((
            b"const struct OSObject_Call_Msg_Content * kernelContent;",
            b"IORPCMessage * msg = rpc.kernelContent;",
            b"IORPC rpc = { .kernelContent = &buf.msg.content.__hdr };",
            b"const OSObject_Call_Msg_Content * messageContent = rpc.kernelContent;",
        ))
        report = inspect_iig_references(data)
        self.assertEqual([record["role"] for record in report["references"]],
                         ["invocation_field", "message_lookup", "rpc_initializer", "typed_message_lookup"])
        self.assertEqual(report["unclassified_lines"], [])

    def test_iig_reference_inventory_does_not_hide_unknown_or_multiple_uses(self):
        report = inspect_iig_references(b"unrelated\nuse(rpc.kernelContent);\n"
                                        b"IORPCMessage * msg = rpc.kernelContent; use(rpc.kernelContent);")
        self.assertEqual(report["unclassified_lines"], [2, 3])
        self.assertEqual(inspect_iig_references(b"legacy rpc.message")["references"], [])

    def test_iig_kernel_content_mismatch_is_not_accepted_as_compatible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            header = root / "source/iokit/IOKit/IORPC.h"
            header.parent.mkdir(parents=True)
            header.write_bytes(b"struct IORPC { void *message; };\n")
            implementation = root / "build/DriverKit/OSObject.iig.cpp"
            implementation.parent.mkdir(parents=True)
            implementation.write_bytes(b"auto msg = rpc.kernelContent;\n")
            report = inspect_iig_abi(root / "source", root / "build")
            self.assertFalse(report["compatible"])
            self.assertFalse(report["header_has_kernelContent"])
            implementation.write_bytes(b"auto msg = IORPCMessageFromMach(rpc.message, false);\n")
            self.assertTrue(inspect_iig_abi(root / "source", root / "build")["compatible"])
            implementation.unlink()
            with self.assertRaisesRegex(ValueError, "real OSObject"):
                inspect_iig_abi(root / "source", root / "build")

    def test_non_pac_padding_rename_preserves_field_type_and_other_padding(self):
        data = b"bool reserved10;\n#else\n\tbool reserved10;\n#endif /* HAS_APPLE_PAC */"
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "228414f8405c12ae2021fbfb1d53c37d7509fa6b7afa97a78ba4a5eef48f2cde"
            result = repair_non_pac_pmap_padding(data)
            self.assertEqual(result.count(b"bool reserved10;"), 1)
            self.assertEqual(result.count(b"bool reserved_no_pac;"), 1)
            self.assertEqual(result.count(b"bool "), 2)
        with self.assertRaisesRegex(ValueError, "pmap header"):
            repair_non_pac_pmap_padding(b"unreviewed")

    def test_uio_repair_moves_alignment_to_declaration_without_changing_byte_type(self):
        original = b"typedef char __attribute__((aligned(_Alignof(union iovecs)))) uio_stackbuf_t;"
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "f0351f1b7dda1fb5b7cf25bf8dc37129b35f5f1fb48f5fd194beb612ddef3e1c"
            self.assertEqual(repair_uio_alignment(original), b"#define uio_stackbuf_t _Alignas(union iovecs) char")
            with self.assertRaisesRegex(ValueError, "alignment layout"):
                repair_uio_alignment(original + original)

    def test_queue_repair_casts_only_diagnostic_line_numbers(self):
        data = b"trace.lastline = __LINE__;\n" + b"panic(format, __LINE__);\n" * 9
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "cc64e15ab2e5f2e0b70269305f3acf987c3f375f660af68d81cc012de2b7a2c6"
            result = repair_queue_line_formats(data)
            self.assertEqual(result.count(b"(unsigned int)__LINE__"), 9)
            self.assertIn(b"trace.lastline = __LINE__;", result)
            with self.assertRaisesRegex(ValueError, "diagnostic layout"):
                repair_queue_line_formats(data + b"panic(format, __LINE__);")

    def test_mac_repair_preserves_the_other_unused_parameter(self):
        data = b"#pragma unused(p)\nreturn cred != proc_ucred(kernproc);\n#else\n#pragma unused(p)"
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "3f9400087ac1b680fc225b54b8449f03db429a989156eeea46ceff318f90b873"
            result = repair_disabled_mac_parameter(data)
            self.assertEqual(result.count(b"unused(p)"), 1)
            self.assertEqual(result.count(b"unused(cred)"), 1)

    def test_bsd_startup_repair_retains_tcp_header_and_adds_real_definitions(self):
        data = b"#include <netinet/tcp_var.h>\n"
        with patch("tools.check_xnu_build.hashlib.sha256") as digest:
            digest.return_value.hexdigest.return_value = "81ca252a6b13082cc7db4c8cdce86cc5adf8b3356ac490452265084d6fa8e1a2"
            self.assertEqual(repair_startup_network_includes(data), b"#include <net/if_var.h>\n" + data)
            with self.assertRaisesRegex(ValueError, "include layout"):
                repair_startup_network_includes(data + data)

    def test_unreviewed_queue_and_vfs_sources_are_rejected(self):
        for transform in (repair_queue_line_formats, repair_vfs_buffer_diagnostics, repair_vfs_cache_diagnostics):
            with self.subTest(transform=transform.__name__), self.assertRaises(ValueError):
                transform(b"unreviewed")

    def test_unknown_uio_header_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "UIO internal header"):
            repair_uio_alignment(b"unreviewed")

    def test_unknown_bsd_startup_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "BSD startup source"):
            repair_startup_network_includes(b"unreviewed")

    def test_unknown_memory_device_source_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "memory device source"):
            repair_memory_device_formats(b"unreviewed")

    def test_object_inventory_excludes_host_and_nonobject_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            root = build / "obj/DEVELOPMENT_ARM64_MIDO"
            root.mkdir(parents=True)
            (root / "valid.o").write_bytes(struct.pack("<4I", 0xFEEDFACF, 0x0100000C, 0, 1))
            (root / "host.o").write_bytes(struct.pack("<4I", 0xFEEDFACF, 0x01000007, 0, 1))
            (root / "empty.o").write_bytes(b"")
            (root / "lto.o").write_bytes(b"BC\xc0\xde")
            report = compiled_objects(build)
            self.assertEqual(report["arm64_mach_o_object_count"], 1)
            self.assertEqual(report["sample_paths"], ["valid.o"])
            self.assertEqual(report["llvm_bitcode_file_count"], 1)
            self.assertFalse(report["bitcode_target_verified"])

    def test_unknown_mac_internal_header_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "MAC internal header"):
            repair_disabled_mac_parameter(b"unreviewed")

    def test_only_pre_c11_compatibility_warning_is_disabled(self):
        data = b"-Werror -Weverything\n-Wno-c++98-compat " + bytes((92,)) + b"\n"
        result = modernize_compatibility_warning(data)
        self.assertIn(b"-Werror -Weverything", result)
        self.assertEqual(result.count(b"-Wno-pre-c11-compat"), 1)
        self.assertEqual(result.count(b"-Wno-error=cast-function-type-strict"), 1)
        self.assertNotIn(b"-Wno-cast-function-type-strict", result)
        self.assertIn(b"-fno-caret-diagnostics", result)
        self.assertIn(b"-fmacro-backtrace-limit=2", result)
        self.assertNotIn(b"-fdiagnostics-parseable-fixits", result)
        with self.assertRaisesRegex(ValueError, "warning layout"):
            modernize_compatibility_warning(b"unreviewed")

    def test_unknown_header_export_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            target = source / "pexpert/pexpert/arm64/Makefile"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"unreviewed")
            with self.assertRaisesRegex(ValueError, "export Makefile"):
                export_mido_header(source)
    def test_optional_search_paths_preserve_required_components_and_warnings(self):
        data = (b"-Werror -Wmissing-include-dirs\n"
                b"$(patsubst %, -I$(OBJROOT)/EXPORT_HDRS/%, $(COMPONENT_IMPORT_LIST))\n"
                b"-I$(SDKROOT)/usr/local/include/kernel\n"
                b"-I$(SDKROOT)/$(KPINCDIR)/platform\n")
        result = public_sdk_search_paths(data)
        self.assertIn(b"-Werror -Wmissing-include-dirs", result)
        self.assertIn(b"-I$(OBJROOT)/EXPORT_HDRS/$(component)", result)
        self.assertEqual(result.count(b"$(wildcard "), 3)
        self.assertIn(b"$(filter libsa,$(component))", result)

    def test_missing_or_duplicate_optional_path_is_rejected(self):
        for data in (b"", b"-I$(SDKROOT)/usr/local/include/kernel\n" * 2):
            with self.assertRaisesRegex(ValueError, "search-path layout"):
                public_sdk_search_paths(data)

    @contextmanager
    def ready_environment(self, output):
        report = {"setup_passed": True, "open_availability": {"script_path": str(output / "availability.pl")}}
        with patch("tools.check_xnu_build.setup", return_value=report), \
                patch("tools.check_xnu_build.prepare_frontend", return_value={"zero_initialization_preserved": True}), \
                patch("tools.check_xnu_build.inspect_iig_abi", return_value={"compatible": True}), \
                patch("tools.check_xnu_build.inspect_headers", return_value={"fixture": {}}), \
                patch("tools.check_xnu_build.verify_generated", return_value={"fixture": "hash"}):
            yield

    def test_changed_make_definitions_are_rejected_before_flag_changes(self):
        with self.assertRaisesRegex(ValueError, "unexpected architecture-patched"):
            modernize_frontend_flags(b"unreviewed flags")

    def test_crlf_and_lf_inputs_share_the_canonical_source_hash(self):
        data = b"-ftrivial-auto-var-init=zero\n\t" + OBSOLETE_INIT_FLAG + b" \\\n"
        with patch("tools.check_xnu_build.MAKE_DEFINITIONS_SHA256", hashlib.sha256(data).hexdigest()):
            self.assertEqual(modernize_frontend_flags(data),
                             modernize_frontend_flags(data.replace(b"\n", b"\r\n")))

    def test_only_the_obsolete_consent_flag_is_removed(self):
        data = (b"CFLAGS = -Werror -march=armv8-a \\\n\t-ftrivial-auto-var-init=zero \\\n\t"
                + OBSOLETE_INIT_FLAG + b" \\\n\t-fsigned-bitfields\n")
        with patch("tools.check_xnu_build.MAKE_DEFINITIONS_SHA256", hashlib.sha256(data).hexdigest()):
            result = modernize_frontend_flags(data)
        self.assertEqual(result, data.replace(b"\t" + OBSOLETE_INIT_FLAG + b" \\\n", b""))
        self.assertIn(b"-Werror", result)
        self.assertIn(b"-march=armv8-a", result)
        self.assertIn(b"-ftrivial-auto-var-init=zero", result)

    def test_missing_zero_initialization_flag_is_not_silently_accepted(self):
        data = b"\t" + OBSOLETE_INIT_FLAG + b" \\\n"
        with patch("tools.check_xnu_build.MAKE_DEFINITIONS_SHA256", hashlib.sha256(data).hexdigest()):
            with self.assertRaisesRegex(ValueError, "zero-initialization flag layout"):
                modernize_frontend_flags(data)

    def test_duplicate_obsolete_flags_are_not_silently_accepted(self):
        data = b"-ftrivial-auto-var-init=zero\n" + (b"\t" + OBSOLETE_INIT_FLAG + b" \\\n") * 2
        with patch("tools.check_xnu_build.MAKE_DEFINITIONS_SHA256", hashlib.sha256(data).hexdigest()):
            with self.assertRaisesRegex(ValueError, "zero-initialization flag layout"):
                modernize_frontend_flags(data)

    def test_commands_are_real_bounded_targets_without_install_or_dry_run(self):
        for target in ("exporthdrs", "build"):
            command = phase_command(Path("source"), Path("build"), "iphoneos", Path("availability.pl"), target)
            self.assertEqual(command[-1], target)
            self.assertIn("MAKEJOBS=" if target == "build" else "MAKEJOBS=--jobs=1", command)
            self.assertIn("-j3" if target == "build" else "-j1", command)
            self.assertEqual("--keep-going" in command, target == "build")
            self.assertIn("MIDO_AVAILABILITY_PL=availability.pl", command)
            self.assertNotIn("--just-print", command)
            self.assertNotIn("install", command)
        with self.assertRaises(ValueError):
            phase_command(Path("source"), Path("build"), "iphoneos", Path("availability.pl"), "install")

    def test_configuration_calls_real_doconf_in_config_only_mode(self):
        command = configuration_command(Path("source"), Path("generated"), "iphoneos")
        self.assertEqual(command[0], str(Path("source/SETUP/config/doconf")))
        for option in ("-c", "arm64", "mido", "iPhoneOS", "DEVELOPMENT"):
            self.assertIn(option, command)
        with self.assertRaises(ValueError):
            configuration_command(Path("source"), Path("generated"), "bad")

    def test_failed_setup_prevents_all_followup_phases(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch("tools.check_xnu_build.setup", return_value={"setup_passed": False}), \
                    patch("tools.check_xnu_build.run_phase") as run:
                report = check(output, "iphoneos", attempt_kernel=True)
            run.assert_not_called()
            self.assertFalse(report["pipeline_passed"])
            self.assertFalse(report["kernel_built"])

    def test_header_failure_stops_before_doconf_and_compile(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.ready_environment(output), \
                    patch("tools.check_xnu_build.run_phase", return_value={"exit_code": 2, "stopped_by": None}) as run:
                report = check(output, "iphoneos", attempt_kernel=True)
            self.assertEqual(run.call_count, 1)
            self.assertFalse(report["headers_exported"])
            self.assertFalse(report["configuration_generated"])

    def test_successful_make_without_exported_headers_is_not_green(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.ready_environment(output), \
                    patch("tools.check_xnu_build.run_phase", return_value={"exit_code": 0, "stopped_by": None}), \
                    patch("tools.check_xnu_build.inspect_headers", side_effect=ValueError("missing headers")):
                report = check(output, "iphoneos", attempt_kernel=True)
            self.assertIn("missing headers", report["blockers"])
            self.assertFalse(report["headers_exported"])

    def test_configuration_only_never_compiles_or_claims_kernel_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.ready_environment(output), \
                    patch("tools.check_xnu_build.run_phase", return_value={"exit_code": 0, "stopped_by": None}) as run:
                report = check(output, "iphoneos")
            self.assertEqual(run.call_count, 2)
            self.assertTrue(report["pipeline_passed"])
            self.assertTrue(report["configuration_generated"])
            self.assertFalse(report["kernel_built"])
            self.assertFalse(report["boot_approved"])

    def test_wrong_generated_configuration_blocks_kernel_compilation(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.ready_environment(output), \
                    patch("tools.check_xnu_build.run_phase", return_value={"exit_code": 0, "stopped_by": None}) as run, \
                    patch("tools.check_xnu_build.verify_generated", side_effect=ValueError("entry source absent")):
                report = check(output, "iphoneos", attempt_kernel=True)
            self.assertEqual(run.call_count, 2)
            self.assertTrue(report["headers_exported"])
            self.assertFalse(report["configuration_generated"])
            self.assertFalse(report["kernel_built"])

    def test_zero_build_exit_without_kernel_binary_is_not_green(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.ready_environment(output), \
                    patch("tools.check_xnu_build.run_phase", return_value={"exit_code": 0, "stopped_by": None}) as run:
                report = check(output, "iphoneos", attempt_kernel=True)
            self.assertEqual(run.call_count, 3)
            self.assertFalse(report["pipeline_passed"])
            self.assertFalse(report["kernel_built"])

    def test_iig_abi_failure_stops_before_kernel_compile(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with self.ready_environment(output), \
                    patch("tools.check_xnu_build.run_phase", return_value={"exit_code": 0, "stopped_by": None}) as run, \
                    patch("tools.check_xnu_build.inspect_iig_abi", return_value={"compatible": False}):
                report = check(output, "iphoneos", attempt_kernel=True)
            self.assertEqual(run.call_count, 2)
            self.assertFalse(report["kernel_built"])
            self.assertFalse(report["pipeline_passed"])
            self.assertIn("matching generator", report["blockers"][0])

    def test_mock_structural_kernel_success_is_never_boot_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            kernel = output / "build/obj/DEVELOPMENT_ARM64_MIDO/mach.development.mido"
            kernel.parent.mkdir(parents=True)
            kernel.write_bytes(b"synthetic test fixture, not a kernel")
            with self.ready_environment(output), \
                    patch("tools.check_xnu_build.run_phase", return_value={"exit_code": 0, "stopped_by": None}), \
                    patch("tools.check_xnu_build.inspect", return_value={"boot_approved": False}):
                report = check(output, "iphoneos", attempt_kernel=True)
            self.assertTrue(report["kernel_built"])
            self.assertTrue(report["pipeline_passed"])
            self.assertFalse(report["boot_approved"])
            self.assertFalse(report["platform_memory_approved"])

    def test_kernel_inspection_failure_is_not_kernel_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            kernel = output / "build/obj/DEVELOPMENT_ARM64_MIDO/mach.development.mido"
            kernel.parent.mkdir(parents=True)
            kernel.write_bytes(b"invalid Mach-O")
            with self.ready_environment(output), \
                    patch("tools.check_xnu_build.run_phase", return_value={"exit_code": 0, "stopped_by": None}):
                report = check(output, "iphoneos", attempt_kernel=True)
            self.assertFalse(report["kernel_built"])

    def test_header_checks_reject_missing_and_empty_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            build = Path(temporary)
            with self.assertRaises(ValueError):
                inspect_headers(build)
            for relative in HEADER_FILES:
                path = build / "obj/EXPORT_HDRS" / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"synthetic header")
            self.assertEqual(len(inspect_headers(build)), len(HEADER_FILES))
            (build / "obj/EXPORT_HDRS" / HEADER_FILES[0]).write_bytes(b"")
            with self.assertRaisesRegex(ValueError, "empty"):
                inspect_headers(build)

    def test_exhausted_budget_never_starts_process(self):
        with patch("tools.check_xnu_build.time.monotonic", return_value=181), \
                patch("tools.check_xnu_build.run_make") as run:
            result = run_phase(["make"], Path("source"), {}, Path("log"), 0)
        run.assert_not_called()
        self.assertFalse(succeeded(result))

    def test_remaining_budget_is_forwarded_to_process_group_runner(self):
        with patch("tools.check_xnu_build.time.monotonic", return_value=160), \
                patch("tools.check_xnu_build.run_make", return_value={"exit_code": 0, "stopped_by": None}) as run:
            result = run_phase(["make"], Path("source"), {}, Path("log"), 0)
        self.assertEqual(run.call_args.kwargs["timeout"], 20)
        self.assertTrue(succeeded(result))

    def test_only_kernel_phase_receives_larger_bounded_diagnostic_capture(self):
        for phase, limit in (("build", 16 * 1024 * 1024), ("exporthdrs", 4 * 1024 * 1024)):
            with self.subTest(phase=phase), patch("tools.check_xnu_build.time.monotonic", return_value=20), \
                    patch("tools.check_xnu_build.run_make", return_value={"exit_code": 0, "stopped_by": None}) as run:
                run_phase(["make", phase], Path("source"), {}, Path("log"), 0)
            self.assertEqual(run.call_args.kwargs["timeout"], 90)
            self.assertEqual(run.call_args.kwargs["log_limit"], limit)


if __name__ == "__main__":
    unittest.main()
