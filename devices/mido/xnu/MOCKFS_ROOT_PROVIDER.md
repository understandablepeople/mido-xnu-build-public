# Original single-executable diagnostic root

`--experimental-mockfs` explicitly enables XNU mockfs for MIDO only, and
requires the memory-root and diagnostic-platform opt-ins. It is not HFS,
APFS, a general-purpose writable root, or an installable iOS environment.
It exposes the original in-memory directory layout, /dev mountpoint and
one executable backed by the root device as /sbin/launchd. The upstream
filesystem intentionally has limited semantics. No filesystem operations
are replaced by artificial successful returns.

The stager pins original sources from XNU 8796.141.3, checks the original
three optional mockfs compilation units, and activates their existing
configuration group. Original vfs_conf registration is left untouched.
The vnode-operation implementation and memdev implementation are unchanged.

Two source issues must be addressed before diagnostic use:

- mockfs_fsnode_t is a pointer typedef, but the original allocator and free
  use that typedef as their allocation type. Both now name the actual
  struct mockfs_fsnode, so node fields fit in the allocated object.
- DKIOCGETMEMDEVINFO exposes a 32-bit base-page field; mockfs then shifts
  that 32-bit field and passes it as a virtual address to
  pager_map_to_phys_contiguous. The MIDO md0 fixture registers a high
  64-bit kernel virtual address. The original shortcut cannot represent
  that address. On this explicit MIDO diagnostic configuration, the
  shortcut is not selected: original cluster_pagein, mockfs_strategy and
  memdev block I/O remain responsible for data. Other configurations
  keep the upstream shortcut. No truncated pointer is reconstructed by
  guessing high address bits.

Original filesystem registration, successful mounting, actual block I/O,
executable validation and first-process execution require separate native
evidence. The previous arbitrary 4 KiB diagnostic page is not an executable
and is not evidence of userspace boot, even if mockfs accepts mounting it.
