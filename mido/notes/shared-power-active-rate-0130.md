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

## Additional Android path traced while CI runs

Own live DT /soc/arm,smmu-kgsl@1c40000 uses the string GPU for
qcom,tz-device-id, static context banks, halt and skip-init. Its vdd-supply
resolves to the CX GDSC at185904c, not the GX domain or the GFX LDO.
Pinned arm-smmu.c register_regulator_notifier installs a CX regulator hook:
on REGULATOR_EVENT_ENABLE it enables its clocks, calls
arm_smmu_restore_sec_cfg(smmu,0), then qsmmuv2_resume. Hardware probe also
calls restore before its first SMMU ID read. The own SMMU clocks are the
already known GPU AHB and BIMC_GFX branches.

msm_tz_smmu.c/h maps the GPU string to TZ_DEVICE_GPU=18. scm.c
scm_restore_sec_cfg uses MP service0xC, command2, two value arguments
(device18,context0). This ID is NOT the GPU firmware PAS13.
These files were downloaded at the same pinned Android commit for reading.
The current XNU CX path has no equivalent notifier/secure restore sequence.
This is another confirmed missing source operation, NOT proof that it alone
caused the photographed GPU external abort. No restore SMC, SMMU global
register write, blanket bypass or raw GPU probe was added to0130. Trace
clock/notifier ordering and existing secure context handoff before enabling
this operation; skip-init is not permission to replace the global SMMU state
with the A530 donor layout.

## Full build and temporary boot result

CI42287667388 SUCCESS for source960e7aaf8f6b93008ffd4bde7c213ad0215ea0b2.
The full kernel compiled and linked. Kernel SHA256:
93ae6fe227eec0908a06291b107b380d358dfb612373660a01c37a065e1e2e77.
Candidate out/shared-power-rate-0130-8cpu/package/mido-xnu-shim.img SHA256:
081a3f9b1ab46cfb63ba0f5c2bb74ce268bf98d0dd33cc9a62fe78fcdfb54e62.
Artifact checksum and baseline shim/DTB/ADT/memory/root preservation passed.
2322432 instruction words scanned: one complete SHA256 K256 data table hit,
zero actual unsupported Cortex-A53 instructions. Packaged memory plan passed.

The existing safe0127 command line gained only midowifipower=1 and
midogpurate=1; eight CPUs and UI fixes remain, raw GPU status stays off.
Verified mido recovery, stock product mido, known lk2nd loader hash, then
product lk2nd-msm8953. Both fastboot boot commands returned OKAY/status0.
No partitions were flashed and no additional rootfs writes were issued.
This proves loader acceptance, NOT a booted UI, successful new RPM/rate
requests, GPU acceleration or networking. Await physical UI check and one
fresh recovery capture. The safe0127 image remains available unchanged.
Private validation and boot reports use prefix shared-power-rate-0130.
