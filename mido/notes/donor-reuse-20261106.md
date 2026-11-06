# Reuse audit: Sailfish GPU and Wi-Fi frontends for mido

## Evidence and boundary

User reports the safe0127 image boots and works after disabling only
midogpustatus. This is a user observation, not a fresh captured runtime log.
No phone command, reboot, partition write, rootfs change, CI run or full kernel
build was made during this audit. Donor code is not linked into the kernel.

Sources inspected locally:
- Sailfish immutable commit6f27e41ff249f2680540ebe8ee5ab982c5e641c9.
- HakiOS local commita48d2b29dd58da5ef322052a7f4f73d7eb8eebc4.
- Android mido reference dbe33d8d742974d65b20971bcb91dee26ea56892.
These are inspected snapshots, not a claim about the latest upstream state.

## Reproducible donor preparation

Run from repository root:

    python -I tools/mido_prepare_donors.py research/sailfish-gpu-reference out/donor-analysis-new

The output must not exist. No build/push/install script is executed. Sources
are read with git show at the pinned commit, ignoring dirty donor worktrees.
Forty-four selected patches reconstruct six final kernel API/driver files.
The sweetgl bridge and IONetworking staging recipe are also retained. Every
patch and output file has a SHA256 in manifest.json. Original donor files are
unchanged. Two adapted frontend candidates are emitted separately:

- adapted/iokit/Kernel/arm/MidoGPU.cpp
- adapted/iokit/Kernel/arm/MidoWLAN.cpp

Actual output: out/donor-reuse-20261106-both,24files. These are offline
candidates, NOT a complete mido driver. Seven focused regression tests pass.
The adapted GPU frontend was separately staged into the ignored existing
build tree and compiled as one ARM64 object:0of1filesfailed,47984bytes.
Private logs/donor-gpu-frontend-compile.txt records the result. The first
attempt failed because its object output directory did not exist; creating
that directory resolved it. No driver source change was needed.
This compile checks headers/types only, not linking or hardware operation.
No downloaded Apple/third-party sources or private firmware are committed.
Full WSL native suite:100 tests,OK,one NDK-dependent skip,7.964seconds.
Private logs/donor-reuse-native-tests.txt. No full kernel build was run.

## GPU: reuse the renderer, replace the platform backend

Sailfish tools/sweetgl/sweet_drm.c already obtains chip ID, GMEM size/base
and maximum frequency from SweetGPU selector15. It is not necessary to
rewrite Mesa or the EAGL bridge to change the GPU identity. Preserve the
SweetGPU service name and selectors10..16 so the existing bridge can work.
The adapted frontend changes board guard and SweetSurface references to
MidoSurface/mido_surface_copy. Existing mido surfaces expose the memory
member used by the donor buffer importer. This is source compatibility,
not proof of correct DMA/cache synchronization or framebuffer presentation.

Sailfish bsd/dev/sweet_gpu.c:sweet_gpu_get_info HARDCODES chip05030002,
GMEM size/base100000, and a donor frequency. Mido chip05000600 and A506
GMEM128KiB+8KiB must come from the own-device binding/reference instead.
Do not claim that replacing those constants makes the GPU operational.

The donor backend hardcodes MMCC008c0000/GCC00300000/GPU00b00000/
SMMU00b40000, PMI8994 S2 programming, donor ZAP allocation, context/stream
configuration and display paths. Mido instead has GCC01800000, GPU01c00000,
SMMU01c40000 and msm_gfx_ldo. Do NOT execute the donor power/init thread,
600MHz vote, fixed carveout, SMMU setup or presentation unchanged.

New pinned Android kgsl_pwrctrl.c inspection establishes a concrete missing
piece in our current path: kgsl_pwrctrl_enable first sets a power level,
then enables rails, clocks, AXI bus voting, then calls regulator_enable.
kgsl_pwrctrl_axi reaches kgsl_pwrctrl_buslevel_update and ultimately
msm_bus_scale_client_update_request. Our six CBCR writes are not equivalent
to that complete sequence. This is a missing prerequisite to investigate,
NOT proof that bus voting alone caused or fixes the photographed abort.
kgsl_pwrctrl_clk also programs the active frequency and IOMMU clocks.
For A506, a5xx_regulator_enable differs from A530: the non530/540 path
uses RBBM_CLOCK_CNTL and hardware clockgating, not the A530 power-domain
sequence. It already requires accessible GPU registers, so copying it
before resolving the external abort would be another unsafe probe.

Next backend work: trace the mido DT bus votes and RPM clock resources
through pinned Android source; establish the full pre-MMIO access contract.
Keep midogpustatus=0. Do not guess reset/security writes, catch and ignore
external aborts, or reuse an A530 fixed memory map. Only then connect
isolated SMMU/BO/submit/fence implementation to the preserved frontend.
Mesa build also needs a pinned Mesa revision and macOS/iPhoneOS SDK;
no Mesa binaries or working rendering backend were produced here.

## Wi-Fi: reuse Darwin interface, not incompatible chip transport

Sailfish's final SailfishWLAN.cpp is an IOEthernet/Apple80211 frontend.
The adapted MidoWLAN.cpp preserves IO80211 class names, ioctl numbers and
link/frame/event contracts; it renames the service, bootarg and backend
callbacks to mido. The backend boundary is small:

- mido_wlan_output(mbuf_t): takes ownership of a transmitted frame.
- mido_wlan_a80211(set,type,val,data,len): Wi-Fi ioctl dispatcher.
- mido_wlan_iokit_attach(mac), link(up), input(mbuf), event(code,data,len).

This means the iOS network/interface layer need not be designed from zero.
However, the Apple80211 scan/association dispatcher currently lives inside
the donor's sailfish_wlan.c alongside QCA6174 logic, not entirely in the
C++ wrapper. It must be separated from radio-specific scan/join commands;
renaming the C++ file alone does not implement Wi-Fi.

Sailfish radio backend uses QCA6174 PCIe/BMI/HTC/WMI/HTT. HakiOS wifi/conf
selects WCN6750/ath11k plus QMI. Neither is mido Pronto/WCNSS/Prima DXE.
Do not copy donor firmware, board/calibration, PCIe addresses or ath11k.
Use mido's extracted firmware/calibration and original WCNSS/Prima protocol.
The existing mido WCNSS control/NV message builders are reusable but have
no operating firmware/SMD/DXE/network data path behind them yet.

qcom_wcnss.c provides a useful platform sequence: PAS init_image, relocatable
memory setup/load; regulators/IRIS, NV-download indication, IRIS configuration,
PAS6 auth_and_reset, ready interrupt, bounded timeout and cleanup. Own-device
DT supplies/proxy clocks and reservations must be reconciled with the
actual downstream subsys-pil-tz/prima path before choosing this sequence.
PAS supported=1 is not authentication or startup. Preserve calibration.

IONetworkingFamily headers are absent from the current mido build tree.
The retained donor0175-stage-ionetworking.sh pins Apple family170.140.2 at
f9f7e57b2132b82de09a26ddcbf56fd8125b4933 for xnu8796.141.3; it was NOT run.
Therefore the adapted WLAN frontend has NOT been compiled. Its prerequisite
is an explicit scoped IONetworking staging/integration, not another phone boot.

## Decision

Reuse Sailfish's Mesa/EAGL and GPU user-client contracts; reuse its Darwin
network frontend and extract the Apple80211 dispatch layer. Replace only
platform/backend portions with mido Android-derived sequencing/protocols.
Do not merge the donor's giant patch chain into mido or overwrite stable
input/display/rootfs. No claim of GPU acceleration or Wi-Fi operation.
