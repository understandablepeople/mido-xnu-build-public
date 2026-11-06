# 0126 runtime and CBCR NoC status correction

Fresh TWRP pull logs/mmio-0126-live-20261106.txt:308360bytes,flush447.
Unlike0125 panic's stale0124 ring, this contains the new PAS supported
and Wi-Fi clock result lines. No panic text found in this captured console;
SpringBoard exec530996ms and Preferences793256/882728/1035059ms observed.
This is not an independent claim of full UI functionality or long-term stability.

- PAS6 and PAS13 each result0/supported1/SMC64: real peripheral support query,
  not merely command availability. No firmware authenticated or radio started.
- Wi-Fi crypto root0,cfg109,core00004ff0,bus0,iface20008000;
  GPLL0c0118000,PLLvotea1,APCSbranchvote1e407. No shared clocks reprogrammed.
- GPU CXa0222800/GXa0225800,clamp1100,supply3/root2 again verified.
- First AHBbranch59028 enable readback20008001 caused false control mismatch;
  result-5 prevented later branches and GPU register reads. No GPU MMIO occurred.

## Root cause and0127

Pinned Android clock-local2.c defines BRANCH_CHECK_MASK bits31:28,
ON nibble0, OFF nibble8 and NOC_FSM_ON nibble2. Previous comparison wrongly
included read-only bit29 in its control readback. The enable actually set bit0
and NoC on-state2, but this was not accepted by our software.

0127 shared mido_cbcr.h classifies status0/2 as on and requires local enable
bit0/hardwarecontrolbit1clear for GPU branch proof. Compare lower28 control
bits exactly; poll all16 possible status nibbles, accepting only0/2.
Require status8 plus enable/controlclear before any branch writes.
The later GPU read-only gate and host report use the same status rules.
Wi-Fi snapshot additionally prints core/bus/interface status-only on flags,
PLLlock and APCScrypto votes; voted CBCRs do not require local enablebit0.
No crypto root reprogramming, rail votes, firmware operations or radio DMA.

Native tests cover normal and observedNoC on values, every unsupported status
nibble, exact write whitelist, real control mismatch, bounded polling and GPU
read suppression. Parser regression accepts20008001 but rejects transitional,
off and unsupported statuses. MMIO lifetime fix0126 retained throughout.

Remaining Wi-Fi blockers are power/proxy/XO vote integration, reserved firmware
copy/cache maintenance/auth/startup, then SMD/NV/DXE/network; PAS support and
clock snapshot are not network readiness. GPU still needs complete clocks,
register access, ZAP/SMMU/CP and userspace graphics integration.

Local preflight185436Z:93 tests pass (one NDK skip), four ARM64 objects
pass, firmware/own-DT/combined memory and voltage plan pass. Historical
validator twelve numbering gaps/three CRLF scripts remain unchanged.
No0127 linked kernel or runtime results at this checkpoint.

## 0127 build and temporary boot

Sourcea12ac37150d8bae6da60bc011103d217cadd3103,CI42275190305 PASS.
Artifact checksum matched. Kernel SHA256
fbfd3cc7df8d51bf08e88b039ddada2e494c941c354abd269141ac327a93541b.
Image out/cbcr-0127-8cpu/package/mido-xnu-shim.img SHA256
3787e842c7565daea8d53eb7dd802532bfbc3b75169b007ebde8fcd03d5faf72.
Scanner2293760words,sole0xb33c14fullK256data,zero actual unsupported hits.
Baseline shim/DTB/ADT/memory/root/8CPU/CC and all combined flags preserved;
candidate packaged memory plan passes.
Verified one mido recovery, stockfastbootmido, knownlk2nd hash, lk2ndRAMboot
OKAY,productlk2nd-msm8953,0127RAMbootOKAY;bothstatus0. No partition flash
or rootfs modifications. Private logs/cbcr-0127-validation.json and
cbcr-0127-temp-boot-20261106.json. Loader acceptance only; actual branch
and GPU register results await user physical test and fresh TWRP console.
