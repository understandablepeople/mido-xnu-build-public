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

## Validation

60 tests PASS, one NDK module skipped. Includes exact CX request encoding,
transport error propagation, serialized opt-in callsite checks, full patch
replay, stale RPM reply rejection, synthetic WCNSS malformed-input tests
and sanitizer-tested gesture aggregation. MidoInput.cpp/MidoHID.cpp ARM64
object compiles PASS. Full CI and physical probe results pending.
Keep0114 rollback image and8CPU/shim/DTB/ADT/root untouched.
