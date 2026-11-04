# Framebuffer follow-ups (24bpp BGR, 0x90001000, 1080x1920, stride 3240)

2026-11-04: appended patch 0106 addresses the display/BGRA-to-BGR24 path and
HID geometry described below. Host tests, clean-series application and five
ARM64 compilation units pass; no new kernel has been linked or booted yet.
See display-0106.md. The original findings below are historical; do not
reimplement them as if patch 0106 did not exist.

Written while adapting xnu patches 0003, 0010, 0012. Nothing below was edited; these are for the owners of the files.

## Single source of constants
`osfmk/arm64/mido_fb.h` (created by patch 0003) holds PHYS, WIDTH/HEIGHT/STRIDE/BPP/SIZE, the 3-block
geometry (`MIDO_FB_BLOCK_PA` 0x90000000, `MIDO_FB_BLOCK_OFFSET` 0x1000, `MIDO_FB_BLOCKS` 3), text colours and
`MIDO_BOOTSTRAP_PAGES`. Include it from asm and C. At run time fbcon prefers `PE_state.video`
(boot_args.Video: base 0x90001000, rowBytes 3240, 1080x1920, depth 24) and only falls back to the
`mido-fbcon` ADT node (reg/width/height/stride; `depth` must be absent or 24).

## Still assuming 32bpp / the old address
1. `xnu/patches/0046-mido-iosurface-iomfb.patch` (MidoFramebuffer.cpp, MidoSurface.cpp): `bytesPerElement = 4`,
   `fRowBytes < fWidth * 4` rejects the 3240 stride (AppleCLCD::start fails: "no boot framebuffer"),
   `MIDO_FB_FORMAT_BGRA` (0x42475241) advertised, blit `memcpy` uses `dx * 4` and `w * 4`, comments say 1080x2400 a8r8g8b8.
   Needs a 24bpp path: pixel format 'BGR3'-style (or convert BGRA surfaces to 3 bytes on flip, which is slow),
   `bytesPerElement = 3`, blit math `* 3`. Userland CoreAnimation renders BGRA, so expect a conversion blit
   (4 -> 3 bytes per pixel) in the flip path. `mido_surface_create_physical` also maps the splash with
   `IOMemoryDescriptor::withPhysicalAddress(0x90001000, round_page(3240*1920))`; page aligned, fine on 4K.
2. `xnu/patches/0061-mido-iphone-x-display-size.patch`: hardcodes panel 1080x2400 (`fLogicalH = 2400`, `fOffY = (fLogicalH - 2400)/2`,
   `(fLogicalW - 1080)/2`); the panel is 1080x1920 now. Also 1125x2436 "iPhone X" logical size no longer fits
   vertically (needs a new logical size / scaling decision).
3. `xnu/patches/0058-mido-hid-event-services.patch` line ~21047: touch normalisation `/ 1080`, `/ 2400`; the FT5435 panel is 1080x1920.
4. `xnu/patches/0046` `MIDO_FB_DOT_PITCH 395` (ppi of the 6.67 in Redmi panel); Note 4X is 5.5 in, about 401 ppi. Check what userland derives from it.
5. `osfmk/console/video_console.c` (stock) only paints depths 8/16/30/32. If boot_args.Video.v_display is non-zero,
   `PE_initialize_console(kPEGraphicsMode)` would draw 32bpp into the 24bpp buffer. Loader must leave `Video.v_display = 0`
   (fbcon via the serial path is the console), or add 24bpp to video_console.c.
6. Outside the xnu patches: `tools/mkadt.py` (old sweet: `FB = 0x9c000000`, node `sweet-fbcon`), `shim/console.h`
   (`FB_BASE 0x9c000000`), `shim/mmu.h`, `tools/qemu-sweet.py`, `docs/QEMU_TESTING.md`, `NOTES.md`. `tools/mkadt_mido.py`
   and `mido/shim/README.md` are already mido-ified (README line 80 says 0003 still assumes 32bpp; that is now fixed).
   QEMU testing has no 0x90001000 framebuffer RAM; add it (or skip fbcon) when reviving the QEMU path.

## Loader / boot facts the three patches rely on
- RAM V=P window must end at or below 0x80000000 (phys_base 0x20000000, mem_size <= 0x60000000). The fb lives
  in L1 slot 2 (0x80000000..0xBFFFFFFF) of the TTBR0 bootstrap table; start.s gets a fresh L2 page for it, or reuses
  an existing one if the RAM window already reaches slot 2 (then fb blocks overwrite only RAM V=P aliases of the splash).
- `BOOTSTRAP_TABLE_SIZE` (osfmk/arm/pmap/pmap.h) went 8 -> 10 pages (`MIDO_BOOTSTRAP_PAGES`). Worst case use is
  2 L1 + 2..3 V=P L2 + 2..3 KVA L2 + 1 fb L2 = up to 9; start.s hangs (stage-0 white band still on screen) rather than
  run past the table. `arm_vm_init` DEBUG sanity check `pages_used` formula does not know about the extra page (10 gives slack).
  `monitor_start/end_pa` in pmap.c use the same constant (only with XNU_MONITOR).
- KVA alias (0012): 3 L2 slots at `MIDO_EARLY_FB_VA = VM_MIN_KERNEL_ADDRESS + 2MiB` (low globals own slot 0), i.e.
  [VM_MIN+2MiB, VM_MIN+8MiB). With ARM_LARGE_MEMORY (the MIDO config) `VM_KERNEL_LINK_ADDRESS` is 0xfffffe0007004000
  = VM_MIN + 7MiB + 16KiB, so the old single block fit but the 3 blocks overlap the kernel image. `mido_early_map_final`
  now panics (shown by the early console) if `gVirtBase < VM_MIN + 8MiB`. **Action for the 0004/makedefs owner: set
  `ARM64_LINK_ADDR` (makedefs/MakeInc.def) and the loader's virtBase to at least 0xfffffe0008004000, e.g.
  0xfffffe0010004000, or move `MIDO_EARLY_FB_VA`.** Not hit by the old 16K/32MB design. If ARM_LARGE_MEMORY is off, the
  gap is huge, but the L1 slot may be empty; the code allocates its L2 table with `alloc_ptpage(TRUE)` like low globals.
  Whether the VM allocator treats that VA range as reserved was inherited from sweet and is unverified.
- Scrolling: neither console scrolls (reads from non-cacheable memory are slow); both wrap and keep a blank line after the
  cursor. The early console (0010/0012) intentionally stays minimal for panic safety. If scrolling is wanted later, copy
  `fbcon_stride` bytes per scanline with a byte loop and amortise over several text rows.
- Early stage marker (start.s stage 0): white 64x32 band, 3 byte stores per pixel, at the bottom-left (row 1888). Progress
  bars in `mido_early_mark` are green with varying red (B,G,R = 00,ff,r).
