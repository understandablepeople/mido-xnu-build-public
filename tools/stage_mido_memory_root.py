"""Opt-in native RAM-root lifecycle when IOStorageFamily is not linked."""

import hashlib


SOURCE_SHA256 = "a31c44293e17bb32cd933cda55838439bff7ddfd7ce2995d91bf959ae85c74fb"
GUARD = b"#if defined(ARM64_BOARD_CONFIG_MIDO) && defined(MIDO_DIAGNOSTIC_MEMORY_ROOT)\n"
BLOCK_LOOKUP = (b"\tioblockstoragedriverClass = OSMetaClass::getMetaClassWithName(gIOBlockStorageDriverKey);\n"
                b"\tassert(ioblockstoragedriverClass);\n")
MEDIA_ASSERT = b"\tassert(iomediaClass);\n"
MEDIA_CONTEXT = b"\tFindRootMediaContext ctx = { .services = NULL, .parent = parent };\n"


def adapt_service(data):
    data = data.replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != SOURCE_SHA256:
        raise ValueError("unexpected prepared IOService memory-root source")
    for anchor in (BLOCK_LOOKUP, MEDIA_ASSERT, MEDIA_CONTEXT):
        if data.count(anchor) != 1:
            raise ValueError("ambiguous memory-root lifecycle anchor")
    data = data.replace(BLOCK_LOOKUP, GUARD + b"\tif (root) {\n#endif\n" + BLOCK_LOOKUP
                        + GUARD + b"\t}\n#endif\n")
    data = data.replace(MEDIA_ASSERT, GUARD + b"\tassert(iomediaClass || !parent);\n#else\n"
                        + MEDIA_ASSERT + b"#endif\n")
    data = data.replace(MEDIA_CONTEXT, GUARD + b"\tif (!iomediaClass) {\n\t\treturn;\n\t}\n#endif\n\n"
                        + MEDIA_CONTEXT)
    return data


def stage_memory_root(source):
    source = source.resolve()
    service = source / "iokit/Kernel/IOService.cpp"
    makefile = source / "iokit/conf/Makefile.arm64"
    configuration = source / "config/MASTER.arm64.MIDO"
    for path in (service, makefile, configuration):
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("escaped MIDO memory-root staging path")
    if b"pseudo-device mido_runtime" not in configuration.read_bytes().splitlines():
        raise ValueError("memory-root diagnostics require MIDO runtime configuration")
    before = service.read_bytes()
    make = makefile.read_bytes().replace(b"\r\n", b"\n")
    if b"MIDO_DIAGNOSTIC_MEMORY_ROOT" in make:
        raise ValueError("memory-root diagnostics already staged")
    after = adapt_service(before)
    service.write_bytes(after)
    makefile.write_bytes(make + b"\nIOService.cpo_CFLAGS_ADD += -DMIDO_DIAGNOSTIC_MEMORY_ROOT=1\n")
    return {"diagnostic_only": True, "null_root_only": True,
            "non_null_storage_class_assertions_preserved": True,
            "root_media_and_visibility_lifecycle_preserved": True,
            "storage_driver_implemented": False, "filesystem_implemented": False,
            "source_before_sha256": SOURCE_SHA256,
            "source_sha256": hashlib.sha256(after).hexdigest(), "boot_approved": False}
