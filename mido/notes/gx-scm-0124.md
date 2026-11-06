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

## Own-board Wi-Fi power dependencies prepared during CI

Host inspector --power-plan resolves actual regulator and clock phandles,
validates units, limits, proxy references and shared rails without hardware
access. Actual board: S7 RPM-level384; S2 level256..384 shared with GPU;
L5 1.8V shared by ProntoPX/IRISdigital, L7 1.8V shared by IRISXO/proxyPLL,
L19 1.3V RF analog and L9 3.3V PA. Five proxy clocks include XO and SCM
core/interface/bus/source, source rate80MHz. Shared-vote aggregation is
mandatory, not seven independent overwrite requests. No rail votes sent.
Synthetic tests reject bad limits, ambiguous handles and mismatched proxy
dependencies; private actual result logs/wcnss-power-dependencies-20261106.json.
Do not substitute the generic remoteproc example supplies for these bindings.

## Full build and temporary boot result

CI42260825852 for58d1561944e8fb3c739115e2687874c0f4e0cc98 PASS.
Kernel xnu/out-0124/kernel.development.mido SHA256
358473f8b5e627a004f2e4f73d9953fdcea00a5a3f77f75d119235d6db381232.
Image out/gx-scm-0124-8cpu/package/mido-xnu-shim.img SHA256
5835eafa42945d1912dc0e4e2c5713f1528ab55e0980e99b686483da8d11264d.
CI artifact checksum matched. Exact0122 shim/DTB/ADT/memory/root/outer
cmdline and8CPU/working edge events preserved; only inner additions
midogpugx=1 midoscmprobe=1. Instruction scan sole0xb334d4 hit is fullK256
data, zero actual unsupported instruction hits. Latest host preflight
79testsPASS(oneNDKskip),4ARM64objectsPASS,ownfirmware/DTpowerplanPASS.
Whole-repository validator still reports old patch-number gaps/threeCRLF
scripts, not fixed or mislabeled as passing. Hostfollowup40e11a9 published
without another kernel build.

Verified one mido TWRP, stockfastboot productmido, knownlk2nd checksum,
lk2ndRAMboot accepted, productlk2nd-msm8953,0124RAMboot accepted.
Both boot sends and Booting responses OKAY, status0. No partition flash,
additional rootfs modification or firmware/calibration upload. Private
logs/gx-scm-0124-validation.json and gx-scm-0124-temp-boot-20261106.json.
Loader acceptance only: GXon/SMC success/iOSUI not yet observed.

Await physical startup, Settings/Safari/SMS, touch/sleep/CC comparison and
returnTWRP. Pull fresh persistent log for GX exact preflight/readback,
memacc/clamp/root/POWER_ON/BHSack and SCM ABI/availability. Do not claim
acceleration or networking from this power/protocol discovery stage.
