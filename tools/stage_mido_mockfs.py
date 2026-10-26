"""Stage original XNU mockfs for an explicit single-executable diagnostic root."""

import hashlib


SOURCE_HASHES = {
    "mockfs.h": "6fb2606b86bdee6e111946d5307b112ca4a53497317c556b0827a545234ec285",
    "mockfs_fsnode.h": "5b3014a41436ebb9986b473302bdbe1b745fc6ba43dc82d27689da700097cb24",
    "mockfs_fsnode.c": "d0a949994d3f498a555547041710b8d83705a969eb3f564bdb4770c6ead0204d",
    "mockfs_vfsops.c": "2b38d7c13e3e2f591bdf41c62d2dc7e59d3b7a594e28bfe0e2331dda972e370d",
    "mockfs_vnops.c": "e91f51d5d542f00ec2081609babaa96f17c4a6ab335bb9bd9e5f0f9082ce8d88",
}
CONFIG_SHA256 = "fd39c685b5e0b2ac214f13d52fd08e815c61be86d340ebe5191aee1dd5f81ae4"
CONFIG_ANCHOR = b"# MIDO_FILESYSTEM = [ devfs fifo namedstreams config_fse ]"
FAST_BEGIN = b"\tif (!VNOP_IOCTL(rvp, DKIOCGETMEMDEVINFO, (caddr_t)&memdev_info, 0, NULL)) {\n"
FAST_END = b"\t}\n\n\tlck_mtx_init(&mockfs_mount_data->mockfs_mnt_mtx, &mockfs_mtx_grp, LCK_ATTR_NULL);"
FAST_GUARD = b"#if !defined(ARM64_BOARD_CONFIG_MIDO) || !defined(MIDO_DIAGNOSTIC_MOCKFS)\n"


def stage_mockfs(source):
    source = source.resolve()
    relatives = ["bsd/miscfs/mockfs/" + name for name in SOURCE_HASHES]
    relatives += ["config/MASTER.arm64.MIDO", "bsd/conf/files", "bsd/conf/Makefile.arm64"]
    before = {}
    for relative in relatives:
        path = source / relative
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError("escaped mockfs staging path")
        before[relative] = path.read_bytes().replace(b"\r\n", b"\n")
    for name, expected in SOURCE_HASHES.items():
        if hashlib.sha256(before["bsd/miscfs/mockfs/" + name]).hexdigest() != expected:
            raise ValueError("unexpected original mockfs source: " + name)
    configuration = "config/MASTER.arm64.MIDO"
    if hashlib.sha256(before[configuration]).hexdigest() != CONFIG_SHA256:
        raise ValueError("unexpected MIDO mockfs configuration")
    if before[configuration].count(CONFIG_ANCHOR) != 1:
        raise ValueError("ambiguous mockfs configuration group")
    units = [name for name in SOURCE_HASHES if name.endswith(".c")]
    for name in units:
        entry = ("bsd/miscfs/mockfs/" + name + "\toptional mockfs").encode()
        if before["bsd/conf/files"].splitlines().count(entry) != 1:
            raise ValueError("missing original mockfs compilation unit: " + name)
    makefile = "bsd/conf/Makefile.arm64"
    if b"MIDO_DIAGNOSTIC_MOCKFS" in before[makefile]:
        raise ValueError("mockfs diagnostics already staged")
    nodes = "bsd/miscfs/mockfs/mockfs_fsnode.c"
    mounts = "bsd/miscfs/mockfs/mockfs_vfsops.c"
    after = dict(before)
    for original, replacement in (
            (b"kalloc_type(mockfs_fsnode_t,", b"kalloc_type(struct mockfs_fsnode,"),
            (b"kfree_type(mockfs_fsnode_t,", b"kfree_type(struct mockfs_fsnode,")):
        if after[nodes].count(original) != 1:
            raise ValueError("unexpected mockfs allocation type")
        after[nodes] = after[nodes].replace(original, replacement)
    if after[mounts].count(FAST_BEGIN) != 1 or after[mounts].count(FAST_END) != 1:
        raise ValueError("unexpected mockfs memory shortcut")
    after[mounts] = after[mounts].replace(FAST_BEGIN, FAST_GUARD + FAST_BEGIN)
    after[mounts] = after[mounts].replace(FAST_END, FAST_END.replace(b"\t}\n", b"\t}\n#endif\n", 1))
    after[configuration] = before[configuration].replace(CONFIG_ANCHOR, CONFIG_ANCHOR[:-2] + b" mockfs ]")
    after[makefile] += b"\n" + b"".join(
        (name[:-2] + ".o_CFLAGS_ADD += -DMIDO_DIAGNOSTIC_MOCKFS=1 -fno-lto\n").encode() for name in units)
    records = {}
    for relative, data in after.items():
        if data != before[relative]:
            (source / relative).write_bytes(data)
            records[relative] = dict(before_sha256=hashlib.sha256(before[relative]).hexdigest(),
                                     sha256=hashlib.sha256(data).hexdigest())
    return dict(files=records, diagnostic_only=True, original_vfs_registration=True,
                backing_io="original cluster_pagein and memdev block strategy",
                memory_shortcut_enabled=False, fsnode_allocation="struct mockfs_fsnode",
                filesystem_contents_validated=False, root_mounted=False, userspace_booted=False,
                production_filesystem=False, boot_approved=False)
