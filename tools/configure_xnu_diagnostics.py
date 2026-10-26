"""Configure a non-Werror diagnostic build and stage a genuine pinned header."""

import hashlib
from pathlib import Path


FIREHOSE_COMMIT = "cdb61e93e803d0093635f356753a9a30c09836db"
FIREHOSE_HEADER_SHA256 = "b1da2269d930974d1fb122d90446534553829dc2a3b090b3d0ea0813fd95dd45"


def configure_warning_policy(data):
    data = data.replace(b"\r\n", b"\n")
    original = b"WERROR := -Werror\n"
    anchor = b"\t$(WERROR) " + bytes((92, 10))
    if data.count(original) != 1 or data.count(anchor) != 1:
        raise ValueError("unexpected XNU warning configuration")
    data = data.replace(original, b"WERROR :=\n")
    additions = (b"\t-Wno-error=unused-but-set-variable " + bytes((92, 10)) +
                 b"\t-Wno-error=pointer-to-int-cast " + bytes((92, 10)))
    return data.replace(anchor, anchor + additions)


def remove_firehose_link_flag(data):
    original = b"LD_KERNEL_ARCHIVES = $(LDFLAGS_KERNEL_SDK) -lfirehose_kernel"
    if data.count(original) != 1:
        raise ValueError("unexpected kernel archive configuration")
    return data.replace(b" -lfirehose_kernel", b"")


def enable_firehose_spi(data):
    original = b"DEFINES = -DAPPLE -DKERNEL -DKERNEL_PRIVATE -DXNU_KERNEL_PRIVATE "
    if data.count(original) != 1 or b"OS_FIREHOSE_SPI" in data:
        raise ValueError("unexpected kernel firehose define layout")
    return data.replace(original, original + b"-DOS_FIREHOSE_SPI=1 ")


def stage_firehose_header(source):
    bundled = Path(__file__).with_name("vendor") / "firehose_buffer_private.h"
    data = bundled.read_bytes().replace(b"\r\n", b"\n")
    if hashlib.sha256(data).hexdigest() != FIREHOSE_HEADER_SHA256:
        raise ValueError("bundled genuine firehose header hash mismatch")
    target = source / "EXTERNAL_HEADERS/os/firehose_buffer_private.h"
    if target.exists() or target.is_symlink() or not target.resolve().is_relative_to(source.resolve()):
        raise ValueError("refusing to replace or escape the firehose header destination")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return {"repository": "apple-oss-distributions/libdispatch", "commit": FIREHOSE_COMMIT,
            "sha256": FIREHOSE_HEADER_SHA256, "path": str(target.relative_to(source)),
            "empty_stub": False, "sdk_modified": False, "library_built": False}
