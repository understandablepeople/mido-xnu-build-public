# 0113: mido GPU power planning and opt-in state audit

Status: source and local tests ready; no full CI build or phone boot yet.
This is the first board-specific GPU bring-up stage, NOT acceleration.
The stable 0112 image is unchanged.

## Source and hardware provenance

Android reference: xiaomi-msm8953-devs/kernel_xiaomi_msm8953 at
 dbe33d8d742974d65b20971bcb91dee26ea56892:
- drivers/regulator/msm_gfx_ldo.c: fuse layout, signed-magnitude voltage
  conversion, adjustment/clamping and LDO/BHS selection.
- drivers/clk/msm/clock-gcc-8953.c and msm-clocks-hwio-8953.h: clock offsets.
- drivers/regulator/gdsc.c: GDSCR power/collapse/hardware-control bits.

The saved mido recovery DT independently identifies the GFX-LDO supply
chain, domain addresses and six voltage/dependency tables. All six tables
were compared against the implementation and match. Private DT SHA256:
663ebfe21b29f028508b9eaf1a55dd14cf56cb5dbb773d15c8ff1042fc246121.
No DT dump, fuse data, firmware or calibration is part of this patch.

## Implemented, but not yet exercised on phone

mido/gpu/mido_gpu_power.h is shared by host tests and the kernel patch.
Its original portable implementation accepts already-read fuse rows65/73;
it does not read fuses or write power registers itself. Row65 bit11 enables
LDO operation for corners1..3; corners4..7 or a disabled fuse use BHS.
Row73 fields46:42,41:37,36:32 are five-bit signed-magnitude corrections in
10 mV steps, not two's-complement values. Reference voltages580/650/720 mV
receive the board's35/25/0 mV adjustments, then board-specific floor/ceiling
clamps. VREF is rounded upward to5 mV from375 mV. CX levels are regulator
levels, NOT literal microvolts. Invalid corner inputs leave output intact.
This planner does not implement rail votes, mem-acc writes or transitions.

A second pure function collects exactly12 whitelisted GCC/GFX-LDO registers.
A failed reader callback leaves the output unchanged. Coarse blocker bits:
- 0x01 CX domain not observed software-controlled/on/not collapsed.
- 0x02 GX domain not observed software-controlled/on/not collapsed.
- 0x04 a required core/AHB/memory/timer/AON branch is not enabled/running.
- 0x08 GMEM or LDO IO clamp asserted.
- 0x10 selected LDO/BHS path lacks its ready/ack indication.
- 0x20 root clock update pending.

A zero mask is NOT permission to access GPU memory or submit commands.
The sequential snapshot is not atomic, and does not establish RPM vote
ownership, clock rate, secure permissions, SMMU mappings or ZAP authentication.

## Kernel integration and safety boundary

xnu/patches/0113-mido-gpu-power-audit.patch adds two headers and one call
from MidoPlatformExpert::start after platform registration. It does not
change input, display, CPU topology, root selection or Android partitions.

- No midogpu argument, or midogpu=0: no mapping or MMIO access from this code.
- midogpu=1: map only0x01858000..0x0185ffff and log the12 fixed registers.
- Other values: refuse hardware access; do not interpret2 as enable-GPU.
- No register writes, efuse reads, SCM calls, GPU/SMMU mapping or firmware
  upload. No accelerator service is advertised to iOS.
- The mapping is permanent, matching this XNU's ml_io_map lifetime rules.
- There are12 software reads and no retries/polls. This is NOT a mechanism
  to catch an MMIO external abort or impose a hardware-bus timeout. These
  GCC/LDO accesses still require a controlled hardware test.

Expected log prefix: MIDO GPU: audit-only; final line explicitly states
no writes and acceleration disabled. Source includes the correct MSM8953
GCC base, not sailfish's MMCC or PMI8994 regulator settings.

## Validation on 2026-11-06

- Full native suite: Ran45 tests, OK, one NDK module skipped.
- New power/audit tests:12 PASS including all96 signed fuse combinations,
  randomized dependency maps, invalid corner preservation,12 injected read
  failures, independent blockers, boot-argument gates and no mock writes.
- GCC ASan/UBSan harness: PASS, including36864 randomized fuse/corner inputs.
- Kernel patch reconstruction from0016 +0046 +0059 +0113: PASS; both emitted
  headers exactly match the canonical tested headers.
- Current MidoPlatformExpert.cpp cross-compile with XNU build-tree flags:
  PASS, real ARM64 Mach-O object34392 bytes. This is not a complete link.
- Instruction sections of that object:407 words, zero matches for the
  existing A53 scanner's unsupported instruction classes. This is only
  an object-level check, not a full-kernel certification.
- Stable0112 image SHA256 remains
  4810436b84324a1bccd090ba54feb29aef60a49cd6efc9ea8b51829f78953c93.
- adb reports recovery; no reboot/boot/flash or recovery MMIO/debugfs reads.

## Next gate

User explicitly authorized the source commit/push on2026-11-06 for the
existing GitHub Actions kernel workflow. Full CI and boot are still pending.
Do not stage unrelated shim/build.sh, NOTES.md, local repair tools, logs,
research, device dumps or firmware. No new branch is required.
Commit only reviewed source/tests/docs/0113, push to
pub/mido-port, require successful full CI, package a separate candidate with
cpus=8 and midogpu=1 while preserving0112 ADT/DTB/shim/root arguments, then
verify hashes and unsupported-instruction scan before any temporary boot.

Only then collect the runtime clock/domain snapshot. A powered-off snapshot
is useful evidence, not a failed acceleration test. Actual regulator/RPM/
mem-acc and clock sequencing comes next, followed by GPU identity, reserved
ZAP memory/SCM PAS13, isolated SMMU and CP execution. Port suitable A5xx
command/Mesa interfaces only after those lower layers pass on this phone.
Wi-Fi remains a separate WCNSS/SMD/DXE/IONetworking track; no Wi-Fi claim.
