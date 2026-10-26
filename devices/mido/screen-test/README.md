# Minimal ARM64 screen experiment

This is a first bring-up payload, not XNU, an iOS ROM, a Linux kernel or an
installer. The corrected v2 build has passed host emulation and was submitted
to lk2nd with temporary fastboot boot. Both transfer and Booting returned OKAY.
A user photograph now confirms the expected output on the handset at EL1.
Only this minimal payload is hardware tested; there is no XNU or iOS result.

Build from normal Windows PowerShell:

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build-arm64-screen.ps1

The script builds host files only and stops before any phone command. Output
defaults to artifacts/arm64-screen-build-v2; an existing directory is refused.
Use a new workspace artifacts subdirectory with -OutputDirectory for retries.
Do not boot the result until its manifest, ELF and disassembly are reviewed.

## Loading contract

The intended loader is the already tested temporary lk2nd-msm8953 23.1 at
e9c8b21735c13dd7ace808b1e35451638f0a0c6d, not stock fastboot. Source references:

- app/aboot/aboot.c: cmd_boot, update_ker_tags_rdisk_addr, boot_linux.
- platform/msm_shared/scm.c: scm_elexec_call passes DTB in x0 to ARM64.
- platform/msm_shared/include/dev_tree.h: DTB_OFFSET is 0x2c.
- platform/msm_shared/dev_tree.c: appended DTB and device-tree update handlers.
- lk2nd/display/simplefb.c: lk2nd.pass-simplefb exports the active screen via
  a /chosen/simple-framebuffer node referencing reserved-memory by phandle.
- lk2nd/display/cont-splash/pipe.c: framebuffer geometry and native 24bpp mode.

The ARM64 Image header has text_offset 0x80000 and a legacy Qualcomm appended
DTB offset at 0x2c. Code and read-only data use PC-relative addressing; there
are no persistent pointer tables. Entry, vectors and stack move together at
a page-aligned load address. Link base zero is not the physical destination.
Review the final ELF for absolute addresses, relocations and unexpected GOT
before use. There is no ramdisk, storage driver, secondary CPU code or XNU.

The packer pins the original extracted recovery DTB hash, reads its msm/board
IDs and creates a minimal diagnostic tree. It does not reuse the vendor tree,
claim a full hardware description or fabricate an active framebuffer. The
loader must populate memory and export its current framebuffer. No conversion,
relocation or forced display refresh is requested. The downstream /soc/qcom,ion
heuristic is absent so the simplefb handler is eligible to run.

## Payload limits

Entry accepts EL1/EL2 with MMU and data cache disabled; otherwise it halts.
The C build uses -mstrict-align because FDT properties are only four-byte
aligned and wide loads can fault before an MMU/memory-attribute setup exists.
The first user build lacked that flag and is superseded; do not boot v1.
Interrupts are masked and exception vectors halt. The payload does not enable
MMU/cache, change exception level, program GIC, touch storage or issue SMC.
It uses a bounded parser for the incoming FDT, an exact diagnostic root marker,
and accepts only a loader-exported 1080x1920 r8g8b8 buffer, stride 3240,
physical base 0x90001000 and matching reserved-memory region. Missing or
different parameters cause a silent halt without framebuffer writes.

On acceptance, only the first 720 screen rows are overwritten, with grayscale
text and a checker strip. Expected text is MIDO ARM64, EL1 or EL2, DTB OK,
RAM ONLY, NOT IOS. Grayscale does not depend on RGB/BGR channel order. The
bottom of the lk2nd screen may remain visible. No animation or USB service is
implemented. Power-button forced restart is needed after a successful halt.

Even this experiment may hang, leave a stale or black screen, or reset through
a firmware watchdog. A fastboot OKAY is not evidence of payload execution.
No partitions should be flashed, erased, formatted or relocked for this test.

## Reviewed v2 build and synthetic execution

The original v1 binary compiled a byte-based read_be64 into an unaligned LDR.
The corrected build uses -mstrict-align; its disassembly uses byte loads for
this function. The ELF has no relocations, unresolved symbols, GOT or BSS.
The payload is 25968 bytes. Packaged image SHA-256:
8be499be41bff90f845596872ea902ca30c3a624009e092fb36eb274cc3d2e1f.

tools/emulate_screen_test.py runs the exact machine code with Unicorn 2.1.4,
installed locally under artifacts/python-deps, and a synthetic loader DTB.
Reproduce using a new report prefix to preserve earlier outputs:

    python tools/emulate_screen_test.py artifacts/arm64-screen-build-v2 --report-prefix another-review

Thirteen scenarios pass, including EL1, relocated EL2, valid properties aligned
to four rather than eight bytes, invalid geometry/format/address/reference and
enabled data cache. Memory hooks reject unaligned data accesses and stores
outside the stack or first 720 framebuffer rows. Invalid cases perform no
framebuffer stores. A rendered preview was inspected. The original v1 fails
an unaligned-access check; it must not be used. The ordinary 39 regression
tests also pass. Emulation does not validate Qualcomm firmware or display DMA.

The pre-boot lk2nd log is artifacts/lk2nd-before-screen-v2.log. Empty responses
to version-bootloader and lk2nd:device were not treated as identity evidence;
the exported log confirms mido. The image hash was checked immediately before
temporary boot. On 2026-10-25, fastboot reported Sending OKAY and Booting OKAY.
No flash command was executed. The user's subsequent photograph shows MIDO
ARM64, EL1, DTB OK, RAM ONLY, NOT IOS and the expected checker strip. The
unchanged lower lk2nd text is retained framebuffer content, not evidence that
lk2nd's menu or USB service is still running. The payload halts by design.
Photo: artifacts/hardware-proof-screen-v2/mido-arm64-el1.png, SHA-256
f72c0a971c01dead97b5c145caaf907b8cd423038cd6fa744b365d877bfd7cfc.
This confirms the standalone AArch64 execution and narrow validated drawing
path. It does not test interrupts, timers, exceptions, a general display
driver, storage, touch, USB, secondary CPUs or any XNU component.
