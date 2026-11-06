# 0111 hardware result and 0112 touch compatibility (2026-11-06)

User reports real backlight darkness/wake now works, briefly reached the
Home screen, then touch stopped after selecting an icon. Fresh TWRP log
has 311898 bytes, flush331, no wrap. It records exec MobileSafari, eight
CPUs, HID touch coordinates, and WLED control readback 0x00/0x80 matching
off/on. This establishes progress, not reliable touch or full DSI sleep.

All twelve saved rejected frames have register-zero byte 0xff. Eleven
have coherent metadata ff 00 01 or ff 00 00, sentinel-terminated contacts
and matching active count. The existing mode-bit check rejects them before
contact parsing. One frame begins ff ff ff and is genuinely inconsistent.
After ten consecutive failures the driver stops polling, matching the
reported loss. Whether byte0 originates in firmware or transfer handling
is not established; this patch is bounded compatibility, not a claim of
fully verified transport. Linux ft5435_ts.c does not validate mode byte0.

0112 permits the observed byte0=ff ONLY with gesture byte0 and zero upper
count bits; count/identity/event validation remains. Factory mode 0x40
and all-ff frames remain rejected, output is unchanged on invalid frames.
Replaying the twelve saved frames accepts eleven, rejects the all-ff
metadata frame. No touch coordinates are invented. Device dumps stay local.

The QUP loop previously read a complete block on a block/service indication
without verifying FIFO nonempty per word. Add bounded FIFO-ready waits;
timeout returns -9 without exposing partial output. A stale block-request
mock now tests this. This is defensive hardening; it is not proven as the
source of the observed ff bytes.

24 native tests pass (NDK module skipped), including sanitizers and exact
patch-source comparison. Current ARM64 driver compiles. Preserve eight
cores, working WLED module switching, RPM rails and 0110 QUP workaround.

First sixteen framebuffer copies measured about 29.5-32.1 ms on hardware.
This is real copy cost, not end-to-end UI latency; lack of GPU alone is not
proof of the cause of every long UI stall. Need separate profiling.
No reboot/flash/MMIO/debugfs access in recovery during this diagnosis.
