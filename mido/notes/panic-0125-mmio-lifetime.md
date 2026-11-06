# 0125 panic: temporary MMIO mapping lifetime

User photograph shows vm_map_delete attempting to remove a permanent VM
entry, vm_map.c:7940, kernel task during MidoInput initialization.
Exact0125 kernel symbols resolve photographed stack addresses:

- fffffff007abe738: __vm_map_delete_failed_panic
- fffffff0073975b8: vm_map_delete+ff8
- fffffff00739f738: vm_map_remove_and_unlock+28
- fffffff007391b10: kmem_free_guard+b0
- fffffff007a69804: MidoInput::touchRails+6a4
- fffffff007a6b354: MidoInput::touchSetup+24
- fffffff007a6cf70: MidoInput::initialize+b0
- fffffff007a6d080: MidoInput::poll+c0

This is an introduced host/kernel VM API mismatch, not demonstrated GPU
hardware failure. arm64/machine_routines.c ml_io_map calls io_map with
unmappable=false; arm/io_map.c selects KMA_PERMANENT in io_submap. It must
not be paired with ml_io_unmap, which removes PTEs then kmem_free(kernel_map).
The new Wi-Fi clock snapshot is before GPU bring-up and frees its mappings
before emitting result, so this is the first invalid new cleanup path.
Existing touchRails even documented the permanent-map restriction; the new
implementation and its original permissive mocks missed it.

0126 fixes all newly introduced temporary clock/status mappings to use
ml_io_map_unmappable(address, size, VM_WIMG_IO). That path selects KMA_DATA
in kernel_map and is correctly paired with ml_io_unmap. Flags preserve Device
memory semantics; mapping extents are page-aligned. No removal of cleanup,
no weakening vm_map permanent-entry checks, no change to unrelated lifetime
mappings, and no changes to GPU/Wi-Fi diagnostic sequencing or boot flags.

Native harnesses expose ONLY the unmappable API and enforce VM_WIMG_IO;
regression back to ml_io_map fails compilation. Source tests enforce exact
unmappable call counts/flags for all three headers, plus patch reconstruction.
Earlier tests proved whitelist/control flow but not the real VM lifetime
contract, so their pass did not establish hardware correctness.

A TWRP read on this turn returned254533bytes/flush277, identical SHA256
cb78e23133e7bc8983daf1d53a00d02fad175c2ea666bf8a4529f0106eef8319
to the prior0124 console. It is STALE and provides no0125 stage evidence.
The panic photograph and exact kernel symbol/source matching are the evidence.
No claim that GPU branches or PAS6/13 support succeeded in0125.

Next: local sanitized suite/ARM64 objects, single0126 CI, checksum/scan,
then same combined flags and baseline in verified temporary lk2nd boot only.
No partition flashing, rootfs or firmware writes to fix this host VM bug.

Preflight182034Z:92 tests pass (one NDK skip), four ARM64 objects pass,
firmware/own-board/combined memory and voltage plan pass. Initial181837Z
ARM64 check caught missing common VM_MEM macros; include corrected from
arm/memory_types.h to vm/memory_types.h. Known old whole-repository
validator issues remain: twelve historical numbering gaps/three CRLF scripts.

## 0126 build and temporary boot

Source54f64890515d3f9d92b56e2786cbb9cf5972b4e1, CI42270008073 PASS.
Kernel SHA256
f8ac2b0ba906939acbaf3c48a053bf1b2a74479f3d515dd30a3bc51521abe1ed.
Image out/mmio-0126-8cpu/package/mido-xnu-shim.img SHA256
d1fb37e0114bd7e603e5009939d3fb626b99b9eb864ace000cceaf3b750c25c7.
Artifact checksum matched. Scanner2293760words, sole0xb33bb4fullK256data,
zero actual unsupported instructions. Packaged memory plan passes.
Baseline shim/DTB/ADT/memory/root/8CPU/CC and all0125combinedflags retained.
Verified one mido recovery, stockfastbootmido, knownlk2nd checksum, lk2nd
RAMbootOKAY, productlk2nd-msm8953,0126RAMbootOKAY;bothstatus0.
No partition flash or rootfs changes. Private validation and boot reports
logs/mmio-0126-validation.json and mmio-0126-temp-boot-20261106.json.
Loader acceptance only; await physical startup/panic comparison and fresh
recovery console for actual GPU/PAS/Wi-Fi stage results.
