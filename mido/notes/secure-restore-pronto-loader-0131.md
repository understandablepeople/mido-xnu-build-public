# 0131 secure restore and Pronto loading core

## Implemented, not deployed

GPU: midogpusecure=1 (default OFF) requests secure restore for the own-board
GPU device18/context0 only after a successful active-rate stage. It checks
SMC64 INFO and restore availability first. No mutating convention fallback;
transport and secure return codes are checked separately. Any negative result
blocks subsequent GPU status probing. There is no SMMU mapping/resume, CP
initialization, ZAP authentication, backend registration or acceleration.
The raw-register backend-ready guard remains unchanged.

SCM: the existing bounded query transport now also accepts typed argument
info and three value registers. Interrupted continuations preserve returned
registers/context; busy retries recreate the original full request. Existing
queries retain their ABI. PAS_INIT needs info0x82, not the all-value info2:
its second argument is SCM_RW in the pinned Android implementation.

Wi-Fi: mido_wcnss_loader.h implements a serialized callback-driven loader:
validate all extents before writes; check dependencies; write/clean metadata;
PAS6 INIT_IMAGE; MEM_SETUP; copy each segment, zero BSS, clean; recheck
dependencies; AUTH_AND_RESET. Both transport and secure status must succeed.
All memory targets must stay in the own-board no-map reservation
0x8e700000..0x8ee00000. Metadata has a separate aligned slot outside the
firmware allocation. Overflow, overlap, invalid counts/size, missing callbacks
or failed readiness stop before writes. Any partial attempt cannot be
implicitly retried with the same result state; there is no guessed shutdown
or rollback. AUTHENTICATED is only the callback result, not a radio handshake.

The loader has NO kernel startup caller yet. Its callbacks must implement
real reserved-memory ownership/mapping, cache clean plus completion barriers,
serialized SCM with the verified ABI, actual proxy/SCM bus and clock readiness
including IRIS sequencing. A boolean or a successful host mock is not that
proof. No code automatically trusts the earlier power-stage acknowledgements
to bypass those requirements. Firmware signature verification remains PAS's
job; the host inspector checks layout/hashes, not cryptographic authenticity.
The image's source buffers must remain valid and must not alias destination
writes. The owner must serialize the entire operation and preserve resources
through firmware startup and subsequent SMD/DXE operation.

## Private firmware preparation

tools/mido_pronto_stage.py reads the existing inspected split firmware,
validates the own live DT reservation and its nonoverlap with the payload XNU
arena, rereads and checks the source hashes, then generates a private C image
descriptor and manifest. This does not reserve or write memory on the phone.
Keep generated files under ignored out/, never upload firmware/calibration.
This check does not replace complete bootloader/ramdisk/ADT reservation
validation for any future image containing this descriptor.

Actual private output out/pronto-stage-0131-private:
allocation6565888 bytes; metadata7324 bytes at0x8edfe000. Own descriptor
copy/BSS was executed against host RAM with sanitizers; PAS was a MOCK.
No claim of actual firmware authentication, startup, WLAN or network success.

## Evidence

Pinned own Android dbe33d8d742974d65b20971bcb91dee26ea56892:
scm.c/scm.h restore and argument encoding; arm-smmu.c regulator notifier;
subsys-pil-tz.c PAS requests; peripheral-loader.c order
init_image -> mem_setup -> load segments -> auth_and_reset.
No donor A530 SMMU layout or PCIe Wi-Fi reset recipe is transplanted.

Host suite:113 tests PASS, one NDK skip. Includes every loader callback
failure, separate secure/transport failure, range/overlap rejection, exact
operation order, partial-attempt retry rejection and shared SCM retries.
ARM64 preflight:20 objects PASS. Its integrity aggregate remains FAILED on
the same12 historical patch-number gaps and three unrelated CRLF scripts.
Private report logs/preflight-20261106T210243Z/report.json. Latest added
SCM three-argument busy-retry test was rerun in the targeted suite.
No full CI/link or physical0131 test was run; the phone remains in recovery.

## Remaining integration before a useful combined boot

Bind real memory/cache/SCM callbacks and verified prerequisites to the Pronto
loader, package firmware privately with explicit boot reservations, implement
IRIS/proxy bus and startup handshake, SMD/NV/DXE/Apple80211 backend.
GPU still needs AXI/QoS, secure SMMU resume and context ownership, ZAP,
A506 CP/BO/fences and userspace rendering integration. Device18 restore alone
is not a proved fix for the earlier external abort. Keep status MMIO OFF.
Do not boot a candidate merely to reconfirm power votes or manufacture a
backend-ready flag to open the raw GPU-register path.
