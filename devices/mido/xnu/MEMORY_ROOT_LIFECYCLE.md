# Diagnostic native memory-root lifecycle

The opt-in `--experimental-memory-root` stages a hash-pinned change after
the existing IOService format repairs. It requires the explicit diagnostic
platform and adds a compiler definition only to IOService.cpo. Both that
definition and ARM64_BOARD_CONFIG_MIDO must be present for the change.

The original IOFindBSDRoot native md0 branch calls setRootMedia(NULL).
There is no IOBlockStorageDriver provider to traverse on that path. The
adaptation resolves and requires that class only for a non-null root.
The existing root-parent locking, invalid-sentinel transition, and call to
publishHiddenMedia remain intact. In publishHiddenMedia, a missing IOMedia
class is accepted only for a null parent; visibility state is still updated
under the original lock before returning. No instances of an absent class
exist to publish. Non-null roots retain the storage-class assertions.

This is not an IOStorageFamily replacement. The opt-in does not implement
storage drivers, register counterfeit metaclasses, invent a successful
IOFindBSDRoot return, or mount a filesystem. Original assertions remain
unchanged without the opt-in, including for non-MIDO builds.

Native compilation and execution must be checked separately. A diagnostic
4 KiB md0 fixture contains no filesystem and is not an installable image.
A genuine root filesystem provider, valid disk image and hardware validation
remain required before any claim of booting userspace.
