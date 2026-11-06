# 0130: shared Pronto power and GPU active-rate candidate

## Implemented runtime requests

Both switches default off. midowifipower=1 runs after successful touch rails,
in the same serialized RPM context as the GPU vote. Thirteen bounded RPM
transactions enable six merged supplies and XO in the own-board active/sleep
sets. L5 merges vddpx/vdddig; L7 combines iris 10mA plus proxy PLL 18mA.
Supply order follows the pinned Pronto core/IRIS enable order. Sleep-set
support is explicit; existing RPM callers retain active-set behavior.
Shared smpa2 CX requests use at least level256, not microvolts; a higher floor
is preserved. The floor is raised before sending the CX request so a missing
ack cannot cause the later GPU vote to lower a possibly accepted WLAN vote.
Failures stop later requests without speculative rollback of shared supplies.

midogpurate=1 selects nominal133330000Hz using GPLL0/2, source5, HID5,
matching the pinned Android F_MM table and own DT graphics corner1.
It does not retune a PLL. All six branches, CX/GX, clamp, supply, core
retention, existing XO config and GPLL0 lock are checked before writes.
Three ordered writes preserve the existing PLL vote bits, select config505,
and request RCG update. Readback/update are bounded; every temporary mapping
is unmapped. Negative results prevent the subsequent status probe.
The status helper still requires a real ready backend before any GPU mapping;
accepting config505 does not bypass that guard. No raw GPU access was enabled.

## Source evidence and validation

Android snapshot dbe33d8d742974d65b20971bcb91dee26ea56892:
wcnss/wcnss_vreg.c, rpm-smd-regulator.c, clock-gcc-8953.c,
clock-local2.c, clock-rpm.c, clock-rpm.h, msm-clocks-hwio-8953.h.
The live own-device DT was compared against all six runtime supply groups,
seven roles, proxy load, active/sleep sets, units and graphics corner1: PASS.
The source snapshots and DT remain private/ignored.

Full preflight logs/preflight-20261106T202003Z: 109 tests PASS, one NDK
skip, 9.583s; 20 ARM64 objects PASS, covering bridges, Input/HID, network,
exec and VM paths. Firmware checks, own-board power plan and packaged-memory
nonoverlap pass. Historical repository validator still reports the same
12 patch-number gaps and three unrelated CRLF shell files; these were not
changed. Object-import audit against0127 plus the new objects has zero
unmatched imports, not a full-link proof. Patch replay reconstructs all
canonical sources including both new runtime headers.

The combined reporter distinguishes nominal-rate selection and supply/XO
acknowledgements from physical driver success. Missing/failed sleep requests
and subsequent failures do not count as success. GPU acceleration and Wi-Fi
network remain false. Fresh recovery collection still contains safe0127;
it is not runtime evidence for0130.

## Deployment boundary

One full CI/link and RAM-only lk2nd candidate is planned after this commit.
Preserve eight CPUs, touch, buttons, sleep, ControlCenter and all existing
safe0127 flags; add only midowifipower=1 and midogpurate=1. Keep GPU raw
status off and do not enable unbacked GPU/WLAN frontends. No partitions or
rootfs need to be written for this prerequisite test.

Remaining: bus/QoS/IOMMU contract and A506 CP/BO/fences; Pronto IRIS/SCM
crypto clocks/PAS6 authenticated firmware startup, SMD and DXE, Apple80211
operations and userspace rendering integration. This is a physical-power
candidate, NOT a completed GPU/WLAN driver or guaranteed first-boot success.
