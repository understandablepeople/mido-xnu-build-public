# Serialized GPU CX vote and independent gesture/WCNSS work

## Scope

0115 adds an opt-in midogpucx=1 request after both working touch rail
requests complete successfully. It reuses the same local RPM SMD client
in the same startup call; no separate service/thread or channel is opened.
The request is smpa resource2, swen=1, vlvl=192: the CX level corresponding
to the board GFX init-corner4. It is NOT a microvolt value. No retries on
failure and no GDSC/GFX-LDO/mem-acc/clock/GPU/SMMU/SCM writes follow.
Failure does not change the result of touch-rail setup. Default0 makes
no extra RPM request. The already validated midogpu=1 snapshot is repeated
after the request, with separate before/after markers. CX vote success
does not prove CX/GX GDSC on or any acceleration.

The existing RPM reader accepted a success-shaped response without matching
its request ID. Before adding a third request,0115 requires exact success
payload length and matching message ID; stale responses fail closed.
No automatic rollback vote is sent: removing an untracked shared supply
vote is not a safe substitute for a proper resource ownership model.
This bounded probe is not yet a shared regulator framework for Wi-Fi.

## Board evidence

Pinned Android kernel dbe33d8d742974d65b20971bcb91dee26ea56892 and saved
recovery DT agree: rpm-regulator-smpa2 resource-name smpa/resource-id2;
regulator-s2-level uses qcom,use-voltage-level. GFX-LDO init-corner4
maps to CX192 and mem-acc2. LDO enable first votes/enables CX, then sets
BHS control. This candidate deliberately stops at the first dependency;
it does not pretend the rest of that sequence is implemented.

## Gesture diagnostics0116

midohidtrace=1 collects accepted, deduplicated HID event counts and raw
start/end/min/max Y for each completed contact, after dispatch. Logging
is capped at64 completed contacts per boot; default0 disables it.
It does not change coordinates, decoder, event masks, identities, timing
or synthesize gestures. A continuous upward trace establishes that a
movement stream reaches dispatch, NOT that backboardd recognized the
system gesture. Test bottom swipes soon after boot before the cap.

## Wi-Fi parallel work

tools/mido_wcnss_firmware.py structurally validates the own-device ARM32
Pronto split image independently from Hexagon A506 ZAP. It verifies MDT
table/hash consistency, segment bounds/nonoverlap, payload lengths and
relocatable flags; describes BSS zero-fill and required allocation.
It neither authenticates signatures nor starts firmware or networking.
Only synthetic fixtures are committed; firmware and calibration stay local.

Actual local WCNSS validation succeeds:13 program headers,9 nonempty
load-memory segments,10 files,6565888-byte page-rounded image extent,
2361408 zero-fill bytes. The saved board DT identifies PAS6, Pronto-v3,
SMD edge6, IPC0b011008 bit17, and a no-map reserved7MiB firmware region
at8e700000. Firmware link-base8e600000 is NOT the destination: the
board reservation implies a +1MiB relocation if that region is reused.
Current XNU low arena20000000..5ff00000 does not overlap that reservation,
but secure-world ownership and proxy clocks/supplies still need bring-up.
No firmware loading, calibration rewrite or Wi-Fi enable is attempted.

Optional --dtb now resolves the actual Pronto memory-region phandle,
requires PAS6/Pronto-v3/no-map/64-bit reservation cells, and produces a
per-segment relocation/copy/zero-fill plan. Rejects reservation overflow
and alignment breaks. Actual saved board DT passes; no allocation is
claimed verified on the device. Private report:
logs/wcnss-board-validated-20261106.json.

Read-only current TWRP dmesg independently reports GFX LDO-mode fuse
disabled by default, adjusted LDO reference615/675/720mV, and Pronto
assigned its reserved region/WCNSS probed built-in. This is Linux recovery
evidence, NOT XNU GPU/Wi-Fi success. No recovery debugfs/MMIO accessed.

## Validation

63 tests PASS, one NDK module skipped. Includes exact CX request encoding,
transport error propagation, serialized opt-in callsite checks, full patch
replay, stale RPM reply rejection, synthetic WCNSS malformed-input tests
and sanitizer-tested gesture aggregation. MidoInput.cpp/MidoHID.cpp ARM64
object compiles PASS. CI42224031975 PASS8m40s for kernel source
a2aec5859f87b49be62748f84ac11774e598c1d5. Host-only WCNSS board-plan
follow-up3f986da does not alter this kernel.

Kernel xnu/out-0116/kernel.development.mido SHA256
c5186b3c6066861ba8f8db6be0db3ddc1c1d3396eb868f9ff6d8d5100ef1ff84.
Image out/gpu-cx-0116-8cpu/package/mido-xnu-shim.img SHA256
fa975f905c1455b0c78a61976dd313843ab44929e8d07452a153e3c9fc48a993.
Exact0114 shim/DTB/ADT/memory/outer cmdline preserved; sole inner additions
midogpucx=1 midohidtrace=1. Scanner single hit0xb32014 is verified complete
SHA256 K256 table, not an instruction. Zero actual unsupported hits.

Verified one mido in TWRP; adb reboot bootloader (not system), verified
stock product mido; known lk2nd RAM boot accepted; verified product
lk2nd-msm8953; candidate RAM boot accepted. No partition flashing, root
replacement or calibration writes.0114 rollback remains intact.
Booting OKAY is loader acceptance only. Await physical startup/touch/WLED
check and early bottom swipes, then return TWRP to pull fresh persisted
log. Require actual MIDO GPU CX result/ACK and before/after snapshots;
trace records must establish actual gesture continuity before any fix.
Acceleration and Wi-Fi remain unavailable; no hardware success inferred.
