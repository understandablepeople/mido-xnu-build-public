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

`python -m unittest tests.test_mido_root_checkpoint tests.test_audit_mido_root_support tests.test_mido_macho_symbols`
checks the standalone observer, audit and bounded symbol reader.
