# mido (Redmi Note 4X, MSM8953) hardware facts

Source tags: [HW] measured on the phone by our own probe, [DTB] saved live recovery
DTB (artifacts/live-recovery/live.dtb in the old repo), [LK] lk2nd 23.1 log.
Anything not tagged is an assumption.

## CPU / boot [HW]
- 8x Cortex-A53 r0p4 (MIDR 0x410FD034), entered at EL1, MMU/D-cache off, SCTLR_EL1 0x00C00800.
- ID_AA64MMFR0 0x1122: TGran16 = 0 -> **no 16K pages**, 4K only. PARange 2 (40-bit). MMFR1 = 0: no PAN/LSE/VHE.
- ISAR0 0x11120: AES, SHA1, SHA2, CRC32 present; no atomics (LSE).
- CNTFRQ 19.2 MHz. CTR 0x84448004: 64-byte lines (DminLine 4 = 64B, IminLine 4).
- MPIDR boot CPU 0x80000000 (cluster 0, core 0). [DTB] cpus: 0x000-0x003 and 0x100-0x103, PSCI 1.0 over SMC.
- PSCI [HW]: VERSION 1.0, CPU_ON (64-bit) supported, SYSTEM_RESET **not** advertised (FEATURES = -1).
- lk2nd 23.1 loads boot v0 images: payload at 0x10080000, DTB at 0x13400000, ramdisk 0x13600000
  (header values we set; see tools/pack_screen_test.py).

## Memory [HW]/[DTB]
- RAM banks 0x10000000+0x70000000 and 0x80000000+0x80000000 (3.75 GiB total).
- Reserved (no-map etc): 0x84a00000-0x86800000, 0x86c00000-0x8d600000, 0x8d600000-0x8e700000,
  0x8e700000-0x8ee00000, splash 0x90001000+0x5EEC00, pstore 0x9ff00000-0xa0000000;
  dynamic pools were placed by Linux in 0x8f000000.., 0xf1800000-0xff000000+ (not authoritative).
- **Free low RAM for the first XNU arena: 0x10000000-0x80000000 (1.75 GiB), untouched by any reservation.**

## Display [HW]/[LK]
- Continuous splash at 0x90001000, 1080x1920, stride 3240, 3 bytes/pixel,
  **byte order in memory is B,G,R** (byte0 = blue). Photo-verified 2026-11-01.

## Interrupts [HW]/[DTB]
- GICv2 qcom,msm-qgic2: GICD 0x0b000000, GICC 0x0b002000. GICD_TYPER 0x4EA (8 CPUs, 160 lines),
  GICD_IIDR 0x1070, GICC_IIDR 0x20070, lk2nd leaves CTLR=1 on both, GICC_PMR 0xF0.
- arch timer PPIs (type 1): sec-phys 2, phys 3, virt 4, hyp 1 -> INTIDs 18, 19, **20 (virtual)**, 17.
  clock-frequency 0x124f800.

## Storage [DTB]/[LK]
- eMMC (HS400 per lk2nd, 62537072640 bytes) = sdhci@7824900: hc_mem 0x07824900+0x500,
  core_mem 0x07824000+0x800, cmdq 0x07824e00+0x200, tlmm_mem 0x0119d000; IRQ SPI 123 (hc), 138 (pwr).
- SD card slot = sdhci@7864900.

## Input [DTB]
- Touch: FocalTech FT5435, I2C addr 0x38 on i2c@78b7000 (BLSP1 QUP3, SPI-IRQ 97), pins GPIO10/11 (function blsp_i2c3),
  reset GPIO64, IRQ GPIO65 (level, falling), panel coords 1080x1920, up to 10 touches,
  vdd supply phandle 0x115 (PM8953 LDO, to be resolved), vcc_i2c phandle 0xbb.
- Capacitive keys are reported as touch virtual keys at y=2040 (below the screen): key 172 HOMEPAGE x=500,
  key 139 MENU x=200, key 158 BACK x=800 (half-size boxes 0x78x... see DTB focal,virtual_key_N: code, x, y).
- Volume up GPIO85 (active low, pull-up). GPIO86/87 configured as keys too (usage unknown).
- Power key / volume down: PM8953 PON via SPMI arbiter @0x0200f000 (core 0x0200f000, chnls 0x02400000,
  obsrvr 0x02c00000, intr 0x03800000, cnfg 0x0200a000).
- TLMM base 0x01000000, 4 KiB per GPIO (CFG at +0, IN_OUT at +4).

## Other
- Recovery verification (2026-11-04): bound `ft5435_ts` on i2c-3/0x38,
  device ID 0x54, firmware 10.0.0, 10 slots, 1080x1920. [HW]
- Touch supplies from the live recovery DT: pm8953_l10 at 2.85 V (vdd),
  pm8953_l6 at 1.8 V (vcc_i2c). [DTB]
- Recovery battery/bms both reported 95%, charging over USB, 4.353459 V
  and 31.2 C. These are a recovery-time snapshot, not live XNU telemetry. [HW]
- RPM-SMD regulators present (PM8953 ldoa*/smpa*); WCNSS (Wi-Fi) is not part of milestone 1.
- GPU Adreno 506: no iOS driver anywhere; first GUI renders in software (as ios-sweet).
