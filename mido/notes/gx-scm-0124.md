# 0124 GX power and SCM availability stage

## Runtime feedback before this change

User reports applications still open after five minutes of the vmd-only
comparison boot. Fresh private log vmd-disabled-live-20261106.txt is
311202 bytes, flush437. It nevertheless contains exec vmd at686410ms,
Preferences723910ms and MobileSMS859402ms. Disabled=true did not prove
that all launch paths suppressed vmd. Improvement is user-observed, but
its cause is NOT established. Do not claim that vmd is absent or that this
fixes every app/switcher stall. No further rootfs change is made here.

## GPU

Include0123 writable-control mask correction: observed CX a0222800 really
has POWER_ON. New opt-in midogpugx=1 defaults off, requires successful
RPM CX vote,0121 CX power result1 and BHS preparation result1.
Board DT identifies initial GFX corner4, CX level192, mem-acc corner2.
Pinned Android reference dbe33d8d742974d65b20971bcb91dee26ea56892:
msm_gfx_ldo.c, mem-acc-regulator.c, gdsc.c, clock-gcc-8953.c,
clock-local2.c and msm-clocks-hwio-8953.h. Device DT is local original
logs/twrp-live-20261104.dtb; no donor address or calibration substitution.

Gate CX on/software-owned, GX off/software-owned, prepared BHS control,
root off/no update, CFG mux/div/MND allzero (existing XO configuration),
and all five audited branches stopped with hardware control disabled.
Then exactly four allowed writes, with readback and bounded waits:
- gfx mem-acc0194415c bit0clear, corresponding to corner2; preserve others.
- GCC GX_DOMAIN_MISC0185b00c bit0clear, as Linux GFX provider probe.
- GCC root CMD01859000 bit1set, no source/PLL/frequency change.
- GX GDSCR0185901c SW_COLLAPSE clear after root-on, poll POWER_ON.

Root/GX each have1000 one-microsecond polls. Reject changed control fields
separately from status bits. After GX POWER_ON require BHS acknowledgement
bit1 in0185f028; otherwise log and stop. No branch enables, GPU register
reads, reset pulses, SMMU, PLL, shaders, CP, SCM PAS writes or acceleration.
No automatic rollback of partially powered domains. Any failed prerequisite
stops further stage writes; preserving powered rails is safer than guessing
a power-down sequence while firmware ownership is not established.

## Wi-Fi / SCM

New midoscmprobe=1 defaults off. Uses actual Qualcomm INFO availability
SMC only (fn c2000601 or82000601), not a PAS operation. Detect SMC64
then SMC32 convention using the reference INFO self-query. Do not fall
back after transport timeout/busy error. Query availability of PAS commands
1(init),2(memory),5(auth/reset),6(shutdown),7(supported), without invoking
them. Output has transport result and availability for every query.
Each request permits at most8 interrupted continuations and4 busy retries;
resume context/registers preserved, negative32-bit return sign handled.
No firmware/RPM/Pronto/radio/SMD writes or fallback to guessed legacy ABI.

Actual next dependencies after evidence: proper Pronto proxy XO/SCM clocks
and own L7/S7/S2 supply sequencing, reserved memory firmware copy with cache
maintenance, authenticated PAS6 and ready handshake, own NV/SMD/DXE/network.
PAS availability alone does not establish PAS6 support or a running radio.
GPU likewise still needs branch clocks/identity, reserved ZAP PAS13, SMMU,
CP execution and a userspace graphics bridge; GX power is not acceleration.

## Checks

Native GX harness enforces exact four-target write whitelist and ordering,
all prerequisite gates/no writes, mapping failures, every readback failure,
last-poll success/timeouts, hardware-shaped status bits and missing BHSack.
SCM harness rejects any non-INFO call, checks allowed query identifiers,
convention fallback, preserved interruption context and bounded errors.
ARM64 MidoInput object includes both implementations. Full linked kernel
and actual phone evidence are separate requirements before any success claim.
