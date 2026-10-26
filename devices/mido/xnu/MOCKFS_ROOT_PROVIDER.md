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

## Native build and execution evidence

Public Action 40364984250 compiled public commit 8d81777 successfully. Its
kernel is 15,335,856 bytes with SHA-256
5bb91091720fb468e11c186ee8c286145b4358061ecfbb6cfc34e12ad8c12da5.
The build report records the reviewed source transformations and has
pipeline_passed=true, kernel_built=true and no blockers.

The v36 offline run reserves eight RAM pages for a 32 KiB diagnostic
ARM64 Mach-O, not the previous arbitrary page. Original mockfs_mountroot
and vfs_mountroot both returned zero on the original BSD thread, after
the original md0 selection. The VFS return is reached through an audited
direct BL from bsd_init. completed=true, fault=null and inputs_unchanged=true.
This proves the native diagnostic root VFS mount, not file reads or execution.

The v37 run of the same kernel additionally reaches original
load_init_program through an audited BL from original bsdinit_task, on
the new native init thread. It also has completed=true, fault=null and
inputs_unchanged=true. No process or function return is fabricated. This
is init-loader entry only: executable_loaded and userspace_booted remain
false. CRC/SHA-256-verified replay packages are saved locally as
mido-xnu-root-mounted-v36-offline-complete.zip and
mido-xnu-init-entry-v37-offline-complete.zip.

The v40 offline run reaches original load_machfile through an audited
exec_mach_imgact call on the native init thread. Its 32-byte ARM64 Mach-O
header matches the reserved root payload, following an observed original
mdevstrategy return. Disk contents and frozen tool inputs are unchanged;
completed=true and fault=null. The CPU model delivers proven missing-table
store aborts for STR W and STP X (post-index or signed offset), using the
native TTBR0/TTBR1 tables. Original exception handlers resolve the faults
and retry instructions; the model does not install pages or force returns.

This is executable header acquisition and loader entry, NOT successful
segment loading, EL0 execution, a real syscall or handset boot. The
CRC/SHA-256-verified package is mido-xnu-init-image-v40-offline-complete.zip
with SHA-256 cb52132263c34d25ce8082195c9fb9d0a9aa861ff757ae6f0e2d158a508b4840.

The v41 run observes original load_machfile returning LOAD_SUCCESS (zero)
to exec_mach_imgact on the same init thread. completed=true, fault=null
and inputs_unchanged=true. Its verified replay archive is
mido-xnu-init-image-v41-offline-complete.zip, SHA-256
bbede9b5d4bda14f15d0ad0b65ea29ce866f833a7d0672eefbe5207727aaeaa0.
The new map has not yet been committed at this return, so this alone is
not successful exec or user instruction execution.

The v42 continuation stops later in machine_task_process_signature:
the original inlined IOTaskHasEntitlement loads amfi->OSEntitlements
through an unregistered (null) amfi pointer. Disassembly confirms the
faulting instruction and _amfi global; this is not a proven translation
fault and the CPU model refuses to invent a mapping for it.

The separate --experimental-entitlement-guard build opt-in requires
explicit mockfs diagnostics. It guards only the original boolean query
on MIDO: absent AMFI returns false (no entitlement); a registered provider
still receives the original query. It does not register a fake provider,
grant rights, skip signature processing or approve installation. The
stager pins the original source hash and records before/after hashes.

Public Action 40374524389 (public commit ba7080e) compiled the opt-in guard
successfully. The resulting kernel is 15,335,800 bytes, SHA-256
72e7265189ed7cf3f9f4c5b45fb262f0d9d0832d25ed2397ce59fcb555f58553.
The v43 run observes original load_init_program returning on the init
thread after LOAD_SUCCESS, without fabricated return values. Its verified
archive is mido-xnu-init-exec-v43-offline-complete.zip, SHA-256
6f4e244a6a0b6217b6fb1dc03ccb7283e684590bd89a51d935cbca6422c3a643.

The v45 run additionally reaches PC 0x100004000 with PSTATE=0 (EL0t).
It observes the original kernel ERET selecting that PC and the native
thread; the same thread reaches the EL0 code hook. Exec may replace the
earlier loader thread, so the check uses the actual exception-return
thread rather than incorrectly requiring the old thread identity.
The native TTBR0 walk proves an EL0-accessible executable mapping, and
all 28 payload bytes match the reserved RAM root. completed=true,
fault=null and inputs_unchanged=true. No new kernel build was needed.

The v45 hook stops BEFORE the first user instruction executes. It proves
EL0 entry, not completed getpid, a userspace boot or physical device boot.
SVC delivery and the original syscall/return path remain a separate gate;
no experimental SVC injector is enabled or shipped. The verified package
is mido-xnu-user-entry-v45-offline-complete.zip, SHA-256
60318a4749adfd2525667d232ea32be002553908ec344d3018aa3c61de956eae.
