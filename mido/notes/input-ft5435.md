# FT5435 input groundwork (2026-11-04)

## Confirmed hardware and failure

Recovery binds ft5435_ts to I2C bus 3, address 0x38. It reports chip ID
0x54 and firmware 10.0.0. The physical sensor is 1080x1920 with ten slots.
Saved live DT identifies Home (500,2040), Menu (200,2040), Back (800,2040).
The actual bus driver is MSM-I2C-v2-adapter, not the sailfish v1-tag path.

The current XNU exposes MidoHIDTouch/MidoHIDButtons, but has no hardware
callers of mido_hid_touch/mido_hid_key. A registered HID service alone
therefore does not prove that physical input can reach iOS.

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

## Remaining implementation gates

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
5. Power/volume-down require PM8953 PON via read-only SPMI; battery requires
   PMI8950 fuel-gauge telemetry. Neither is implemented by these touch helpers.
   Never publish a recovery snapshot as live XNU charge percentage.

The optional two-core diagnostic image remains unbooted. Keep SMP testing
separate from input changes. No boot/reboot/flash is needed for these tests.
Recovery debugfs/gpio previously correlated with an external abort and reboot
into LineageOS; do not read it again. Current work uses local files only.

## Reference provenance

Saved Linux references: xiaomi-msm8953-devs/kernel_xiaomi_msm8953, immutable
commit dbe33d8d742974d65b20971bcb91dee26ea56892, particularly
ft5435_ts.c, i2c-msm-v2.c and i2c-qup.c. They define the wire formats used for
the independent helpers. Device dumps and downloaded sources remain local.
