# 0125: gated GPU branches and peripheral PAS support

Predecessor hardware evidence: runtime-0124.md. No acceleration or Wi-Fi
connectivity is implied by this stage.

## GPU

Opt-in midogpuclocks=1, only after GX result 1. GCC-only access to the
existing 01858000/8000 window. Requires forced XO root on/no update,
configuration exactly zero, CX/GX on/not collapsed, clamp bit0 clear,
supply status bits0/1 set, and all six branches disabled/hardware control
clear before the first write.

Ordered branch enable-bit-only writes:
AHB59028, BIMC_GPU59030, BIMC_GFX59034, TIMER59040, AON59044, CORE59020.
Each preserves other control fields and waits at most 1000us for CLK_OFF
bit31 to clear, checking all other bits match the request. First mismatch
or timeout stops later writes; no guessed rollback. Mapping is released.

BIMC_GFX59034 was omitted from the earlier five-branch coarse snapshot;
its own new per-branch log is required, not just blockers00. Pinned Android
clock-gcc-8953.c and msm-clocks-hwio-8953.h define both BIMC branches at
GCC/GFX views of the same own-board clock-controller physical base;
clock-local2.c establishes enable bit0, hardware-control bit1/off bit31.
XO-only core clock is a safe bring-up rate, not performance tuning.
No GPU register writes, PLL programming, SMMU, CP or shaders.

## Wi-Fi and GPU secure firmware prerequisites

Reuse bounded SCM register transport (8 interrupted continuations, 4 busy
retries). INFO availability remains atomic 82000601/c2000601. Only after
PAS command7 availability, send yielding 02000207/42000207 with arginfo1
and peripheral6 (WCNSS) /13 (GPU ZAP). x0 is transport result; x1 is
peripheral support, logged separately. On transport error stop immediately;
an unsupported peripheral does not prevent querying the other one.

No init-image, memory setup, authentication/reset/shutdown calls; no firmware
or radio writes. Supply/proxy-clock aggregation and reserved-buffer cache
maintenance remain required before starting Pronto or GPU ZAP.

## Checks

Native sanitized harness: exact six-target write order, bit preservation,
all power/root/branch gates before any writes, mapping failure/cleanup,
each branch control mismatch and timeout, last-poll success, default off.
SCM harness admits INFO and supported-only function identifiers, PAS6/13
arguments, yielding convention, fallback, context continuation, bounded
transport errors and absent command7. Patch reconstruction compares all
canonical headers and driver with the actual kernel patch series.

Local validation 2026-11-06: preflight175028Z reports 80 tests passing
(one NDK skip), four ARM64 objects passing, own firmware/power-plan passing.
Additional new-header patch reconstruction test passes. First preflight
174942Z failed because the clocks include preceded ml_io_unmap declaration;
include order fixed and ARM64 rechecked. Repository-wide validator retains
the known 12 historical patch-number gaps and three unrelated CRLF scripts.
No linked kernel, CI run, image or hardware execution for0125 yet.
User explicitly authorized scoped commit/push on 2026-11-06 after batching.

## Combined additions before the first candidate build

midogpustatus=1: only after clocks result1, re-map GCC and require all six
branches on, both domains on, supply/clamp/root correct. Then read only
A5xx word offsets 4f5 RBBM_STATUS, 530 STATUS3, 4f4 AHB_ERROR_STATUS,
3000 VBIF_VERSION from own-DT GPU aperture01c00000/40000. No chip-ID claim:
VBIF version is not A506 identity. Zero/all-ones version is a failed probe.
All successful mappings released. Entry marker precedes reads so a hardware
bus stall is distinguishable; MMIO bus completion itself has no software timeout.

midowificlocks=1: eight read-only GCC values: crypto RCGR command/config,
core/bus/iface CBCR, GPLL0 mode/vote and APCS branch vote. Own DT hashed IDs
match pinned include/dt-bindings/clock/msm-clocks-8953.h: XO pilot voter,
gcc_crypto_clk/ahb/axi and crypto_clk_src. Target80MHz NOT programmed.
Firmware, shared supplies and XO remote votes NOT sent.

Wi-Fi SMEM discovery, SCM support and crypto-clock snapshot now execute
before GPU requests so later GPU MMIO failure cannot hide those results.
They do not depend on GPU success. Existing touch/RPM path stays serialized.

Host mido_bringup_plan.py checks actual payload-managed arena and segment
bounds against own-DT Pronto reservation, temporary shim/tags/payload,
framebuffer and other fixed reservations. This is a packaging nonoverlap
check, not runtime ownership or secure firmware authorization. Shared rail
voltage floors aggregated per active/sleep set, existing GPU CX192 floor
preserved; mixed units/conflicting constraints rejected. Proxy PLL load/XO
vote integration remains unresolved and must precede actual firmware startup.
The host tool does not issue any hardware requests.

Final combined checks: preflight180217Z four ARM64 objects, firmware, own DT,
memory/vote plan and recovery reads pass; final native suite87 tests pass
(one NDK skip). Historical repository-integrity issues remain unchanged.

Additional native harness enforces exact GPU/Wi-Fi read whitelist, no writes,
all gating failures and mapping cleanup. PAS harness additionally covers
PAS6 unsupported while PAS13 still queried, PAS busy exhaustion, and direct
PAS interruption exhaustion. New host tests cover shared supply constraints,
active/sleep separation, memory edges, payload table failures and overlap.

## CI source and one-pull result protocol

Kernel source dbf2ee477f8e63efcf1b847faf78772c19f74414 published; one build
CI42267277194. No runtime result until candidate image is actually booted.
Host-only follow-up tools/mido_bringup_report.py requires a fresh single-boot
console and checks six exact branch addresses, on/control values, bounded
poll counts, final stage results, nonzero/non-all-ones VBIF and PAS transport
versus support. Old0124 log deliberately reports five missing proof groups;
never labels INFO command availability as peripheral support. All reports
keep acceleration/network false: these are prerequisite diagnostics only.
Final expanded host suite91 tests pass (one NDK skip); four ARM64 objects
were already checked for the identical kernel source. No second kernel CI
is needed for the host parser/tests/documentation follow-up.
