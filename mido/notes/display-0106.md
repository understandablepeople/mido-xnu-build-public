# Mido display repair 0106 (2026-11-04)

## Confirmed failure

The post-dyld-repair device log records `MIDO FB: no boot framebuffer`,
then 62 SpringBoard SIGABRT/restart cycles. The repeated exception describes
Wireless/wireless0 with zero display bounds. The old driver requires four
bytes per panel pixel; the confirmed splash has three, B,G,R order.

## Implementation

`xnu/patches/0106-mido-bgr24-scaled-display.patch` appends to the existing
series; it does not modify the previously booted kernel or root filesystem.

- Map the real panel independently from the user-visible IOSurface.
- Advertise a 1242x2208 BGRA canvas at scale 3, matching the existing D21AP ADT
  and the iPhone 8 Plus layout. Scale the entire canvas to 1080x1920; do not
  crop an iPhone X canvas or expose BGR24 as BGRA.
- Allocate a zeroed, cached, aligned BGRA default surface and allow its swaps.
  Never let userland write four-byte pixels directly to the three-byte panel.
- Validate format, packed-pixel layout, allocation length, stride and rectangle
  bounds before copying. Support clipped/scaled rectangles and padded rows.
  Copy B,G,R only for the 24-bit panel; retain the bounded 32-bit path.
- Normalize HID coordinates against the physical 1080x1920 panel without old
  2400-pixel clamps or iPhone X offsets. This does not implement or verify the
  FT5435 hardware input driver.
- Pause text rendering only after a nonempty GUI copy. Persistent logging is
  upstream of this rendering gate and remains active; panic entry restores
  text. `midofb_noconsole=0` keeps text for diagnosis.
- Clean up mapping, buffer, timer and lock resources on service destruction.

The exact scanout implementation is also in `mido/display/mido_scanout.h`.
A consistency test compares it byte-for-byte with the new kernel header
embedded in the patch.

## Verified locally

- Seven scanout tests pass under WSL, including 1500 reproducible randomized
  reference comparisons, padded rows, invalid lengths/strides, physical touch
  coordinates, and a complete 1242x2208 to 1080x1920 frame.
- AddressSanitizer and UndefinedBehaviorSanitizer pass 10000 extreme-rectangle
  cases; output guards remain intact.
- The host harness extracts the real patched framebuffer-console and early
  console sources. Pixel/canary and GUI pause/resume tests pass.
- All five affected compilation units pass syntax checking and real ARM64
  object compilation with generated headers/flags from successful CI run
  41382749979. New function definitions and references agree, including C
  linkage for the console gate. This is not a full kernel link.
- All 74 patches, including 0106, apply in order to the baseline. HFS staging
  was reconstructed from the pinned source in the successful CI artifact,
  reversing its two later HFS modifications before replaying the series.
  The seven affected files exactly match the source used for compilation.
- The broader Windows suite has an existing unrelated SDHC expectation
  failure: it expects 0x07824900/0x500 while the current ADT uses
  0x07824000/0x1000. The display geometry assertions pass. Do not change the
  working eMMC configuration to make this stale assertion pass.

Commands from the repository root (Linux/WSL for native C tests):

    python3 -m unittest discover -s mido/tests -p test_mido_scanout.py -v
    python3 mido/tests/fb/run_fb_test.py research/display-buildtree/xnu research/display-fb-test

## Full build and temporary boot

CI 41823010516 passed the full kernel build/link on 2026-11-04. The
downloaded kernel matches its SHA256SUMS entry:
`7c4216f42693965edb643f0da409effa43cd62b8ba7a02bd8c8ad6ae3f62665d`.
The Cortex-A53 scanner has one raw match in SHA-256 constant K256[57],
not an instruction; all 64 table words were checked against the source.
The BearSSL host outage was bypassed with a same-pin mirror fallback.

A separate image preserves the verified build15 shim, ADT and cmdline,
replacing only the kernel. It was temporarily booted through verified
lk2nd; both fastboot boot commands completed successfully, with no flash.
This proves bootloader acceptance ONLY. A fresh device log and screen
observation are still required before claiming that the SpringBoard loop
is fixed. Touch hardware, GPU and other services remain unverified.
Preserve build15 and all root backups.
Do not flash the old host root/sparse image: it still has the dyld corruption
that was repaired only on the phone.
