"""Real MIDO header/configuration stages and an optional bounded kernel build attempt."""

import argparse
import hashlib
import json
from pathlib import Path
import os
import re
import shutil
import struct
import sys
import time

try:
    from tools.stage_mido_runtime import stage_runtime
    from tools.check_xnu_setup import check as setup, setup_command
    from tools.check_xnu_build_graph import clean_environment, run_make, LOG_LIMIT, MAX_LOG_LIMIT
    from tools.check_mido_headers import verify_generated
    from tools.backport_iig_output import install_hook
    from tools.repair_xnu_formats import stage_format_repairs
    from tools.repair_xnu_aggregates import stage_aggregate_repairs
    from tools.repair_xnu_switches import stage_switch_repairs
    from tools.repair_xnu_network_gates import stage_network_gates
    from tools.repair_xnu_platform_gates import stage_platform_gates
    from tools.repair_xnu_trace_formats import stage_trace_formats
    from tools.repair_xnu_core_diagnostics import stage_core_diagnostics
    from tools.repair_xnu_network_types import stage_network_types
    from tools.repair_xnu_optional_defaults import stage_optional_defaults
    from tools.repair_xnu_scalar_cookies import stage_scalar_cookies
    from tools.repair_xnu_packet_classes import stage_packet_classes
    from tools.configure_xnu_diagnostics import configure_warning_policy, enable_firehose_spi, stage_firehose_header, remove_firehose_link_flag
except ModuleNotFoundError:
    from stage_mido_runtime import stage_runtime
    from check_xnu_setup import check as setup, setup_command
    from check_xnu_build_graph import clean_environment, run_make, LOG_LIMIT, MAX_LOG_LIMIT
    from check_mido_headers import verify_generated
    from backport_iig_output import install_hook
    from repair_xnu_formats import stage_format_repairs
    from repair_xnu_aggregates import stage_aggregate_repairs
    from repair_xnu_switches import stage_switch_repairs
    from repair_xnu_network_gates import stage_network_gates
    from repair_xnu_platform_gates import stage_platform_gates
    from repair_xnu_trace_formats import stage_trace_formats
    from repair_xnu_core_diagnostics import stage_core_diagnostics
    from repair_xnu_network_types import stage_network_types
    from repair_xnu_optional_defaults import stage_optional_defaults
    from repair_xnu_scalar_cookies import stage_scalar_cookies
    from repair_xnu_packet_classes import stage_packet_classes
    from configure_xnu_diagnostics import configure_warning_policy, enable_firehose_spi, stage_firehose_header, remove_firehose_link_flag


PIPELINE_TIMEOUT = 650
HEADER_FILES = ("osfmk/arm64/proc_reg.h", "pexpert/pexpert/arm64/boot.h", "osfmk/mach/mach_types.h")
MAKE_DEFINITIONS_SHA256 = "cdaceff9ef17a85b066b7bacbf4290c04ca4c4f1a5a81b932af76d4c754cc2a6"
OBSOLETE_INIT_FLAG = b"-enable-trivial-auto-var-init-zero-knowing-it-will-be-removed-from-clang"


def modernize_frontend_flags(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != MAKE_DEFINITIONS_SHA256:
        raise ValueError("unexpected architecture-patched MakeInc.def")
    lines = data.splitlines(keepends=True)
    selected = [line for line in lines if line.strip() == OBSOLETE_INIT_FLAG + bytes((32, 92))]
    if len(selected) != 1 or data.count(b"-ftrivial-auto-var-init=zero") != 1:
        raise ValueError("unexpected zero-initialization flag layout")
    result = b"".join(line for line in lines if line not in selected)
    if OBSOLETE_INIT_FLAG in result or result.count(b"-ftrivial-auto-var-init=zero") != 1:
        raise ValueError("zero-initialization policy was not preserved")
    return result


def prepare_frontend(source):
    path = source / "makedefs/MakeInc.def"
    original = path.read_bytes()
    updated = modernize_frontend_flags(original)
    updated = public_sdk_search_paths(updated)
    updated = modernize_compatibility_warning(updated)
    updated = configure_warning_policy(updated)
    updated = enable_firehose_spi(updated)
    updated = remove_firehose_link_flag(updated)
    firehose_header = stage_firehose_header(source)
    export_report = export_mido_header(source)
    repairs = {}
    for relative, transform in (
        ("security/mac_internal.h", repair_disabled_mac_parameter),
        ("bsd/dev/memdev.c", repair_memory_device_formats),
        ("bsd/dev/unix_startup.c", repair_startup_network_includes),
        ("bsd/sys/uio_internal.h", repair_uio_alignment),
        ("bsd/sys/queue.h", repair_queue_line_formats),
        ("bsd/vfs/vfs_bio.c", repair_vfs_buffer_diagnostics),
        ("bsd/vfs/vfs_cache.c", repair_vfs_cache_diagnostics),
        ("osfmk/arm/pmap/pmap.h", repair_non_pac_pmap_padding),
        ("libkern/libkern/c++/OSMetaClass.h", repair_metaclass_overrides),
        ("osfmk/vm/vm_kern.h", repair_kmem_guard_initializers),
        ("osfmk/kern/kalloc.h", repair_kalloc_initializers),
        ("osfmk/kern/startup.h", repair_tunable_initializers),
        ("bsd/sys/sysctl.h", repair_sysctl_initializers),
        ("bsd/kern/uipc_socket2.c", repair_socket_core_includes),
        ("bsd/kern/socket_flows.c", repair_socket_flow_logging),
        ("osfmk/kern/ast.c", repair_disabled_kperf_ast),
        ("iokit/Kernel/IONVRAM.cpp", repair_nvram_log_prefix),
        ("osfmk/kern/clock.c", repair_clock_microsecond_formats),
        ("osfmk/kern/processor.c", repair_disabled_kperf_timer),
        ("osfmk/arm64/start.s", repair_mido_apple_tunables),
        ("bsd/sys/vnode_internal.h", repair_vnode_argument_offsets),
        ("bsd/kern/qsort.c", repair_qsort_alignment),
    ):
        target = source / relative
        before = target.read_bytes()
        after = transform(before)
        target.write_bytes(after)
        repairs[relative] = {"original_sha256": hashlib.sha256(before).hexdigest(),
                             "updated_sha256": hashlib.sha256(after).hexdigest()}
    format_repairs = stage_format_repairs(source)
    switch_repairs = stage_switch_repairs(source)
    aggregate_repairs = stage_aggregate_repairs(source)
    network_gates = stage_network_gates(source)
    platform_gates = stage_platform_gates(source)
    trace_formats = stage_trace_formats(source)
    core_diagnostics = stage_core_diagnostics(source)
    network_types = stage_network_types(source)
    optional_defaults = stage_optional_defaults(source)
    scalar_cookies = stage_scalar_cookies(source)
    packet_classes = stage_packet_classes(source)
    runtime = stage_runtime(source)
    path.write_bytes(updated)
    return {"original_sha256": hashlib.sha256(original).hexdigest(),
            "updated_sha256": hashlib.sha256(updated).hexdigest(),
            "removed_flag": OBSOLETE_INIT_FLAG.decode(), "zero_initialization_preserved": True,
            "warning_flags_relaxed": True, "sdk_modified": False,
            "disabled_warning": "pre-c11-compat", "werror_preserved": False,
            "nonfatal_warnings": ["unused-but-set-variable", "pointer-to-int-cast"],
            "firehose_header": firehose_header, "firehose_spi_enabled": True,
            "nonfatal_warning": "cast-function-type-strict",
            "mido_header_export": export_report,
            "parseable_fixits": False, "compact_diagnostics": True,
            "source_repairs": repairs, "format_repairs": format_repairs,
            "aggregate_repairs": aggregate_repairs, "switch_repairs": switch_repairs,
            "network_gates": network_gates, "platform_gates": platform_gates,
            "trace_formats": trace_formats, "core_diagnostics": core_diagnostics,
            "network_types": network_types, "optional_defaults": optional_defaults,
            "scalar_cookies": scalar_cookies, "packet_classes": packet_classes,
            "mido_runtime": runtime}


def repair_vnode_argument_offsets(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "d535fde0a15f480bd4ade024de39d3084476835ca0065ab295e51b511a131ed4":
        raise ValueError("unexpected vnode offset source")
    original = b"((int) (((char *) (&(((p_type)NULL)->field))) - ((char *) NULL)))"
    if data.count(original) != 1:
        raise ValueError("unexpected vnode argument offset layout")
    return data.replace(original, b"((int)__builtin_offsetof(__typeof__(*(p_type)NULL), field))")


def repair_qsort_alignment(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "cc113c8ed0a9158a9c657cf1c30181f4205bbc822453bde39258f9367dff5fe5":
        raise ValueError("unexpected qsort source")
    original = b"((char *)a - (char *)0) % sizeof(long)"
    if data.count(original) != 1:
        raise ValueError("unexpected qsort alignment layout")
    return data.replace(original, b"((uintptr_t)(a)) % sizeof(long)")


def repair_disabled_kperf_timer(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "45247c10581a8b895ac1311d2533ccff0c59fcd3af1b8917ff35d640c8de6e79":
        raise ValueError("unexpected processor timer source")
    original = b"\t[RUNNING_TIMER_KPERF] = kperf_timer_expire,\n"
    if data.count(original) != 1:
        raise ValueError("unexpected processor timer table")
    return data.replace(original, b"#if KPERF\n" + original + b"#endif\n")


def repair_mido_apple_tunables(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "bf92967ea96e638f5a9a002cd4e478272f08616531d212caa919944c85e8a023":
        raise ValueError("unexpected ARM64 startup source")
    for original in (b"#include <arm64/tunables/tunables.s>\n",
                     b"\tAPPLY_TUNABLES x12, x13, x14\n"):
        if data.count(original) != 1:
            raise ValueError("unexpected Apple tunable layout")
        data = data.replace(original, b"#if !defined(MIDO)\n" + original + b"#endif\n")
    return data


def repair_clock_microsecond_formats(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "001630fcf2089f7f8df7c39ee79f8ba9279b84aa06ec5d8883b016eb15fdc5b1":
        raise ValueError("unexpected clock diagnostic source")
    if data.count(b"%d") != 21:
        raise ValueError("unexpected clock microsecond format count")
    return data.replace(b"%d", b"%u")


def repair_nvram_log_prefix(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "ba6d8e74eb5b920a92a18236eed56b7dc95afd09da95116d3d52935714b2cc03":
        raise ValueError("unexpected NVRAM logging source")
    original = b'IOLog("%s:%s:%u - " fmt, __FILE_NAME__, __FUNCTION__, __LINE__, ##args);'
    if data.count(original) != 3:
        raise ValueError("unexpected NVRAM logging prefix layout")
    return data.replace(original, original.replace(b"__LINE__,", b"(unsigned int)__LINE__,"))


def repair_socket_core_includes(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "0eb60e42e57257412c7f822f6b3f5d1487adf724b7782cf52df07b4a7f95d9ac":
        raise ValueError("unexpected socket core source")
    original = b"#include <net/route.h>"
    if data.count(original) != 1:
        raise ValueError("unexpected socket core include layout")
    return data.replace(original, b"#include <net/if_var.h>\n#include <os/log.h>\n" + original)


def repair_socket_flow_logging(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "c14cb48ccae48a321e7e23d01e7c8011e623e070ece9eda68736e7caed16f7ff":
        raise ValueError("unexpected socket flow source")
    original = b"#include <sys/socketvar.h>"
    if data.count(original) != 1:
        raise ValueError("unexpected socket flow include layout")
    return data.replace(original, original + b"\n#include <os/log.h>")


def repair_disabled_kperf_ast(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "2667cac493a5a59c14647bf0652b310de98b2e66d97c225f36fcead39c703c0d":
        raise ValueError("unexpected AST source")
    header = b"#include <kperf/kperf_kpc.h>"
    callback = (b"\tif (reasons & AST_KPERF) {\n"
                b"\t\tthread_ast_clear(thread, AST_KPERF);\n"
                b"\t\tkperf_kpc_thread_ast(thread);\n\t}")
    for original in (header, callback):
        if data.count(original) != 1:
            raise ValueError("unexpected KPERF AST layout")
        data = data.replace(original, b"#if KPERF && KPC\n" + original + b"\n#endif")
    return data


def repair_tunable_initializers(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "41afcc8be3e13b2e865fa55be1da100894c74cbd84023ef781392efa746d75f5":
        raise ValueError("unexpected startup tunable header")
    boolean = b".var_is_bool = __startup_type_is_bool(type_t), " + bytes((92,)) + b"\n"
    string = b".var_is_str = true, " + bytes((92,)) + b"\n"
    if data.count(boolean) != 2 or data.count(string) != 1:
        raise ValueError("unexpected tunable initializer layout")
    data = data.replace(boolean, boolean + b"\t        .var_is_str = false, " + bytes((92,)) + b"\n", 1)
    return data.replace(string, b".var_is_bool = false, " + bytes((92,)) + b"\n\t        " + string)


def repair_sysctl_initializers(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "c8e3ae8a6a560c9d6abcad2f2ea83fe377f9f962179f28c30baab87c002477f4":
        raise ValueError("unexpected sysctl header")
    parent = b".oid_parent     = &sysctl_##parent##_children,"
    version = b".oid_version    = SYSCTL_OID_VERSION,"
    if data.count(parent) != 1 or data.count(version) != 2:
        raise ValueError("unexpected sysctl initializer layout")
    data = data.replace(parent, parent + b" " + bytes((92,)) + b"\n\t    .oid_link = { .sle_next = NULL },")
    return data.replace(version, version + b" " + bytes((92,)) + b"\n\t    .oid_refcnt = 0,", 1)


def repair_kmem_guard_initializers(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "f65a4aefbbd0901ec16b39c8d78bcb8c43ea2a2bb7f9f2fbbc5a22d94e6a2ae1":
        raise ValueError("unexpected VM allocation header")
    original = b"kmem_guard_t guard = {\n\t\t.kmg_tag = tag,\n\t};"
    if data.count(original) != 2:
        raise ValueError("unexpected VM guard initializer layout")
    replacement = (b"kmem_guard_t guard = {\n\t\t.kmg_tag = tag,\n\t\t.kmg_type_hash = 0,\n"
                   b"\t\t.kmg_atomic = 0,\n\t\t.kmg_submap = 0,\n\t\t.kmg_context = 0,\n\t};")
    return data.replace(original, replacement)


def repair_kalloc_initializers(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "34289216bd95d4691f407996c97d5a64d665153b5470e605ec9391bf1661edd3":
        raise ValueError("unexpected typed allocation header")
    start = data.index(b"#define _KALLOC_TYPE_DEFINE(var, type, flags)")
    end = data.index(b"#ifndef XNU_KERNEL_PRIVATE", start)
    macros = data[start:end]
    continuation = b" " + bytes((92,)) + b"\n"
    additions = (
        b"#if XNU_KERNEL_PRIVATE\n"
        b"#define KALLOC_TYPE_ZERO_SHARED_ZONES .kt_zshared = NULL, .kt_zsig = NULL,\n"
        b"#else\n"
        b"#define KALLOC_TYPE_ZERO_SHARED_ZONES .unused1 = NULL, .unused2 = NULL,\n"
        b"#endif\n\n"
    )
    replacements = (
        (rb"(?m)^(\s*\.kt_signature = KALLOC_TYPE_EMIT_SIG\(type\),[^\n]*\n)",
         b"    KALLOC_TYPE_ZERO_SHARED_ZONES" + continuation),
        (rb"(?m)^(\s*\.kt_version = KT_V1,[^\n]*\n)",
         b"    .kt_stats = NULL, .kt_next = NULL, .kt_heap_start = 0, .kt_zones = {0}," + continuation),
    )
    for pattern, addition in replacements:
        macros, count = re.subn(pattern, lambda match: match[0] + addition, macros)
        if count != (1 if b"kt_signature" in pattern else 2):
            raise ValueError("unexpected typed allocation initializer layout")
    pattern = rb"(?m)^(\s*\.kt_size_type = sizeof\(type\),[^\n]*\n)(\s*\.kt_sig_type = KALLOC_TYPE_EMIT_SIG\(type\),)"
    macros, count = re.subn(pattern, lambda match: match[1] +
                           b"    .kt_size_hdr = 0, .kt_sig_hdr = NULL," + continuation + match[2], macros)
    if count != 1:
        raise ValueError("unexpected headerless allocation initializer layout")
    return data[:start] + additions + macros + data[end:]


def repair_metaclass_overrides(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "0b47cb07db5854013123fce2972592d63997c8a7bced80b7365bb04af4614647":
        raise ValueError("unexpected metaclass header")
    declarations = (
        b"virtual void retain() const;", b"virtual void release() const;",
        b"virtual void release(int freeWhen) const;",
        b"virtual void taggedRetain(const void * tag = NULL) const;",
        b"virtual void taggedRelease(const void * tag = NULL) const;",
        b"const int    freeWhen) const;", b"virtual int getRetainCount() const;",
        b"virtual const OSMetaClass * getMetaClass() const;", b"~OSMetaClass();",
        b"virtual bool serialize(OSSerialize * serializer) const;",
    )
    for declaration in declarations:
        if data.count(declaration) != 1:
            raise ValueError("unexpected metaclass override layout")
        data = data.replace(declaration, declaration[:-1] + b" override;")
    return data


def repair_non_pac_pmap_padding(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "228414f8405c12ae2021fbfb1d53c37d7509fa6b7afa97a78ba4a5eef48f2cde":
        raise ValueError("unexpected pmap header")
    original = b"#else\n\tbool reserved10;\n#endif /* HAS_APPLE_PAC */"
    if data.count(original) != 1:
        raise ValueError("unexpected non-PAC padding layout")
    return data.replace(original, original.replace(b"reserved10", b"reserved_no_pac"))


def repair_disabled_mac_parameter(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "3f9400087ac1b680fc225b54b8449f03db429a989156eeea46ceff318f90b873":
        raise ValueError("unexpected MAC internal header")
    original = b"return cred != proc_ucred(kernproc);\n#else\n#pragma unused(p)"
    if data.count(original) != 1:
        raise ValueError("unexpected disabled MAC parameter layout")
    return data.replace(original, original.replace(b"unused(p)", b"unused(cred)"))


def repair_memory_device_formats(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "1caae0b366a8d7d254222cbf1433134b0e925e1114898822a145237a8dc5011a":
        raise ValueError("unexpected memory device source")
    replacements = {
        b'memory device: %08X", devid);': b'memory device: %08X", (unsigned int)devid);',
        b"devid, devid, mdev[devid].mdBDev, mdev[devid].mdCDev, base << 12":
            b"(unsigned int)devid, (unsigned int)devid, (unsigned int)mdev[devid].mdBDev, (unsigned int)mdev[devid].mdCDev, base << 12",
    }
    for original, replacement in replacements.items():
        if data.count(original) != (2 if original.startswith(b"memory device:") else 1):
            raise ValueError("unexpected memory device format layout")
        data = data.replace(original, replacement)
    return data


def repair_startup_network_includes(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "81ca252a6b13082cc7db4c8cdce86cc5adf8b3356ac490452265084d6fa8e1a2":
        raise ValueError("unexpected BSD startup source")
    original = b"#include <netinet/tcp_var.h>"
    if data.count(original) != 1:
        raise ValueError("unexpected BSD startup include layout")
    return data.replace(original, b"#include <net/if_var.h>\n" + original)


def repair_uio_alignment(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "f0351f1b7dda1fb5b7cf25bf8dc37129b35f5f1fb48f5fd194beb612ddef3e1c":
        raise ValueError("unexpected UIO internal header")
    original = b"typedef char __attribute__((aligned(_Alignof(union iovecs)))) uio_stackbuf_t;"
    if data.count(original) != 1:
        raise ValueError("unexpected UIO alignment layout")
    return data.replace(original, b"#define uio_stackbuf_t _Alignas(union iovecs) char")


def repair_queue_line_formats(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "cc64e15ab2e5f2e0b70269305f3acf987c3f375f660af68d81cc012de2b7a2c6":
        raise ValueError("unexpected queue header")
    if data.count(b", __LINE__);") != 9:
        raise ValueError("unexpected queue diagnostic layout")
    return data.replace(b", __LINE__);", b", (unsigned int)__LINE__);")


def repair_vfs_buffer_diagnostics(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "44f5b06714838ea3b21df96c922f3c077b8ca8f145a2cee8b080a61706494ae2":
        raise ValueError("unexpected VFS buffer source")
    if data.count(b'%x", operation);') != 2:
        raise ValueError("unexpected VFS operation diagnostics")
    data = data.replace(b'%x", operation);', b'%x", (unsigned int)operation);')
    original = b"case BUF_CLAIMED_DONE:\n\t\t\t\tlck_mtx_lock(&buf_mtx);\n\t\t\t\tgoto out;"
    if data.count(original) != 1:
        raise ValueError("unexpected VFS callback switch")
    return data.replace(original, original + b'\n\t\t\tdefault:\n\t\t\t\tpanic("buf_iterate: invalid callout result %d", retval);')


def repair_vfs_cache_diagnostics(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != "a22925bf8bb138da4990fa1d22bc25b91425d5675225c12571cf099d5dc7a60e":
        raise ValueError("unexpected VFS cache source")
    replacements = {
        b"major(vp->v_rdev), minor(vp->v_rdev));":
            b"(unsigned int)major(vp->v_rdev), (unsigned int)minor(vp->v_rdev));",
        b"old nc_counter(%d)": b"old nc_counter(%u)",
        b"\tuint32_t          chain_len = 0;\n": b"",
        b"chain_len++, entry = entry->hash_chain.le_next": b"entry = entry->hash_chain.le_next",
    }
    for original, replacement in replacements.items():
        if data.count(original) != (2 if original == b"old nc_counter(%d)" else 1):
            raise ValueError("unexpected VFS cache diagnostic layout")
        data = data.replace(original, replacement)
    return data


def modernize_compatibility_warning(data):
    original = b"-Wno-c++98-compat " + bytes((92,))
    if data.count(original) != 1:
        raise ValueError("unexpected compatibility warning layout")
    additions = (b"\n\t-Wno-pre-c11-compat " + bytes((92,))
                 + b"\n\t-Wno-error=cast-function-type-strict " + bytes((92,))
                 + b"\n\t-fno-caret-diagnostics " + bytes((92,))
                 + b"\n\t-fmacro-backtrace-limit=2 " + bytes((92,)))
    return data.replace(original, original + additions)


def export_mido_header(source):
    path = source / "pexpert/pexpert/arm64/Makefile"
    original = path.read_bytes().replace(b"\r\n", b"\n")
    expected = "0d24437f9af00daca441365d90f44b8f909e14e10c6e7e26a30a8010da06740d"
    if hashlib.sha256(original).hexdigest() != expected or original.count(b"\tBCM2837.h\n") != 1:
        raise ValueError("unexpected pexpert header export Makefile")
    header = source / "pexpert/pexpert/arm64/MIDO.h"
    if not header.is_file() or not header.read_bytes():
        raise ValueError("missing real MIDO header")
    updated = original.replace(b"\tBCM2837.h\n", b"\tMIDO.h " + bytes((92,)) + b"\n\tBCM2837.h\n")
    path.write_bytes(updated)
    return {"original_sha256": expected, "updated_sha256": hashlib.sha256(updated).hexdigest(),
            "header_sha256": hashlib.sha256(header.read_bytes()).hexdigest()}


def public_sdk_search_paths(data):
    replacements = {
        b"$(patsubst %, -I$(OBJROOT)/EXPORT_HDRS/%, $(COMPONENT_IMPORT_LIST))":
            b"$(foreach component,$(COMPONENT_IMPORT_LIST),$(if $(filter libsa,$(component)),$(addprefix -I,$(wildcard $(OBJROOT)/EXPORT_HDRS/libsa)),-I$(OBJROOT)/EXPORT_HDRS/$(component)))",
        b"-I$(SDKROOT)/usr/local/include/kernel":
            b"$(addprefix -I,$(wildcard $(SDKROOT)/usr/local/include/kernel))",
        b"-I$(SDKROOT)/$(KPINCDIR)/platform":
            b"$(addprefix -I,$(wildcard $(SDKROOT)/$(KPINCDIR)/platform))",
    }
    for original, replacement in replacements.items():
        if data.count(original) != 1:
            raise ValueError("unexpected optional include search-path layout")
        data = data.replace(original, replacement)
    return data


def phase_command(source, build, sdk, availability, target):
    if target not in ("exporthdrs", "build"):
        raise ValueError("unsupported build phase")
    command = setup_command(source, build, sdk)
    command[-1] = target
    command.insert(-1, f"MIDO_AVAILABILITY_PL={availability}")
    command.insert(-1, "BUILD_WERROR=0")
    command.insert(-1, "WERROR=")
    return command


def configuration_command(source, generated, sdk):
    if sdk not in ("iphoneos", "macosx"):
        raise ValueError("unsupported SDK")
    return [str(source / "SETUP/config/doconf"), "-c", "-cpu", "arm64", "-soc", "mido",
            "-platform", "iPhoneOS" if sdk == "iphoneos" else "MacOSX", "-d", str(generated),
            "-s", str(source / "osfmk/conf"), "-m", str(source / "config"), "DEVELOPMENT"]


def run_phase(command, source, environment, log, started):
    remaining = PIPELINE_TIMEOUT - (time.monotonic() - started)
    if remaining <= 0:
        return {"exit_code": None, "stopped_by": "pipeline time budget exhausted"}
    try:
        log_limit = MAX_LOG_LIMIT if command[-1] == "build" else LOG_LIMIT
        phase_timeout = 600 if command[-1] == "build" else 90
        return run_make(command, source, environment, log, timeout=min(phase_timeout, remaining), log_limit=log_limit)
    except OSError as error:
        return {"exit_code": None, "stopped_by": str(error)}


def succeeded(result):
    return result["exit_code"] == 0 and not result["stopped_by"]


def compiled_objects(build):
    root = build / "obj/DEVELOPMENT_ARM64_MIDO"
    objects = []
    bitcode = []
    for path in sorted(root.rglob("*.o")):
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError("escaped kernel object")
        with path.open("rb") as stream:
            header = stream.read(16)
        if len(header) == 16 and struct.unpack("<4I", header) == (0xFEEDFACF, 0x0100000C, 0, 1):
            objects.append(str(path.relative_to(root)))
        elif header[:4] in (b"BC\xc0\xde", b"\xde\xc0\x17\x0b"):
            bitcode.append(str(path.relative_to(root)))
    return {"arm64_mach_o_object_count": len(objects), "sample_paths": objects[:30],
            "llvm_bitcode_file_count": len(bitcode), "bitcode_sample_paths": bitcode[:30],
            "bitcode_target_verified": False}


def inspect_headers(build):
    exported = build / "obj/EXPORT_HDRS"
    records = {}
    for relative in HEADER_FILES:
        path = exported / relative
        if not path.is_file() or not path.resolve().is_relative_to(build.resolve()):
            raise ValueError(f"expected exported header missing or outside build: {relative}")
        data = path.read_bytes()
        if not data:
            raise ValueError(f"empty exported header: {relative}")
        records[relative] = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    return records


def inspect_iig_references(data):
    patterns = {
        "invocation_field": rb"const struct \w+_Msg_Content\s*\*\s*kernelContent\s*;",
        "message_lookup": rb"IORPCMessage\s*\*\s*msg\s*=\s*rpc\.kernelContent\s*;",
        "rpc_initializer": rb"\.kernelContent\s*=\s*&buf\.msg\.content\.__hdr",
        "typed_message_lookup": rb"const \w+_Msg_Content\s*\*\s*messageContent\s*=\s*rpc\.kernelContent\s*;",
    }
    records = []
    for number, line in enumerate(data.splitlines(), 1):
        if b"kernelContent" not in line:
            continue
        matches = [role for role, pattern in patterns.items() if re.search(pattern, line)]
        role = matches[0] if len(matches) == 1 and line.count(b"kernelContent") == 1 else "unclassified"
        records.append({"line": number, "role": role})
    return {"references": records,
            "unclassified_lines": [record["line"] for record in records if record["role"] == "unclassified"],
            "scope": "lexical inventory only; not a transform or ABI approval"}


def inspect_iig_abi(source, build):
    header = (source / "iokit/IOKit/IORPC.h").read_bytes()
    declaration = re.search(rb"struct IORPC\s*\{([^}]+)\};", header)
    if declaration is None:
        raise ValueError("IORPC ABI declaration missing")
    implementations = sorted(build.rglob("OSObject.iig.cpp"))
    if not implementations or len(implementations) > 16:
        raise ValueError("expected bounded real OSObject IIG output")
    records = []
    for path in implementations:
        if path.is_symlink() or not path.resolve().is_relative_to(build.resolve()) or path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("unsafe or oversized IIG output")
        data = path.read_bytes()
        if not data:
            raise ValueError("empty IIG implementation")
        records.append({"path": str(path.relative_to(build)), "sha256": hashlib.sha256(data).hexdigest(),
                        "kernelContent_occurrences": data.count(b"kernelContent"),
                        "reference_inventory": inspect_iig_references(data)})
    header_support = b"kernelContent" in declaration[1]
    return {"compatible": header_support or not any(record["kernelContent_occurrences"] for record in records),
            "header_has_kernelContent": header_support,
            "header_sha256": hashlib.sha256(header).hexdigest(), "implementations": records,
            "scope": "kernelContent ABI mismatch check only, not complete RPC validation"}


def save_kernel_artifact(build, output, sdk):
    if sdk not in ("iphoneos", "macosx"):
        raise ValueError("unsupported kernel artifact SDK")
    name = "mach" if sdk == "iphoneos" else "kernel"
    kernel = build / f"obj/DEVELOPMENT_ARM64_MIDO/{name}.development.mido"
    if not kernel.exists() and not kernel.is_symlink():
        kernel = kernel.with_name(kernel.name + ".unstripped")
    if (kernel.is_symlink() or not kernel.is_file() or
            not kernel.resolve().is_relative_to(build.resolve()) or
            not 0 < kernel.stat().st_size <= 128 * 1024 * 1024):
        raise ValueError("missing, escaped, empty or oversized kernel output")
    destination = output / kernel.name
    if destination.exists() or destination.is_symlink():
        raise ValueError("refusing to replace existing kernel artifact")
    shutil.copyfile(kernel, destination)
    return {"source": str(kernel), "path": str(destination), "bytes": destination.stat().st_size,
            "boot_approved": False, "platform_memory_approved": False}


def check(output, sdk, archive=None, attempt_kernel=False, reviewed_rpc=False, experimental_boot_crypto=False,
          mido_no_image4_boot=False, experimental_irq_timer=False, experimental_boot_checkpoints=False,
          experimental_mapped_checkpoint=False, experimental_platform_expert=False, experimental_pthread=False,
          experimental_memory_root=False, experimental_mockfs=False, experimental_entitlement_guard=False,
          experimental_native_4k=False):
    if experimental_entitlement_guard and not experimental_mockfs:
        raise ValueError("entitlement guard requires explicit mockfs diagnostics")
    if experimental_mockfs and not experimental_memory_root:
        raise ValueError("mockfs diagnostics require explicit memory-root diagnostics")
    if experimental_memory_root and not experimental_platform_expert:
        raise ValueError("memory-root diagnostics require the explicit diagnostic platform")
    if experimental_pthread and not experimental_platform_expert:
        raise ValueError("diagnostic pthread requires the explicit diagnostic platform")
    if experimental_platform_expert and not (experimental_boot_crypto and experimental_irq_timer and mido_no_image4_boot):
        raise ValueError("diagnostic platform requires explicit bootstrap crypto, IRQ timer and non-Apple startup")
    if experimental_mapped_checkpoint and not experimental_boot_crypto:
        raise ValueError("mapped checkpoint requires the explicit bootstrap crypto build")
    if experimental_boot_checkpoints and not experimental_boot_crypto:
        raise ValueError("boot checkpoints require the explicit bootstrap crypto build")
    if experimental_irq_timer and not experimental_boot_crypto:
        raise ValueError("IRQ timer diagnostics require the explicit bootstrap crypto build")
    if mido_no_image4_boot and not experimental_boot_crypto:
        raise ValueError("non-Apple bootstrap requires explicit experimental bootstrap crypto")
    if experimental_boot_crypto and (not attempt_kernel or sdk != "iphoneos"):
        raise ValueError("bootstrap crypto requires an explicit iphoneos kernel attempt")
    if reviewed_rpc and not attempt_kernel:
        raise ValueError("reviewed RPC adaptation requires an explicit kernel attempt")
    started = time.monotonic()
    setup_report = setup(output, sdk, archive, execute_setup=True, open_availability=True)
    output = output.resolve()
    source = output / "source"
    build = output / "build"
    generated = build / "obj/DEVELOPMENT_ARM64_MIDO/osfmk/DEVELOPMENT"
    environment = clean_environment(os.environ)
    environment.update(SRCROOT=str(source), OBJROOT=str(build / "obj"))
    report = {"purpose": "real header export/configuration and optional kernel compilation attempt, NOT boot approval",
              "setup_passed": setup_report["setup_passed"], "sdk": sdk,
              "attempt_kernel_requested": attempt_kernel, "phases": {}, "exported_headers": {},
              "generated_configuration": {}, "headers_exported": False, "configuration_generated": False,
              "kernel_built": False, "boot_approved": False, "platform_memory_approved": False,
              "blockers": [], "kernel_inspection": None, "kernel_artifact": None,
              "kernel_inspection_deferred": True, "frontend_compatibility": None}
    rpc_options = []
    try:
        if not setup_report["setup_passed"]:
            raise ValueError("host setup did not pass; inspect setup-report.json")
        if attempt_kernel:
            report["frontend_compatibility"] = prepare_frontend(source)
        if experimental_native_4k:
            try:
                from tools.stage_mido_native_4k import stage_native_4k
            except ModuleNotFoundError:
                from stage_mido_native_4k import stage_native_4k
            report["experimental_native_4k"] = stage_native_4k(source)
        if experimental_memory_root:
            try:
                from tools.stage_mido_memory_root import stage_memory_root
            except ModuleNotFoundError:
                from stage_mido_memory_root import stage_memory_root
            report["experimental_memory_root"] = stage_memory_root(source)
        if experimental_mockfs:
            try:
                from tools.stage_mido_mockfs import stage_mockfs
            except ModuleNotFoundError:
                from stage_mido_mockfs import stage_mockfs
            report["experimental_mockfs"] = stage_mockfs(source)
        if experimental_entitlement_guard:
            try:
                from tools.stage_mido_entitlement_guard import stage_entitlement_guard
            except ModuleNotFoundError:
                from stage_mido_entitlement_guard import stage_entitlement_guard
            report["experimental_entitlement_guard"] = stage_entitlement_guard(source)
        if experimental_pthread:
            try:
                from tools.stage_mido_pthread import stage_pthread
            except ModuleNotFoundError:
                from stage_mido_pthread import stage_pthread
            report["experimental_pthread"] = stage_pthread(source)
        if experimental_platform_expert:
            try:
                from tools.stage_mido_platform_expert import stage_platform_expert
            except ModuleNotFoundError:
                from stage_mido_platform_expert import stage_platform_expert
            report["experimental_platform_expert"] = stage_platform_expert(source)
        if experimental_boot_checkpoints:
            try:
                from tools.stage_mido_boot_checkpoints import stage_boot_checkpoints
            except ModuleNotFoundError:
                from stage_mido_boot_checkpoints import stage_boot_checkpoints
            report["experimental_boot_checkpoints"] = stage_boot_checkpoints(source)
        if experimental_mapped_checkpoint:
            try:
                from tools.stage_mido_mapped_checkpoint import stage_mapped_checkpoint
            except ModuleNotFoundError:
                from stage_mido_mapped_checkpoint import stage_mapped_checkpoint
            report["experimental_mapped_checkpoint"] = stage_mapped_checkpoint(source)
        if experimental_boot_crypto:
            try:
                from tools.stage_mido_boot_crypto import stage_boot_crypto
            except ModuleNotFoundError:
                from stage_mido_boot_crypto import stage_boot_crypto
            report["experimental_boot_crypto"] = stage_boot_crypto(source)
        if experimental_irq_timer:
            try:
                from tools.stage_mido_irq_timer import stage_irq_timer
            except ModuleNotFoundError:
                from stage_mido_irq_timer import stage_irq_timer
            report["experimental_irq_timer"] = stage_irq_timer(source)
        if mido_no_image4_boot:
            try:
                from tools.stage_mido_nonapple_boot import stage_nonapple_boot
            except ModuleNotFoundError:
                from stage_mido_nonapple_boot import stage_nonapple_boot
            report["nonapple_boot"] = stage_nonapple_boot(source)
        if reviewed_rpc:
            report["reviewed_rpc_hook"] = install_hook(source)
            rpc_options = [f"MIDO_RPC_PYTHON={sys.executable}",
                           f"MIDO_RPC_BACKPORT={Path(__file__).with_name('backport_iig_output.py').resolve()}"]
        availability = setup_report["open_availability"]["script_path"]
        command = phase_command(source, build, sdk, availability, "exporthdrs")
        command[-1:-1] = rpc_options
        result = run_phase(command, source, environment, output / "exporthdrs.log", started)
        report["phases"]["exporthdrs"] = {"command": command, "result": result}
        if not succeeded(result):
            raise ValueError("header export failed; inspect exporthdrs.log")
        report["exported_headers"] = inspect_headers(build)
        report["headers_exported"] = True
        generated.mkdir(parents=True, exist_ok=True)
        command = configuration_command(source, generated, sdk)
        configuration_environment = dict(environment, SOURCE=str(source / "osfmk/conf") + "/")
        result = run_phase(command, source, configuration_environment, output / "configuration.log", started)
        report["phases"]["configuration"] = {"command": command, "result": result}
        if not succeeded(result):
            raise ValueError("real doconf/config generation failed; inspect configuration.log")
        report["generated_configuration"] = verify_generated(generated, "DEVELOPMENT")
        report["configuration_generated"] = True
        if attempt_kernel:
            report["iig_abi"] = inspect_iig_abi(source, build)
            if not report["iig_abi"]["compatible"]:
                raise ValueError("IIG emits kernelContent absent from pinned IORPC ABI; matching generator or reviewed RPC backport required")
            command = phase_command(source, build, sdk, availability, "build")
            command[-1:-1] = rpc_options
            result = run_phase(command, source, environment, output / "kernel-build.log", started)
            report["phases"]["build"] = {"command": command, "result": result}
            try:
                report["kernel_artifact"] = save_kernel_artifact(build, output, sdk)
            except (OSError, ValueError) as error:
                report["blockers"].append(f"kernel artifact could not be saved: {error}")
            try:
                report["compiled_objects"] = compiled_objects(build)
            except (OSError, ValueError) as error:
                report["compiled_objects_warning"] = str(error)
            if not succeeded(result):
                raise ValueError("kernel build attempt failed; inspect kernel-build.log")
            report["kernel_built"] = report["kernel_artifact"] is not None
    except (OSError, ValueError) as error:
        report["blockers"].append(str(error))
    report["pipeline_passed"] = (report["configuration_generated"] and not report["blockers"]
                                  and (not attempt_kernel or report["kernel_built"]))
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    (output / "build-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    if sys.platform != "darwin":
        print("Local XNU build is disabled on this host. Use the manual macOS workflow in .github/workflows/build.yml.", file=sys.stderr)
        raise SystemExit(2)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--sdk", choices=("iphoneos", "macosx"), required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--attempt-kernel", action="store_true")
    parser.add_argument("--reviewed-rpc", action="store_true")
    parser.add_argument("--experimental-native-4k", action="store_true",
                        help="Opt in to native 4KiB user page policy; not complete iOS support")
    parser.add_argument("--experimental-boot-crypto", action="store_true",
                        help="Opt in to incomplete, fail-closed bootstrap crypto; not boot approval")
    parser.add_argument("--mido-no-image4-boot", action="store_true",
                        help="Opt in to non-Apple startup only when MIDO already omits Image4")
    parser.add_argument("--experimental-irq-timer", action="store_true",
                        help="Opt in to single-CPU diagnostic GICv2/timer backend; not hardware approval")
    parser.add_argument("--experimental-boot-checkpoints", action="store_true",
                        help="Opt in to pre-MMU MIDO framebuffer checkpoints; not boot approval")
    parser.add_argument("--experimental-mapped-checkpoint", action="store_true",
                        help="Opt in to EARLY_BOOT mapped framebuffer marker; requires explicit DT contract")
    parser.add_argument("--experimental-platform-expert", action="store_true",
                        help="Opt in to synthetic-only diagnostic IOPlatformExpert; no RTC or hardware approval")
    parser.add_argument("--experimental-pthread", action="store_true",
                        help="Opt in to matching open pthread kernel provider; not userspace approval")
    parser.add_argument("--experimental-memory-root", action="store_true",
                        help="Opt in to null RAM-root lifecycle without IOStorageFamily; no mount approval")
    parser.add_argument("--experimental-mockfs", action="store_true",
                        help="Opt in to original single-executable mockfs; not a production filesystem")
    parser.add_argument("--experimental-entitlement-guard", action="store_true",
                        help="Deny boolean entitlements when AMFI is absent; no signature bypass")
    args = parser.parse_args()
    report = check(args.output_directory, args.sdk, args.archive, args.attempt_kernel, args.reviewed_rpc,
                   args.experimental_boot_crypto, args.mido_no_image4_boot, args.experimental_irq_timer,
                   args.experimental_boot_checkpoints, args.experimental_mapped_checkpoint,
                   experimental_platform_expert=args.experimental_platform_expert,
                   experimental_pthread=args.experimental_pthread,
                   experimental_memory_root=args.experimental_memory_root,
                   experimental_mockfs=args.experimental_mockfs,
                   experimental_entitlement_guard=args.experimental_entitlement_guard,
                   experimental_native_4k=args.experimental_native_4k)
    print(json.dumps(report, indent=2))
    for name in ("setup", "exporthdrs", "configuration", "kernel-build"):
        log = args.output_directory / f"{name}.log"
        if log.exists():
            lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
            diagnostics = [line for line in lines if ": error:" in line or ": fatal error:" in line]
            if diagnostics:
                print(f"Compiler errors from all of {name}.log (first 80):")
                print("\n".join(diagnostics[:80]))
            print(f"Last 120 lines of {name}.log:")
            print("\n".join(lines[-120:]))
    if not report["pipeline_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
