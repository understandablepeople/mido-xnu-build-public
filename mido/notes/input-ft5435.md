# FT5435 input groundwork (2026-11-04)

## Confirmed hardware and failure

Recovery binds ft5435_ts to I2C bus 3, address 0x38. It reports chip ID
0x54 and firmware 10.0.0. The physical sensor is 1080x1920 with ten slots.
Saved live DT identifies Home (500,2040), Menu (200,2040), Back (800,2040).
The actual bus driver is MSM-I2C-v2-adapter, not the sailfish v1-tag path.

The last hardware-tested kernel (0106) exposes MidoHIDTouch/MidoHIDButtons,
but has no hardware callers. Patch 0107 now adds those callers; it is NOT
hardware-verified. A registered HID service alone does not prove input works.

## Patch 0107 implementation

MidoInput runs on its own workloop, starting after ten seconds and HID
registration. It configures the verified MSM8953 QUP3 clocks/pins, verifies
FT5435 ID 0x54, and polls reports every 20 ms with bounded timeouts. Output
uses nine-byte v2 tags in FIFO mode; input uses block mode, including the
65-byte full report and tag overhead. Three failed frames release contacts;
ten stop polling, followed by at most five identity re-probes. Home is mapped
explicitly; Menu/Back remain unassigned. Hardware identities retain slots.

Read-only SPMI observer transactions read PM8953 power/volume-down and
PMI8950 SOC/charger status. Volume-up uses GPIO85. MidoBattery subclasses
IOPMPowerSource and publishes only successful hardware samples, with no
invented voltage/current/temperature. iOS power-source recognition is untested.
No charging configuration or PMIC regulator writes are performed.

Boot arguments midoinput=0, midotouch=0 and midopmic=0 disable the respective
paths. Touch inherits warm L10/L6 supplies; cold rail initialization is NOT
implemented. Failed identity probing is logged, not reported as working touch.
SMP remains cpus=1; eMMC retry and repaired on-device root remain unchanged.

Local checks: ARM64 Mach-O compilation succeeds for MidoInput, MidoHID and
KernelConfigTables. Native mocked transport/state tests cover boundaries,
partial transfers, errors, timeouts, slot reconciliation and sanitizer stress.
Patch application against the verified 0106 tree passes. Full CI 41839208377
at 95d386e passed in 6m26s. Downloaded kernel SHA256 is
8967aa380d51bb20d7eee7fe17d82b24cd83a1369df1c90af7281e5ee0944f5e.
The A53 scanner's sole raw match is the same complete SHA256 constant table
as 0106, not an instruction. A separate one-core image is packaged with the
previous shim, DTB, ADT and command line unchanged. NO hardware boot yet.

## Pure, host-tested helpers

mido/input/mido_ft5435.h is new independent code, not a copied Linux driver.
It is NOT integrated into the kernel patch series yet.

- Decode the fixed 63-byte report (three metadata bytes, ten six-byte records).
- Distinguish down/contact/up and screen/virtual-key/outside coordinates.
- Preserve hardware identities 0..14; do not confuse the ten-contact count
  with the four-bit hardware identity range. Identity 15 terminates records.
- Reject invalid mode/count/event, duplicate IDs and inconsistent active count
  without modifying the caller's frame. A valid zero-count frame releases all
  tracked contacts even if stale record bytes remain in the device report.
- Build the nine-byte QUP-v2 repeated-start register-read command. The report
  read is 81 70 82 01 00 81 71 87 3f. Length and buffer capacity are checked.
  This is an output FIFO command, not a complete MMIO transport. Receive data
  includes a two-byte tag header which the future transport must remove.

Six WSL tests pass, including 2000 deterministic contact-frame comparisons,
virtual-key boundaries, malformed reports and output-preservation checks,
command/canary checks and 100000 ASan/UBSan malformed-report iterations.

Run from Linux/WSL:

    python3 -m unittest discover -s mido/tests -p test_mido_ft5435.py -v

## Original implementation checklist (implemented above; hardware gates remain)

1. Implement bounded QUP-v2 FIFO/block transport using MSM8953 clock offsets,
   validating HW version, FIFO size and controller state before transfers.
   A full report plus two receive-tag bytes is 65 bytes: do not assume it
   fits a 64-byte FIFO. Include timeout, NACK/error and partial-transfer tests.
2. Preserve live regulator/pin configuration initially, verify device ID and
   use only normal register reads. Do not upload firmware, invoke calibration,
   or reuse sweet/sailfish rail, GPIO or clock addresses. A warm inherited
   configuration, if it works, is not proof of cold-boot rail initialization.
3. Maintain a 15-identity to ten-HID-slot mapping with explicit release on
   up, disappearance, virtual-key transition and bounded transport failure.
   Home maps to existing key 3. Menu/Back policy must be chosen explicitly;
   do not silently convert all capacitive keys into Home presses.
4. Integrate driver start after scheduler/HID availability, compile ARM64
   objects, apply the complete patch series, then full CI link. Only afterward
   temporarily boot a separately named image and collect fresh evidence.
5. Power/volume-down use PM8953 PON via read-only SPMI; battery uses PMI8950
   telemetry in MidoInput, not the pure touch helpers. Both need a hardware
   test. Never publish a recovery snapshot as live XNU charge percentage.

The optional two-core diagnostic image remains unbooted. Keep SMP testing
separate from input changes. No boot/reboot/flash is needed for these tests.
Recovery debugfs/gpio previously correlated with an external abort and reboot
into LineageOS; do not read it again. Current work uses local files only.

## Reference provenance

Saved Linux references: xiaomi-msm8953-devs/kernel_xiaomi_msm8953, immutable
commit dbe33d8d742974d65b20971bcb91dee26ea56892, particularly
ft5435_ts.c, i2c-msm-v2.c and i2c-qup.c. They define the wire formats used for
the independent helpers. Device dumps and downloaded sources remain local.
