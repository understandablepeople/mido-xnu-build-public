# Native root-discovery evidence (2026-10-26)

The v30 offline run reaches the original IOBSD resource wait inside
IOFindBSDRoot on the original BSD initialization thread. The direct ARM64 BL
instruction is audited at 0xfffffff007ac1c60; the observed LR is that address
plus four. The original timeout argument is 30,000,000,000 ns.

Kernel SHA-256:
e5fd32774a153c41277ed422bf93e2249409735361cbd01978c3363c49a1d289

The run completes its requested checkpoint without a fault, leaves its hashed
inputs unchanged, and charges 173,897,060 modeled instructions. This is entry
to a resource wait, NOT a returned service, selected root, mounted filesystem,
userspace startup, handset boot, or installation approval. No function return
or root-device result is fabricated. Exact runner inputs and reports are
preserved in the local v30 offline evidence package, not distributed as a
phone image in this public source repository.

## Next real dependencies

The inspected kernel contains original mdevadd, mdevlookup, mdevstrategy and
mdevrw functions. However, the synthetic chosen/memory-map has no RAMDisk
property, and the kernel has no recognized HFS/APFS/NFS/mockfs root-provider
symbols checked by the audit. APFS-related UUID helpers do not implement APFS.

A memory-backed diagnostic root path requires a reserved, non-overlapping RAM
range, an ARM64 RAMDisk property (two 64-bit words), an explicitly selected
memory device, and then a real registered filesystem implementation with a
valid image. Device selection alone would still not demonstrate mounting.
Actual eMMC access additionally requires a Qualcomm storage backend; none is
inferred from successful compilation or from a synthetic memory-device test.

## Read-only audit

Run `python tools/audit_mido_root_support.py KERNEL APPLE_TREE OUTPUT.json`.
APPLE_TREE is the XNU flattened Apple tree, not a Linux FDT. Existing reports
are not overwritten. Symbol presence only supplies static evidence; the audit
never grants boot approval, even when its prerequisite blocker list is empty.
It does not inspect dynamically loaded filesystem modules.

## Public-build verification and RAM-disk experiment

Public Action 40352396023 succeeded and produced a 15,333,704-byte kernel,
SHA-256 2eb4ad70cc3b09549d80c8800ba2070dca922d810a371fd407d63a80d0f9c082.
The v31 offline run of that exact public kernel reaches the audited original
resource wait with completed=true, fault=null and inputs_unchanged=true.

The next v33 fixture adds one explicitly reserved 4 KiB diagnostic RAM page
at 0x22032000, protects it from the allocator by advancing topOfKernelData,
copies it through the native handoff payload, and selects rd=md0. Those bytes
are deliberately NOT a filesystem and must not be treated as one.

The real mdevadd executes and returns device 0x01000000 with size_pages=1.
Execution then reaches the original assertion in IOService::setRootMedia:
IOService.cpp:5182, expression ioblockstoragedriverClass. The real
IOBlockStorageDriver metaclass is absent. No successful root selection or
mounting is claimed, and the assertion was not removed or bypassed.

The matching distribution pins IOStorageFamily commit
609cbbdf9fa8fd5eae973d9135c7d44b47e6502e. Its official codeload archive has
SHA-256 42bfd0c4740148e25a7d1c86a94c55b7ce6de66010102bf82368228c5e76759b
and 84 validated regular-file/directory members. The native driver depends
on IOMedia, IOStorage, IOBlockStorageDevice and DriverKit/performance-control
interfaces; registering a fabricated class with the same name is not an
acceptable substitute. Dependency compilation and registration remain open.

## Verified native md0 selection (v35)

Public Action 40358370749 attempt 2 compiled the explicit memory-root opt-in
successfully from public commit a7f731adf2d768bb452df06099dcfc8bdbbd7cba.
Attempt 1 never acquired a hosted runner and did not compile anything.
The new kernel SHA-256 is
e2b60375844cc30a473ffcf1fcee6caef6ba252805435321c6efac24533ac2f0.
The native build report has kernel_built=true, pipeline_passed=true and no
blockers; this does not grant device boot approval.

The first v34 execution reached the original IOFindBSDRoot return address,
but the host observer incorrectly read a dynamically mapped output pointer
as a physical address. Its unmapped host read is not a kernel panic or a
successful root-selection observation. A bounded, read-only native table
walker now reads those outputs, including noncontiguous page crossings.
It does not alter registers, mappings, kernel memory or function results.

The v35 replay of the same kernel then completed with fault=null, no execution
error and inputs_unchanged=true. Original IOFindBSDRoot returned status 0,
root_name=md0 and root_device=0x01000000 on the original BSD thread. The
original mdevadd returned that device; the actual initialized mdev table
record confirms the LTO-inlined lookup, sector size 512, one page and flags 1.
The diagnostic RAM page SHA-256 remained unchanged. No return was invented.

The fixture still contains only a 4 KiB diagnostic page, NOT a filesystem.
root_mounted, disk_io_validated, userspace_booted and device_boot_proven are
all false. A real root provider and appropriate contents remain the next
gate. Native mockfs is a possible deliberately limited diagnostic provider,
not HFS/APFS: its 32-bit memory-device shortcut needs an ARM64 address-width
review before use with this high virtual-address RAM-disk registration.

`python -m unittest tests.test_mido_root_checkpoint tests.test_audit_mido_root_support tests.test_mido_macho_symbols`
checks the standalone observer, audit and bounded symbol reader.
