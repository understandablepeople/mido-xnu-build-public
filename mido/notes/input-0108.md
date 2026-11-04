# 0107 hardware evidence and 0108 follow-up (2026-11-04)

The 0107 kernel reached the lock screen on the physical mido. User observed
multi-minute power/volume UI delays and a stale charging icon after unplug.
Fresh persisted log: 218570 bytes, flush 419, no ring wrap. One SpringBoard
exec, no panic(cpu or SIGABRT text. This is not proof of a responsive system.

Power and volume events were dispatched with one HID client. PM8953 observer
reads work. PMI8950 samples change from 99% USB=1 charging=1 to 98% USB=0
charging=0 and back to USB=1. Hardware disconnect detection works; iOS UI
consumption/timing is not established. Old sampling used 1500 poll cycles,
not elapsed time, and logged only percentage changes.

Touch did NOT initialize: QUP version 0x20070000, identity zero, error -7
on the initial probe and all five retries. -7 combines bus/controller errors;
the exact status was discarded before reset. It is not proof that rails are
off, nor a slow but working touch screen. Do not repeat an identical boot
expecting working touch or blindly write regulators from another platform.

Framebuffer code does not implement physical panel/backlight sleep: unhandled
selectors return success. Removing clock/date on screen does not demonstrate
panel power-off. A separate verified display power path is still required.

## Patch 0108

- Reuse horizontal source offsets in 128-column tiles (512-byte stack table),
  instead of two 64-bit divisions per output pixel per row. Mapping/clipping
  remains exact for arbitrary rectangles; no reduction in canvas resolution.
- Measure the first framebuffer copies, and log up to 20 input scheduling
  gaps over one second. These measure delays; they do not assume their cause.
- Retain QUP status/error/operational snapshots before reset, print on probe
  failures. No new recovery MMIO reads, PMIC writes or reset pulses.
- Sample battery every five elapsed seconds instead of 1500 callbacks, and
  log USB/charging/full transitions even when percentage remains unchanged.

Native randomized pixel reference and ASan/UBSan tests pass. An x86 host
benchmark of the full 1242x2208 -> 1080x1920 copy measured median 6.255 ms
before, 2.972 ms after (2.10x), with identical output. This is NOT a phone
speed measurement and does not establish the cause of multi-minute delays.
Local ARM64 compilation succeeds for MidoInput and MidoFramebuffer.
Keep cpus=1 for this comparison; SMP remains a separate untested change.
