# Post-Claude hardware evidence and 0111 (2026-11-05)

Fresh recovery read: logs/after-claude-0110-20261105.txt, 307972 bytes,
flush 270, no wrap. Read with mido-log-pull.py; no recovery MMIO/debugfs
access, reboot, partition writes or flash commands.

The 0110 log confirms 8/8 CPUs initialized and SGI1 verified. Preserve
cpus=8: old instructions to keep cpus=1 are historical, not current.
RPM L6/L10 votes report success, FT5435 chip ID 0x54 and firmware 10 read
successfully. Touch coordinates do reach MidoHIDTouch intermittently, but
many frames fail decoding despite read=0 and eventually stop polling.
The present log lacks raw failed frames, so their exact cause is unproven.
Do not claim touch is fixed or blindly relax the decoder validation.

0110 WLED off writes zero brightness and toggles sink sync; it does not
disable the WLED module. User observes minimum brightness, not darkness.
Saved live DT identifies PMI8950 SID3 ctrl d800 and sink d900, strings 0,1.
Saved pinned Linux leds-qpnp-wled.c uses ctrl+0x46 BIT7 to disable the module
when brightness is zero, separately from sink brightness and sync.

0111 preserves the existing brightness save/restore path and adds a masked
read-modify-write of control PPID 0x3d8 register 0x46, preserving all other
bits. It verifies readback before marking the request successful. This is
backlight-module shutdown, NOT full DSI panel sleep or SoC suspend. Physical
darkness and wake restoration still require the next hardware test. No
direct PMIC access from recovery is used.

For touch, 0111 logs the first twelve rejected 63-byte reports and QUP status
before contact release. Transport/decoder policy is unchanged pending that
evidence. Keep working RPM votes and the 0110 block-read workaround.

Local current-driver ARM64 compile passes. 24 native tests pass; the NDK
module is skipped. Tests include patch-source equality and sanitizer stress.
Hardware results and CI/package identifiers must be recorded separately.
