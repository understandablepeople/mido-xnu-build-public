# Matching HFS source audit (2026-10-26)

A candidate real filesystem provider was located by the same pinned macOS 13
distribution tree used to match XNU and pthread, not by choosing an arbitrary
latest filesystem revision. This is source inspection only; it has NOT been
compiled into MIDO or used to mount a volume.

- Distribution tree: 1103a82bbc0ce0def4c198db70251c29c27b2040
- XNU commit: 1b191cb58250d0705d8a51287127505aa4bc0789
- HFS version: hfs-627.100.6
- HFS commit: 31d5ec238dfab485e78a9a30b8b92d13e8914f03
- Official repository: apple-oss-distributions/hfs
- Codeload archive SHA-256: f70bafcc0a74cf7df4902e406c24119da75dfd2025cabc325a49e317b65a504e

The archive has 401 validated regular-file/directory members. The kext source
phase FB20E0DB1AE950C200CEBE7B declares 39 translation units. Of those, 38
exist under core/; core/hfs_key_roll.c is absent. The corresponding
core/hfs_key_roll.h is also absent. Do not substitute successful crypto/key
roll stubs for these missing implementations.

The original core/kext-config.h enables CONFIG_PROTECT for the real iOS
target. Therefore an unmodified iOS HFS integration must not be declared
complete merely by copying all available C files. Any explicitly scoped
unencrypted diagnostic configuration must retain fail-closed behavior for
unsupported protected volumes and must not claim iOS data-protection support.

## Actual VFS registration path

core/hfs_iokit.cpp implements com_apple_filesystems_hfs::start. It calls the
real superclass, registers hfs_vfsops through vfs_fsadd with
VFS_TBLCANMOUNTROOT, initializes HFS zones and registers sysctls. A correct
integration must execute that lifecycle before root mounting; defining the
hfs_vfsops symbol alone is not registration. In XNU vfs_mountroot, a
VFC_VFSCANMOUNTROOT provider may enter its original VFS_MOUNT method even
without a separate vfc_mountroot function.

The upstream build uses core/kext-config.h as a prefix header. Compression,
content-protection, vnode operations, encodings and kernel API dependencies
need an explicit compile/link review. Native compilation, registration, block
I/O, a valid filesystem image, successful mounting and userspace execution
remain distinct unproven gates. Upstream licensing and notices must be kept.

The downloaded reference, per-file hashes and source-audit.json are local
under artifacts/hfs-reference-v32/. No HFS sources or Apple SDK binaries are
vendored by this audit.
