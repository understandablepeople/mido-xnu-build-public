# mido XNU shim (lk2nd RAM image)

Turns a mido XNU kernel Mach-O into a bootable lk2nd RAM image, mirroring ios-sweet.
**Nothing here has run on the phone.** All verification is host-side (Unicorn).

## Pieces

| File | Role |
|---|---|
| `mido/shim/entry.S` | m1's hardware-validated entry: exact 64-byte arm64 Image header (text_offset 0x80000, image_size, Qualcomm appended-DTB offset at 0x2c), EL1/EL2 detect, halts if MMU/D-cache is on, vectors that draw ESR/ELR/FAR. |
| `mido/shim/shim.c` | 24bpp B,G,R console (m1) + loader derived from sweet `shim/loader.c`: locate payload, validate, copy, build ADT + boot_args, jump. |
| `mido/shim/fb_dtb.inc` | m1's strict simple-framebuffer check (needs lk2nd's simplefb node at 0x90001000, 1080x1920, stride 3240). No valid node = shim draws nothing and returns, like m1. |
| `mido/shim/link.ld`, `font.h` | m1's linker script (no .bss, no relocations, 16 KiB stack inside the image) and font. |
| `mido/shim/build.py` | NDK clang + ld.lld build, rejects relocations, optional packaging, prints sha256. Refuses to overwrite. |
| `tools/mkpayload.py` | Mach-O + ADT -> `SWEETXNU` payload. Now 4K: `PAGE=0x1000`, `virt_base` = 2 MiB-aligned, asserts `dram-base` 2 MiB aligned. Chained-fixup handling unchanged. |
| `tools/mkadt_mido.py` | Apple Device Tree for mido (iPhone 8 Plus identity D21AP, 8x A53, GICv2, `mido-fbcon`, `pram`, optional `mido-sdhc`). |
| `tools/pack_mido_boot.py` | lk2nd boot image v0: kernel = shim + appended DTB, ramdisk = payload. |
| `tools/lzfse.py`, `tools/adt.py`, `tools/extract_d21ap.py` | Pure-python LZFSE + IM4P unwrap; extracts the real D21AP DeviceTree from an IPSW (`/product` node). |
| `mido/tests/` | `test_mido_shim.py`, `fixtures.py` (synthetic Mach-O + DTBs). |

## Boot image layout (page size 2048, header v0)

| Item | Address | Content |
|---|---|---|
| kernel | 0x10080000 | shim Image + appended DTB (`qcom,msm-id` 293, `qcom,board-id` 11) |
| tags | 0x13400000 | DTB copy, lk2nd rewrites /chosen |
| ramdisk | 0x13600000 | SWEETXNU payload |
| XNU arena | `phys_base` 0x20000000, `mem_size` 0x40000000 (args) | kernel segments at `phys_base + (vmaddr - virt_base)`, then ADT, then boot_args page |

cmdline is the validated `lk2nd.pass-simplefb=keep` (first word renamed `mido-xnu-shim`; lk2nd ignores it, but this word is the one change versus the validated screen test).

## How the shim finds the payload (verified in lk2nd source)

lk2nd 23.1 `platform/msm_shared/dev_tree.c: update_device_tree()` does, for any boot with ramdisk_size != 0
(it is not conditional on arm64): `fdt_setprop_u32(/chosen, "linux,initrd-start", ramdisk)` and
`"linux,initrd-end"` (u32, ramdisk + size). `boot_linux()` reaches it unless `BOOT_ATAGS_COPY` is set; ATAGS copy
is only chosen for 32-bit kernels. The shim accepts 4- or 8-byte props. If the props are absent (or the DTB fails
sanity checks) it falls back to the header's fixed ramdisk address 0x13600000 and says so on screen. Not verified:
that the release binary behaves like the pinned source on the phone (the source audit only pins e9c8b217).

## Loader behaviour

Console lines are printed before each risky step: INITRD, PAYLOAD, PHYS/VIRT/ENTRY, CHECKS, COPY (one line per
segment before it is copied), COPY ADT, BOOTARG, JUMP. A red background plus `FAIL: reason` means a refused
payload; a red `EXCEPTION` shows ESR/ELR/FAR. Checks: magic/version/nsegs, every file range inside the payload
(and inside initrd-end when known), phys_base/virt_base 2 MiB aligned, arena inside 0x10000000..0x80000000,
segments and entry inside the image, ADT + boot_args inside the arena, and no overlap of the arena with the shim,
DTB or payload. It also refuses to jump unless entered at EL1, reads back the first 16 bytes of each copied segment,
then `dsb; ic iallu; dsb; isb` and jumps to the entry PA with x0 = boot_args PA. boot_args: Revision/Version 2,
Video base 0x90001000, rowBytes 3240, 1080x1920, depth 24, `deviceTreeP` = ADT virtual address (as sweet).

## Build and run (host only)

```
python -I tools/mkadt_mido.py out/k.adt [--phys-base 0x20000000] [--mem-size 0x40000000] [--sdhc]
python -I tools/mkpayload.py KERNEL.macho out/k.adt out/payload.bin --cmdline "debug=0x14e serial=3"
python -I mido/shim/build.py out/build --payload out/payload.bin [--reference-dtb dtb-00.dtb]
#  -> out/build/shim.bin, shim.elf, package/mido-xnu-shim.img (+ manifest.json), sha256s printed
python -I tools/extract_d21ap.py IPSW research/ipsw      # one-time: real D21AP /product node
python -I -m unittest discover -s mido/tests -v          # tests (needs the NDK; Unicorn from ios/artifacts/python-deps)
MIDO_SIM_PNG=some_dir  # also writes the simulated console screenshot shim-sim.png
```
Flashing/booting is deliberately not scripted: `fastboot boot` of the image is the user's call.

## Verified

- shim builds with NDK clang 28.2 (`-Werror`), no relocations, no .bss, header equal to m1's layout.
- Unicorn: initrd props (u32 and u64) and fixed-address fallback paths copy segments to the right PAs, zero the
  bss tail, place the ADT and boot_args with correct fields, and jump with x0 = boot_args; bad payloads are refused
  without copying or jumping; invalid framebuffer DTB draws nothing.
- ADT round-trips through `tools/adt.py`; IM4P + LZFSE decode of the real D21AP tree works (185432 bytes, `/product`
  `iPhone 8 Plus`).

## NOT verified

- Anything on the phone: lk2nd release behaviour, DDR at 0x20000000+ accepting writes, speed of Device-memory copy
  (~tens of MB at 8 bytes/store), the real XNU entry conventions (4K start.s), cache state at the jump.
- Unicorn does not model MMU/cache/Device-memory semantics, only the logic.
- Panic-log `pram` is 1 MiB just above `dram-size`; `mkpayload` takes the already-reduced dram-size from the ADT.
- `mido-fbcon` `depth` property and 24bpp are not yet consumed by the kernel patches (0003 still assumes 32bpp).
- `mido-sdhc` `compatible` string is a guess; only `reg` is from the DTB.
