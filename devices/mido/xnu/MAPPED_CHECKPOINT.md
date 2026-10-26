# Opt-in mapped framebuffer checkpoint

This is a diagnostic marker, not a console or permission to boot XNU.
Enable only with --experimental-mapped-checkpoint and the explicit bootstrap
crypto build. The manual bootstrap workflow exposes approve_mapped_checkpoint,
defaulting to false. Ordinary builds remain unchanged.

The isolated runtime registers at EARLY_BOOT/MIDDLE: after VM initialization,
not immediately after MMU enable. It uses native ml_io_map (VM_WIMG_IO),
never the physical framebuffer address as a post-MMU pointer.

An explicit /chosen property mido,diagnostic-framebuffer is required.
Its exact 56-byte payload is seven little-endian uint64 values:
version=1, physical=0x90001000, size=6220800, width=1080, height=1920,
stride=3240, depth=24. A missing property disables the marker. A malformed
property or failed mapping halts with a diagnostic panic before drawing.
No producer currently injects this property into the packaged image.
Adding it is a separate reviewed change, not discovery of framebuffer ownership.

The marker is a white 64x16 RGB888 rectangle at column 60, row 608.
It performs bounded aligned 32-bit device writes followed by dsb sy.
The mapping remains for the lifetime of this single-use boot diagnostic.

Local tests compile the core to ARM64 Mach-O and ELF and emulate its actual
instructions. They check all seven contract fields, null inputs/callbacks,
failed/unaligned/overflowing map returns, exact whole-framebuffer contents,
and mapping/synchronization order. The map callback in this unit test is
modeled; a real native mapping plus EARLY_BOOT integration has not yet been
executed for this new marker. No new cloud kernel build or phone run is implied.
The v11 image and its earlier evidence are unchanged.

The native runtime translation unit still needs compilation with the real
Apple SDK on macOS. The local Windows attempt using the pinned XNU headers
stops at missing string.h in kern/kcdata.h; replacement SDK headers were not
introduced to hide this prerequisite.
