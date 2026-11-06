# GPU/Wi-Fi investigation after stable 0112 touch (2026-11-06)

## Active: 0113 audit verified; 0114 HID metadata candidate

User confirms unchanged working UI/touch; Control Center opens only via
AssistiveTouch. Fresh0113 log verifies complete audit,8/8 CPUs, FT5435 and
WLED; GPU blockers1f (CX/GX off, required clocks stopped, clamps set and
selected supply not ready). No GPU enable claimed. See hid-0114.md for
raw snapshot and separate Built-In/DisplayIntegrated HID event correction;
48 native tests OK, ARM64 driver compile PASS, CI/hardware test pending.

See gpu-power-0113.md. Added tested mido fuse/corner voltage planning and
an opt-in, read-only12-register GCC/GFX-LDO audit hooked to platform start.
No GPU/SMMU access or power writes, even if coarse status has no blockers.
Default midogpu=0 touches no hardware. No acceleration or Wi-Fi enabled.
Native45 tests OK (NDK skipped), ASan/UBSan PASS, affected ARM64 object
compile PASS. Authorized source commit77e8b54 published; CI42172953662
PASS8m48s. Packaged separate candidate c5121993...c811e46, preserved exact
0112 boot inputs except added midogpu=1; stable0112 unchanged.
Phone was actually in stock fastboot after CI. Verified product mido,
RAM-booted known lk2nd, verified lk2nd-msm8953, RAM-booted0113: both
status0 Booting OKAY. No adb reboot or flash. Need user screen/touch check
and return TWRP for a fresh persisted GPU audit log; no runtime values yet.

## Read-only preflight completed, not an accelerated build

Fresh recovery pull: logs/input-0112-gpu-preflight-20261106.txt, 346876
bytes, persistent flush693, no ring wrap. Contains 8/8 CPU/SGI1 success,
FT5435 verification and repeated successful WLED module off/on readbacks.
The absence of a panic in this saved log is not an all-app stability test.
No recovery debugfs/MMIO reads, reboot, flash or phone filesystem writes.

Pinned Linux reference xiaomi-msm8953-devs/kernel_xiaomi_msm8953 at
dbe33d8d742974d65b20971bcb91dee26ea56892 explicitly lists A506 using
a530_pfp.fw, a530_pm4.fw and a506_zap. Its GMEM is 128 KiB + 8 KiB;
sharing command microcode does not make the A530 platform driver portable.

Read-only host debugfs extracted six GPU files from vendor_image.emmc.win
(872415232 bytes). Private copies and SHA256 manifest remain in ignored
research/mido-firmware. tools/mido_gpu_firmware.py validates the local
ELF32/Hexagon header, packed authentication data, split headers/segments,
memory extents and microcode word lengths. This is structural validation,
NOT cryptographic authentication: hardware_loaded/signature_verified=false.
Run: python -I tools/mido_gpu_firmware.py research/mido-firmware
Actual A506 metadata6684 bytes, b02 load segment5188 bytes, link address
0x5000, relocatable, alignment1 MiB. This link address is NOT a destination
physical address. Do not use it as a physical load address or reuse the
donor's fixed ZAP carveout. SCM PAS13 needs a separately reserved allocation
that does not overlap this phone's XNU, payload, framebuffer or carveouts.

Resolved local DT power chain: GX GDSCR0x0185901c, CX GDSCR0x0185904c;
GX parent is msm_gfx_ldo at0x0185f000, NOT a directly copied PMI8994 rail.
Its efuse resource is0x000a4000. The pinned msm_gfx_ldo.c uses per-chip
fuses, seven corners, CX-level and mem-acc corner maps. Port those semantics
before enabling GX or changing core clock; arbitrary fixed voltages are not
a safe substitute. GCC gfx registers are at0x01800000, not sailfish MMCC.
No GPU register or SCM PAS call has been tested in XNU on this phone.

Read-only FAT inspection of modem.emmc.win found /IMAGE/WCNSS.MDT plus
B00/B01/B02/B04/B06/B09/B10/B11/B12 (10 files). Extracted privately into
research/mido-firmware with wcnss-manifest.json. Also privately extracted
WCNSS_qcom_wlan_nv.bin, WCNSS_qcom_cfg.ini and WCNSS_cfg.dat from vendor
/firmware/wlan/prima; never publish calibration/config or substitute another
device's calibration. Pinned qcom_wcnss.c, qcom_wcnss_iris.c, subsys-pil-tz.c
and prima wlan_qct_dxe.c are now available locally. Presence of those files
does not prove WCNSS firmware startup, radio, scan, association or networking.

Validation: nine new synthetic firmware tests PASS; complete native suite
33 tests PASS, one NDK module skipped. Real private A506 bundle inspection
PASS; local JSON logs/gpu-a506-firmware-preflight-20261106.json. No private
firmware is required by committed tests. Stable0112 unchanged; no new kernel
patch/image built, no acceleration or Wi-Fi functionality claimed.

Next implementation: mido-specific GFX-LDO/CX/GX/clock power sequencing
with bounded timeouts and test doubles, then gated GPU identification;
SCM/ZAP, isolated SMMU and CP test precede any Mesa/CoreAnimation bridge.
Keep Wi-Fi firmware boot/SMD/DXE/network interface as a separate track.

User reports 0112 touch remains stable, Settings/Safari/Messages open, Phone
shows black, bottom Control Center gesture fails. These are user observations,
not yet checked against a fresh 0112 log. Do not replace stable input blindly.

Primary source repositories inspected at immutable commits:
- oosexgang/hakios-xnu-kernel: 2631f5d7d4f9d7322aca60991b34ba465dec343b
- joranv1/ios-sailfish: 6f27e41ff249f2680540ebe8ee5ab982c5e641c9

HakiOS README reports Metal acceleration on Adreno642L (SM7325). Source
contains GPU driver, Mesa/Metal bridges and Wi-Fi bringup reviews. Its
platform-specific transport and power code is not a mido driver.
ios-sailfish README reports Adreno530 CoreAnimation OpenGL ES acceleration
via Mesa freedreno and a kernel GPU driver, plus QCA6174 PCIe Wi-Fi. GPU
patches0119 onward cover power, CP, SMMU, zap, buffer/submit and presentation;
these are stronger A5xx-family references, not proven A506 support.

Local saved recovery DT independently identifies mido GPU chipid05000600,
MMIO01c00000 length40000, SMMU01c40000 length10000. Wi-Fi nodes identify
qcom,wcnss_wlan, Pronto remoteproc and SMEM/SMD WCNSS. Do not assume the
PCIe QCA6174 path or an ath11k stack fits this device. Exact firmware,
calibration paths and Linux driver bindings need backup/source inspection.

Existing phone-backup/BACKUPS directory is present in the old ios workspace.
Treat as read-only; preserve calibration/MAC/private data locally. Firmware
and register/clock/power references may come from the device backup, but
Android binary modules/libraries cannot simply be installed as XNU drivers.

Next: inventory firmware and DT dependencies without modifying phone; review
Adreno530 kernel/userspace interface against506; plan minimal gated GPU
power/ID/CP test with original image rollback, then rendering integration.
GPU probe alone is not CoreAnimation acceleration. Preserve cpus8 and0112.
Wi-Fi needs WCNSS firmware boot, transport, networking and iOS interface,
not only a successful firmware load. Keep it a separate bring-up track.
Control Center requires edge-coordinate/event-mask/UI-policy investigation;
Phone black screen needs its own process log, not a GPU diagnosis by default.
No new phone commands, reboot or flash during this source investigation.
