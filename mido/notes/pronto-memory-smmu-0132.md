# 0132 private Pronto handoff, memory adapter and SCM-only SMMU resume

## Implemented and locally validated; not deployed

The own split firmware can now travel in a private binary bundle inside a
copy of the existing payload ADT. No public kernel embedding or rootfs write
is necessary. The current private payload is based on the old0130 kernel,
NOT an0132 boot image; it must not be mistaken for a deployable candidate.
The exported mido_pronto_boot entry invokes mido_pronto_start_from_adt, but
no board startup caller invokes mido_pronto_boot yet. The exported entry
owns one persistent memory adapter and a lifetime claim before binding the
readiness callback, preventing concurrent rebinds and repeat attempts.

Pipeline:
- mido_pronto_stage.py writes the inspected descriptor plus pronto.bin.
- mido_pronto_payload.py validates source/destination ranges, checks the
  payload/ADT arena and own reservation, preserves every existing kernel
  segment, command line and chosen property, appends the changed ADT and
  changes only its header offset/size. Refuses an existing output file.
- mido_wcnss_bundle.h parses the little-endian container without unaligned
  typed loads, bounds all offsets, checks disjoint source regions and uses
  the existing destination/overlap validator.
- mido_wcnss_start.h obtains the bundle and arena from SecureDT, parses them
  and synchronously invokes the real memory/SCM adapter.
- mido_wcnss_memory.h maps only0x8e700000+7MiB using the unmappable Normal
  non-cacheable VM_WIMG_WCOMB mapping. Uses volatile byte stores and DSB SY
  completion before secure consumption. This is not a cacheable alias and
  does not pretend a barrier cleans dirty cache lines. Requires no cached
  alias or previous external ownership of this reservation; caller must
  establish that before providing readiness. Rejects XNU arena overlap.
- The adapter checks SMC64, all three PAS operations and PAS6 support before
  mapping or writing, restricts mutating calls to PAS6 init/mem/auth with
  exact argument types, rechecks caller-owned dependencies before each PAS
  call and unmaps on every post-map outcome. No guessed shutdown/rollback.
  One persistent adapter instance can be claimed only once, including a
  failed attempt; owner must serialize and must not reset it to retry.

The dependencies_ready callback has NO production provider yet. It must
represent real serialized rail/XO ownership, crypto/proxy clock and bus votes,
IRIS setup, firmware reservation ownership and source-buffer lifetime.
Do not implement it as return1 or infer readiness from boot arguments.
After successful authentication those resources still need proper lifetime
and the driver needs a firmware-ready/SMD handshake before any radio claim.
No callers install a WLAN backend. No Wi-Fi network was established.

## GPU secure handoff

midogpusmmu=1 defaults OFF and requires midogpusecure restore result1.
Queries IO-read/write availability with the known SMC64 convention. Uses
atomic SCM IO calls only, not direct SMMU or GPU MMIO. Reads ID1 at01c40024,
requires4KiB register pages, address space64KiB and valid context-bank counts
fitting the own resource. Derives IMPL_DEF1 at01c46000, clears only LOCAL_HALT
bit2 through secure write, then reads back bit2. Preserves unrelated fields.
Atomic calls permit bounded interrupted continuations, but never busy replay
or fallback. The helper whitelist permits only the two confirmed SMMU read
addresses and the one control write; the old aborting GPU address is rejected.
No context-bank reprogramming, page tables, bypass, CP, ZAP or backend-ready
flag is introduced. Failure propagates before the guarded GPU status stage.
Neither flag was enabled or tested on the phone. This follows the pinned
Android static-CB notifier path, but is NOT proof of a fix for the old abort.

## Validation evidence

Pinned Android dbe33d8d742974d65b20971bcb91dee26ea56892:
arm-smmu.c ID1 geometry and static-CB qsmmuv2_resume; scm.c atomic IO ABI.
Local XNU8796 pmap.c maps VM_WIMG_WCOMB to normal non-cacheable;
proc_reg.h CACHE_ATTRINDX_WRITECOMB and machine_routines.c unmappable API.

119 host tests PASS, one NDK skip;20 ARM64 objects PASS. Private report
logs/preflight-20261106T212055Z/report.json. Integrity aggregate still FAILS
only on the same12 old patch-number gaps and three unrelated CRLF scripts.
Tests cover exact memory/SCM order, each dependency failure, each transport
failure, secure failures, unavailable calls before mapping, cleanup,
second-claim refusal, binary corruption/offsets, ADT handoff and preservation,
SMMU ID/layout, retained bits, whitelist and bounded interruption/no busy retry.
The actual4MiB bundle also passed the sanitized parser. The emitted ARM64
object contains a defined _mido_pronto_boot symbol, not merely unused inline
header syntax; it references the existing SecureDT APIs. No full kernel link
was performed. No firmware bytes,
calibration or device logs are committed.

Private out/pronto-stage-0132-private/pronto.bin:
4142984 bytes, SHA256 ac6ae6337fcaf2de04cfc8b212da3ba28c312d70af794ab96d2164ef2a23d8de.
Its host-only payload-with-pronto.bin:
SHA256 5e09e794808e84491ea14f4a38cde848d169d268b50dfdfb190d1d3db236e4f2.
This payload contains the old0130 kernel. It was not booted or flashed.
Phone verified recovery/mido. No CI scheduled and no device writes issued.

## Remaining real hardware work

Pronto: IRIS autodetection/reset/configuration with bounded waits and own
19.2/48MHz selection, SCM crypto/proxy bus/clock ownership, actual ready
provider and startup call, then SMD/NV/DXE/IRQ and Apple80211 backend.
The old proxy/SCM bandwidth client traverses AP-owned PCNOC nodes; do not
replace that with guessed isolated RPM master/slave votes.
GPU: AXI/QoS, validation of secure restore/resume, ZAP reservation/PAS13,
A506 CP/BO/fences, hardware backend registration and userspace rendering.
No amount of power acknowledgements or successful host mocks establishes
those operations. Do not boot the old private payload or an empty candidate.
