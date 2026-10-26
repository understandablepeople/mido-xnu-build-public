# mido: observed recovery hardware

Source: the successful local capture in artifacts/live-recovery. It was made
under TWRP 3.7.0_12-0, uid 0, kernel 4.9.337~zLOS-1bf4601a. This is not the
Android LineageOS 3.18 kernel, nor a direct fastboot handoff measurement.

## Confirmed observations

- The live FDT is 266752 bytes and has a valid FDT v17 structure.
- The memory node contains two address/size pairs: base 0x10000000, size
  0x70000000; base 0x80000000, size 0x80000000. These are raw DT banks, not
  universally free payload space. Firmware carve-outs must be excluded.
- Recovery /proc/iomem lists System RAM at 0x10000000-0x849fffff,
  0x86800000-0x86bfffff and 0x8ee00000-0xffffffff, inclusive. Allocations and
  reserved/CMA ranges inside these intervals are not safe scratch memory.
- Recovery kernel code is reported at 0x10080000-0x1183ffff. This differs from
  0x80008000 in the saved boot header. Do not use the header as proof of the
  address at which the bootloader actually enters a payload.
- Live chosen initrd-start is 0x13600000, initrd-end is 0x14dbed6e.
- The selected panel is NT35532, 1080x1920, video mode DSI. Its DT timing is
  60 Hz. Panel link bpp is 24; this is distinct from the 32-bit framebuffer.
- fb0 reports 1080x3840 virtual size, stride 4352 bytes, 32 bits per pixel.
  The virtual height is not the physical panel height. 1080*4 is 4320 bytes:
  a display test that assumes packed rows would use the wrong stride.
- The active touch input is ft5435_ts, on I2C bus 3 at address 0x38, with
  compatible focaltech,5435. The driver reports Device ID 0x54. Synaptics and
  Goodix touchscreen candidate nodes in the DT are not proof of active devices.
- The interrupt controller remains qcom,msm-qgic2, with register windows at
  0x0b000000 and 0x0b002000. PSCI uses SMC.

## Remaining boot blockers

1. The physical bootloader framebuffer base, pixel layout and display scanout
   state are not established by Linux's reserved splash region alone.
2. Recovery's framebuffer allocation may differ from the bootloader splash.
   Even a successful fbprobe query cannot by itself justify physical writes
   after fastboot handoff. A reported address may also be a DMA/IOMMU address.
3. The address rewrite and ARM64 handoff bridge have now been identified in the
   phone's aboot. Execution level, inherited display state and safe scratch
   ranges still require a controlled loader test; they must not be guessed.
4. The separate persist readback is now verified. Preserve it with the original
   TWRP backup; neither is a reason to replace low-level bootloader partitions.
5. XNU needs a GICv2-compatible path and eventually eMMC and FocalTech support;
   swapping sweet constants is not a complete port.

## Read-only framebuffer query

tools/fbprobe.c opens fb0 with O_RDONLY and uses only FBIOGET_FSCREENINFO and
FBIOGET_VSCREENINFO. It does not mmap, write pixels, change video mode, or
access block devices. It is an ordinary Linux executable for the running
recovery, not a boot image. Its source contains no shell execution or network
access. It reports addresses without dereferencing them.

Build on the host with tools/build-fbprobe.ps1 using the installed Android NDK
28.2.13676358. The static ARM64 binary is written to artifacts/fbprobe/fbprobe.
Compilation is not an on-device runtime test.

To run, the user must explicitly copy it into recovery's /tmp RAM filesystem,
mark it executable and invoke it. That writes a temporary program file in RAM,
but does not flash partitions or draw on the screen. Keep the phone in TWRP.

The current workspace has no bootable mido shim and no installed iOS.

## Successful framebuffer query

The user built and ran fbprobe in TWRP. The local executable is 2140336 bytes,
SHA-256 3E6E47535589588277E86592A1885A4A4853BEB2E8BA5DF6E792A2B880E5C4A6.
artifacts/fbprobe-run/fbprobe.json reports smem_start 0, length 16711680,
line_length 4352, 1080x1920 visible, 1080x3840 virtual, offsets 0/0 and 32 bpp.
Channel offsets are red 0, green 8, blue 16, alpha 24, each eight bits. This
describes little-endian RGBA bytes in the recovery framebuffer, not a proven
bootloader splash format. Zero is not a writable framebuffer address.

## Pinned source audit

The zeelog/android_kernel_xiaomi_mido commit matching the recovery suffix was
resolved to 1bf4601a044920feba9d76898c8cf225b7d19477. Read-only reference files
are under upstream/kernel-reference. In drivers/video/fbdev/msm/mdss_fb.c the
driver can leave smem_start zero when no contiguous framebuffer region exists;
the ION allocation path also uses its own buffer mapping. Thus a successful
FBIOGET_FSCREENINFO returning zero does not supply a bare-metal physical pointer.
This is a code-supported explanation, not proof of the exact allocation path
that the running recovery selected. No extra raw memory probes are planned.

An independent source path was found in msm8916-mainline/lk2nd, pinned to
fd380ac637d1af38598e3f3c5321d4c962b96315. Its
lk2nd/device/dts/msm8953/msm8953-xiaomi-common.dts explicitly lists mido and
the NT35532 panel. This is device/panel support in a bootloader, not an iOS port
and not evidence that a particular release is safe to boot on this phone.

The generic LK reference has ARM64 recognition, gzip handling, configurable
boot-header address overrides and a secure-monitor ARM64 handoff. It is not
the phone's exact proprietary aboot binary. The observed address difference
cannot yet be attributed to one particular branch of that reference code.

The local aboot/abootbak and separate persist readbacks are now complete.
tools/readback-firmware.ps1
requires existing root TWRP, verifies all three partition symlinks and sizes
against the recorded mido layout before copying, reads each source into /tmp,
then verifies the host copies against recovery SHA-256 and the partition size.
All dd destinations are uniquely named /tmp files, never partitions. Keep these
files private. There are still no boot or flash commands to run.

## Completed bootloader readback and binary analysis

The three host copies match the recovery checksums and partition lengths.
aboot and abootbak are byte-identical 1 MiB ELF32 ARM executables, SHA-256
873A4F8013E6E9F8057AC40E6E086DB701CC13818C07318AF71D27941A59C448.
persist is 32 MiB. Its content was not parsed; it remains private calibration
data, not a source to publish or a file to flash experimentally.

tools/inspect_aboot.py verifies the manifest and ELF bounds before disassembly.
It uses Capstone 5.0.6, installed only under artifacts/python-deps. Address-specific
annotations are enabled only for the exact aboot SHA-256 above. Reproduce with:

    python -m pip install --only-binary=:all: --target artifacts/python-deps capstone==5.0.6
    python tools/inspect_aboot.py artifacts/firmware-readback artifacts/NEW_ABOOT_ANALYSIS

Canonical output is artifacts/aboot-analysis/report.json plus five assembly
listings. No firmware code was executed by this analysis.

Observed address rewrite function: VA 0x8f6294a0. It calls the memory-bank
selector at 0x8f60496c and overwrites boot header kernel, ramdisk and tags fields:

| Destination | Offset from selected bank base |
| --- | --- |
| ARM32 kernel | 0x00008000 |
| ARM64 kernel | 0x00080000 |
| ramdisk | 0x03600000 |
| DTB/tags | 0x03400000 |

The ARM64 recognition call site compares the word at kernel + 0x38 with
0x644d5241. Using the observed recovery bank base 0x10000000 predicts kernel
0x10080000 and initrd 0x13600000, matching the recovery capture. DTB 0x13400000
is still a static prediction rather than a captured pointer. The ARM64 dispatch
at 0x8f62ac88 transfers through a secure-monitor bridge at 0x8f6162b8. These
findings establish a loading path, not XNU hardware compatibility or a boot result.

## Next controlled stage

A pristine official lk2nd 23.1 msm8953 candidate was downloaded to
artifacts/boot-candidates/lk2nd-msm8953-23.1.img. It is 368656 bytes and matches
the GitHub release asset digest:
2170c90c4b28a0d6dd31ec942500dc1fc4da94a34dbfd0676238ba1de1353cfa.
Release source commit: e9c8b21735c13dd7ace808b1e35451638f0a0c6d.
Its embedded device tree includes /lk2nd/mido and the NT35532 panel; these were
verified in the downloaded binary, not only the current source branch.

The candidate has a legacy Qualcomm QCDT boot layout (dt_size 8192 at header
offset 40), which the strict v0 inspector intentionally does not support. It
must not be interpreted as Android boot header version 8192 or repacked blindly.
Its mido identification tree has board-id 0x1000b, while the recovery tree
contains 0xb; successful selection by this proprietary bootloader has not been
tested. Device support and a matching release checksum do not eliminate risk.

The release source defaults to ABOOT_STANDALONE=1 and cont-splash. This skips
stock device-info initialization in the corresponding source conditional, but
it is not a proof that every startup path is storage-write-free. No blanket
claim of zero persistent side effects is made for running another bootloader.

First check Windows enumeration in stock fastboot, without executing the
candidate. After that, a separately reviewed temporary boot test can exercise
display, USB and device detection and export the lk2nd log. Do not use flash,
erase, format, lock or unlock commands. The temporary boot test has now
succeeded; see the observations below. There
is still no mido XNU kernel or installed iOS.

## First temporary lk2nd boot: 2026-10-25

The user booted the verified candidate through stock fastboot without a flash
command. A screen photograph shows lk2nd-msm8953 23.1, mido identification,
NT35532 panel and ARM64 availability. USB fastboot responded to oem log and
the staged log was saved as artifacts/lk2nd-first-boot.log (4943 bytes).

The log reports execution at 0x10008000 and an incoming DTB at 0x13400000,
2964 bytes long. This confirms the previously predicted DTB address for this
boot, not a fixed address contract for all future boots.

Continuous splash was detected on RGB_0: base 0x90001000, stride 3240 bytes,
1080x1920, hardware format 0x2243f, three bytes per pixel. This is distinct
from recovery fb0 (4352-byte stride, four bytes per pixel). The hardware
format still needs decoding before selecting a bare-metal pixel byte order.
Do not reuse recovery RGBA assumptions or write beyond the active surface.

Internal eMMC initialized in HS400 mode with capacity 62537072640 bytes.
The slot2 MMC/SD probe failed; that does not show internal eMMC failure.
lk2nd exposes wrapper partitions, including a 512 KiB lk2nd slice and a
63 MiB boot slice. It failed normal boot with Invalid boot image header
and fell back to fastboot. The project reserves the first 512 KiB of the
boot partition, so this error alone is not evidence of a damaged original
Android image. No repair, flash or erase is justified by this message.

The next payload must be a separately reviewed minimal ARM64 bring-up test,
not a sweet image or XNU deployment. Confirm its loading and handoff contract,
execution level and display format before executing it. No such test image
had been built at that stage. The later result is recorded below.

## Hardware-confirmed standalone ARM64 test: 2026-10-25

The corrected screen-test v2 was built, reviewed, CPU-emulated and sent through
the temporary lk2nd fastboot boot path without any flash command. The handset
photograph confirms MIDO ARM64, EL1, DTB OK, RAM ONLY, NOT IOS and the expected
grayscale strip. Thus the payload reached AArch64 EL1, accepted the incoming
diagnostic DTB and loader-exported framebuffer, and visibly drew on the panel.
The first 720 rows were changed; lower lk2nd text remains as stale pixels.
The payload has no interactive menu or USB service and deliberately halts.

The reviewed image hash is
8be499be41bff90f845596872ea902ca30c3a624009e092fb36eb274cc3d2e1f.
Sources, limitations and emulator details are in screen-test/README.md. The
photo is artifacts/hardware-proof-screen-v2/mido-arm64-el1.png. This milestone
does not establish an XNU boot, an iOS port, working interrupts/timers or any
general-purpose device drivers. Further payloads still need separate review.

## Next EL1 diagnostic submitted: 2026-10-25

The controlled BRK/ERET and virtual-counter diagnostic in diagnostics/ was
built and reviewed. Its 20 modeled scenarios and 40 ordinary regression cases
pass; the original screen payload remains byte-identical after shared-source
changes. The new image was temporarily booted through revalidated lk2nd, and
both Sending and Booting returned OKAY. The subsequent handset photograph
confirms BRK ERET OK, ESR F2004D49, FRQ 0124F800 and COUNTER OK. The controlled
EL1 exception-return path and readable advancing virtual counter are now
hardware confirmed; the reported frequency is 19.2 MHz. Photo evidence is
artifacts/hardware-proof-diagnostics-v1/mido-el1-brk-counter.png.
No timer interrupt, GIC, MMU or XNU code is exercised. See diagnostics/README.md
for boundaries, image hash and the distinction between injected emulator
exception state and real handset behavior.
