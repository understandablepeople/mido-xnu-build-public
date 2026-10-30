# Native 4-KiB build checkpoint

2026-10-30: GitHub run 41094338254 completed successfully on macos-15 with
Xcode 16.4, source commit b6e0896060abd7529bf4c5af07dd092961de7088.

The source-staging regressions, actual header export, compilation and linking
passed. build-report.json records kernel_built=true, pipeline_passed=true,
and an empty blockers array. This is compilation evidence, NOT boot approval.

- Artifact: mach.development.mido, 15,287,608 bytes.
- SHA-256: cc775278d62f492d424ae998663bdb370c909203f3fd69c9a66c2961cdce32f3.
- Native page-policy candidate: seven hash-pinned source files plus MIDO flags.
- Bootstrap pool: sixteen pages, full clearing, checked L2 allocation boundary.
- Original Apple compiler checks were retained; no Linux allocator workaround.

This build enabled bootstrap crypto and the existing non-Apple startup option.
IRQ/timer, framebuffer checkpoints, platform expert, pthread, memory-root, mockfs
and entitlement diagnostics were NOT enabled. It must not replace the previous
hardware diagnostic image without rebuilding the required providers and auditing
the new binary's addresses, bootstrap instructions and memory placement.

The checkpoint stager accepts the exact reviewed native-4K startup hash as well
as the baseline hash; it does not accept arbitrary modified startup source.
Its combined staging regression suite has 23 passing tests.

Still unverified: hardware execution of this binary, full VM/scheduler startup,
16-KiB code signatures on 4-KiB VM, dyld shared cache and actual Apple userspace.
No phone partition was written and no RAM boot was attempted for this build.

## Full-provider build and offline binary audit

Run 41095763854 (commit fa4b9f0) also succeeded, with all ten diagnostic
workflow inputs enabled. Its report records kernel_built=true,
pipeline_passed=true and blockers=[]. The retained mach.development.mido is
15,366,760 bytes, SHA-256
9b67c800aaf870ab969fab329f0080bdb89eebc0635d199d14a693853e235187.

tools/audit_mido_native4k_binary.py executes this exact binary under Unicorn
2.1.4 Cortex-A53 emulation, from after the framebuffer argument checkpoint
until before common_start. It does not execute the initial framebuffer writes,
enable the MMU or construct a bootable phone image. The old v89 profile is
unchanged and must not be used with this binary.

Three cases passed against independent table bytes: a 32-MiB diagnostic arena,
a synthetic 3-GiB extent crossing L2 boundaries, and synthetic 8-GiB pool
exhaustion. The latter stops at the guard loop before writing outside the pool.
All 32 MiB of execution backing were compared, with the 64-KiB table pool
prefilled nonzero to verify complete clearing. Larger synthetic extents are
table-geometry tests, NOT approved physical memory maps.

Reproduce from the repository root with Unicorn installed:

    python -m tools.audit_mido_native4k_binary PATH_TO_KERNEL --output NEW_REPORT.json

Set MIDO_NATIVE4K_KERNEL to the same artifact to enable the binary integration
case in tests.test_mido_native4k_binary. Next hardware work still requires a
new reviewed MMU/observer/loading profile; these results do not prove VM,
userspace, dyld or SpringBoard startup.

## Native-4K MMU and translated reads

The separate tools/audit_mido_native4k_mmu.py audit also passed five scenarios
with Unicorn 2.1.4 on the Cortex-A53 model: normal startup, missing high root,
missing low root, missing argument block and missing stack block. The normal
path executes native startup through MMU enable, branches at arm_init into a
92-byte store-free observer, reads actual high-virtual argument and stack
memory, then returns with MMU/caches disabled. Every missing mapping stops at
its intended instruction, not just an arbitrary later failure.

This is an offline synthetic argument fixture. The original arm_init body is
not executed in this audit, and modeled higher exception-level controls and
SCTLR bit 23 are not evidence about the handset firmware. VBAR is redirected
to the checked halt-only diagnostic vector page. It is not an iOS boot test.

    python -m tools.audit_mido_native4k_mmu PATH_TO_KERNEL --toolchain NDK_BIN --output-directory NEW_DIR

The observer source is included; its compiled 92-byte payload must match the
reviewed SHA-256 before use. Set MIDO_NATIVE4K_OBSERVER to observer.bin alongside
MIDO_NATIVE4K_KERNEL for the corresponding regression integration cases.

## Bounded native-4K loader profile and RAM test

tools/mido_native4k_profile.py provides an exact-SHA profile separate from the
previous v89 binary. It verifies the original prefix, table-builder and MMU
instruction windows, derives current addresses, and supplies the complete
sixteen-page expected table pool. The bounded 32-MiB geometry needs only four
nonzero table pages; the profile emits a 2048-word initializer plus an explicit
8192-word verification count. The remaining pages must still be checked as zero,
not omitted from validation. This keeps the carrier code/data envelope unchanged.
The profile alone is not a phone image or a general full-kernel boot loader.

The local bounded-C carrier integration passed 55 unit tests and complete image
emulation: actual entry, native tables/MMU, original arm_init C, stop before
arm_vm_init, cache-aware physical return, and diagnostic screen rendering.
Its compiled checker rejected 19 state corruptions, including the last pool
word and extra table pages; seven preparation acceptance/rejection cases passed.
The public staging/binary/MMU/profile suite has 38 passing tests with the pinned
kernel and compiled observer supplied.

Local RAM image: artifacts/mido-native4k-c-v3/mido-xnu-carrier-probe.img,
51,924,992 bytes, SHA-256
6b5780f1836957294582e608adcc1e99be248fc90ab62f5bafdc6c2040ba4ce8.
At 2026-10-30 17:40:40 UTC the handset accepted its fastboot boot command via
the verified temporary lk2nd 23.1 loader. No flash/erase command was executed.
The hardware early-C result is NOT yet confirmed: it requires a photograph of
the handset diagnostic display. This is deliberately halted before VM init,
not a full XNU, dyld, SpringBoard or iOS boot.

## Hardware observation and batched VM investigation

The subsequent user photograph shows XNU EARLY C OK, FAIL=0 and STOP BEFORE
VM INIT for the native-4K RAM diagnostic. This is manually interpreted display
evidence for the bounded early-C stage, not evidence of complete VM startup or
physical cache coherence. The local observation record binds the photograph
hash to the recorded RAM session; no image was flashed to a partition.

Four independent offline VM checkpoints are now derived from real BL call
sites by tools/mido_vm_checkpoint_plan.py: geometry before early_random,
return from early_random, first bzero call and return from that bzero.
The unchanged no-seed fixture correctly panics in Apple's bootseed check.
An explicit offline-only 64-byte test seed lets all four checkpoints pass.
Seed zeroing is checked within its exact payload range; the first allocated
4-KiB page is poisoned before execution and checked completely zero afterward.
Only zero writes in that exact allocation page are allowed, not arbitrary
writes elsewhere in the arena. No kernel PRNG or allocator was stubbed.

This establishes bounded offline progress into arm_vm_init, not completion of
arm_vm_init, pmap_bootstrap, translation-table replacement or userspace startup.
Larger stages require separate allocator/observer lifetime and mapping review.

The next user photograph confirms XNU VM PAGE OK, FAIL=0 and STOP AFTER FIRST
PAGE on the handset, for RAM image SHA-256
f42fffae7cd061daa74508abbb05a227caaef061e6a6d8df358a6a8bf5ba580b.
This extends the hardware observation into the first original VM allocation;
it does not confirm completion of VM init or a working iOS userspace.

The offline batch now also passes second-page clearing, first L2 return and
completion of the initial L2-page loop: seven independent checkpoints total.
At that boundary exactly three sequential pages are compared against an
independent 12-KiB reference: invalid page zero, L1 page with one precise
APTable descriptor (0x2000000012403003), and empty L2 page. The active bootstrap
translation tables are not replaced by this test. The RAM observer remains
below topOfKernelData; allocation writes are confined to reviewed pages above it.
