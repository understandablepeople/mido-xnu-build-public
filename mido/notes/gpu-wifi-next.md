# GPU/Wi-Fi investigation after stable 0112 touch (2026-11-06)

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
