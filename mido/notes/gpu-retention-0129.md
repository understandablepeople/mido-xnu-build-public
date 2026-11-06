# 0129: mido GPU core retention candidate

## Verified runtime, not driver success

The phone was in recovery. The fresh safe0127 capture is private:
logs/safe0127-runtime-20261106.txt, 224769 bytes, console flush 252,
SHA256 b51ad10e87a0dc3c97a2eeb42a4854da707700ffcca05be998f3ae0f0e59edc0.
All six branch-enable checks passed; core CBCR 0x59020 was 0x00004f01.
PAS6 and PAS13 support queries returned transport 0 and supported 1.
These do not prove authentication, firmware startup, rendering or networking.
WCNSS_CTRL was absent. GPU status MMIO remained disabled in the safe image.
No new phone writes, reboot, partition flash or rootfs modifications occurred.

## Android-derived difference

Pinned Android commit dbe33d8d742974d65b20971bcb91dee26ea56892:
drivers/clk/msm/gdsc.c applies CLKFLAG_RETAIN_MEM and CLKFLAG_RETAIN_PERIPH
on non-root domain clocks when toggle_mem/toggle_periph are set.
Own CX GDSC references core_clk and does not request retain-mem/periph;
its enable hook consequently sets both flags. GX only has core_root_clk,
which that loop skips. drivers/clk/msm/clock-local2.c cbcr_set_flags maps
RETAIN_MEM to bit14 and RETAIN_PERIPH to bit13, with write barrier/delay.
Captured core value has bit14 but not bit13. Existing XNU branch requests
only ORed bit0 and never explicitly set bit13.

The candidate ORs 0x6000 into the existing core CBCR after power/root and
all six branch preflight checks, before enabling any branch. Existing MMIO
store helper includes dsb osh; delay1us and writable-bit readback follow.
Mismatch returns -7 before branch-enable writes, without speculative rollback.
All other control bits and the six-branch enable order are preserved.

This is NOT established as the cause or cure of the 0127 external abort.
It is NOT a complete reproduction of Android power ordering: this code runs
after GX validation whereas the Android retention hook belongs to CX enable.
Active frequency selection, AXI bus votes and IOMMU prerequisites still need
implementation/validation before another direct GPU register access.
The 0128 actual-backend-ready guard stays intact. Do not register a ready
backend just to bypass this guard or claim hardware acceleration.

## Validation and deployment status

Canonical header is reproduced by 0125 through 0129 patch replay.
Native ASan/UBSan tests cover preflight no-writes, retention readback failure,
all four initial retention-bit combinations, preservation of unrelated bits,
all branch failures/timeouts and mapping cleanup.
Final full native suite: 105 tests PASS, one NDK-dependent skip, 9.784s.
Local ARM64 compile: all 17 bridge/Input/network objects PASS, including
MidoInput with the updated retention header. Focused diff whitespace check
PASS; patch context whitespace is intentional. No new kernel link,
CI build, Mesa userspace installation or temporary phone boot is claimed.

## Remaining hardware path

GPU: Android-derived active rate/rail/bus/IOMMU contract, safe MMIO access,
A506 CP initialization, BO mapping, submission and fences; then register the
real backend and validate Mesa/EAGL rendering on device.
Wi-Fi: Pronto PAS6 firmware startup with own reserved-memory ownership,
supplies/proxy clocks, SMD control and DXE packet transport, Apple80211
dispatch, actual scan/association and traffic. Existing donor frontends alone
cannot provide these. The current physical-backend registration callers exist
only in host tests; no fake runtime registration has been introduced.
