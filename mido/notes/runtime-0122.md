# 0122 runtime: app launch stall and CX readback

## Verified on 2026-11-06

The phone was in TWRP. All device access in this investigation was read-only:
ADB identity/state, the persisted kernel log, and targeted HFSX sector reads.
No reboot, partition write, firmware load, GPIO/debugfs or MMIO probe occurred.

The 0122 kernel log contains an exec of Preferences at uptime 748932 ms.
The matching launchd log successfully spawned Preferences PID 257 at
16:12:28.933 (device clock is not real calendar time), followed by requests
from that process. No exit of Preferences, SpringBoard PID 26 or
runningboardd PID 25 appears in the examined launchd interval. This proves
process launch, NOT that an app window was displayed or remained responsive.
SpringBoard logged an unbalanced SBSwitcherViewController appearance
transition nearby. That warning is a clue, not an established root cause.
The Preferences watchdog report with PID 1026 belongs to an older boot:
its systemwide stackshot has SpringBoard PID 987, unlike current PID 26.
Do not use it as evidence of a new 0122 watchdog termination.

## Additional concrete load source

Read the last Persist trace, latest available Special trace and two
Signpost traces using a local HFSX catalog reader. Extracted 426 uuidtext
files (140669347 bytes) locally, not a whole userdata image. Decoded using
Mandiant macos-UnifiedLogs release v0.7.0, Windows release SHA256 verified
against its published sidecar. All original files and decoded reports are
private, untracked logs; nothing from the device was uploaded.

For boot UUID 2093E9BD230C4896A0F716089B68D2F3, deduplicating overlap
between Persist and Special by PID/thread/time/message yields 238303
records over parser times 548.806524030..559.674014563 seconds. Of these,
200544 records come from vmd PID 224. The single Persist file alone covers
554.377397033..559.674014563 seconds and contains those 200544 vmd records.
Repeated errors are invalid XPC connection and NSCocoaErrorDomain 4099
while requesting telephony contexts/subscriptions. launchd separately
reports missing CommCenter services. No sampled CPU utilization is
available, so log volume must NOT be called a measured CPU percentage
or proof that this causes the later app/switcher stall.
The decoded persisted intervals stop before Preferences was launched.
They do not establish the precise failed app transition after 748 seconds.

Confirmed launchd definition: System/Library/LaunchDaemons/
com.apple.voicemail.vmd.plist, label com.apple.voicemail.vmd, executable
System/Library/PrivateFrameworks/VisualVoicemail.framework/vmd.
A narrowly scoped, reversible disable experiment is justified to test
this background loop, but needs explicit confirmation before rootfs
modification and a fresh boot/UI comparison. No such disable performed.

## GPU correction staged as 0123

0122 hardware CX readback was a0222800 after requesting 00222800 from
00222801. Bit 31 indicates POWER_ON, but the old comparison rejected
additional bit 29. Use mask 00fff007 for known writable fields: software
collapse, hardware control, software override, and three 4-bit wait fields
(bits 12..23), as defined in the pinned Android gdsc.c reference. Check
POWER_ON independently. Unexpected changes in any checked control field
still fail; status alone without POWER_ON still times out.
Host tests include the hardware-shaped a0222800 readback, delayed readiness,
status-only timeout and mismatches in control/wait fields. Exactly one CX
write remains permitted. No new GX, clock, memory, GPU or radio operations.
CX power is NOT GPU acceleration. WCNSS_CTRL is still absent in 0122;
Wi-Fi remote firmware/SMD startup remains unfinished. Working CC is unchanged.

## Validation and next action

Local preflight logs/preflight-20261106T164227Z: 75 tests pass (one NDK
skip), four ARM64 objects pass, GPU/WCNSS firmware checks pass. Repository
integrity still fails for the previously documented historical patch gaps
and CRLF shell scripts; no unrelated cleanup performed. No new CI/full
link/image/hardware test for 0123. Do not spend a reboot merely to relabel
CX success while app-launch diagnosis remains unresolved.

Private logs/0122-hfs-reader-snapshot.cjs preserves the in-memory reader.
It is a forensic snapshot for this exact volume/catalog, NOT a general
recovery tool: hardcoded extents, no overflow support, zero-size files need
special handling. Revalidate device and volume before any future reuse.

## Authorized vmd-only comparison boot

User explicitly approved the reversible experiment. On 2026-11-06, verified
one mido TWRP device and userdata unmounted by major:minor. Revalidated
HFSX volume, catalog extents and exact original plist bytes. The vmd file
is CNID172074, data extent634134, logical size3067 bytes, one4096-byte block.
Saved original block/file, neighbor blocks, catalog record, volume and journal
headers privately under logs/vmd-disable-20261106. Scanned17 pending journal
transactions/279 destination blocks, checked their header checksums and
lengths; no pending replay writes overlap the target data block. The journal
was not replayed, cleared or modified. Launchd disabled.plist has no override
for com.apple.voicemail.vmd.

The sole semantic plist change is Disabled=true. XML was serialized with
indentation reduced and trailing whitespace to preserve exact3067-byte
logical size; original allocation/catalog/permissions unchanged. Wrote
exactly one4096-byte block with fsync. Readback matched the replacement;
both neighbor blocks, volume header and journal header remained identical.
Parsed readback equals original dictionary plus Disabled=true.
Original block SHA256 c3f8a821248c5ddd2ae9d29429465cbe9eb23c9d1cdbfc598a3595bd923962c6.
Disabled block SHA256 02c5074bb8f8d27158a34bc5e7f8d52b8e53f8183c89ad4bbf1eb215069592a2.

For a single-variable comparison, reused the exact0122 image, not0123.
Known lk2nd checksum and image checksum verified, recovery->stockfastboot
productmido->knownlk2ndRAMboot->productlk2nd-msm8953->0122RAMboot all accepted.
No flash, other partition writes, new kernel build or GPU/Wi-Fi changes.
Private temp-boot.json records both boot commands exit0/OKAY. Bootloader
acceptance is not proof of iOS boot or that launchd honored Disabled.

Await physical test: Settings/Safari/SMS, repeat after3-5 minutes, double
Home, CC, touch and sleep. Then return TWRP to verify no vmd process/
telephony XPC storm and correlate app/scene behavior in new logs. Retain
the backup for rollback; revalidate current mapping and pending journal
before restoring, never blindly reuse a raw offset after filesystem changes.
