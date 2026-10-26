# MIDO XNU groundwork, 2026-10-25

Status: a dedicated MIDO architecture scaffold now passes local compiler
checks; see ARCHITECTURE.md for its deliberately incomplete scope.
No XNU kernel has been built or run here. The EL1 BRK/ERET and
counter result is from our standalone diagnostic, not XNU. Nothing in this
directory authorizes booting another device's kernel or changing partitions.

Standalone early GICv2/timer sources and mock tests now exist in early/.
They are not connected to XNU or a phone payload; see early/README.md.

A DEVELOPMENT/DEBUG master candidate has local selector, make-include and
native osfmk config/header-generation checks. See MASTER_CONFIG.md and
BUILD_CONFIG.md for the deliberately incomplete scope and remaining gates.
The complete source tree is now prepared locally; SDK_GRAPH.md documents
two real macOS SDK/top-level make diagnostics and their dry-run limitations.
HOST_SETUP.md records successful real macOS host-tool setup at commit
a55c8a0/run 40204223224. Real header export and doconf/config generation
passed at 9be1920/run 40204919828. The first kernel compiler invocation
failed on an obsolete Clang flag and nonexistent include search paths.
See KERNEL_BUILD.md. No kernel compilation/link success or boot approval
is established; platform and loading gates remain outstanding.

Earlier compile checkpoint: run 40207369644 produced 21 LLVM bitcode files,
not a linked kernel, before the 4 MiB diagnostic budget stopped the run.
The broader attempt exposed an incompatible IIG-generated RPC ABI as well
as incomplete configuration and modern-compiler diagnostics. Real code-generation
probes in run 40207890758 confirm that deployment targets 16.6, 20.0 and 21.0
all still emit kernelContent, which the pinned IORPC structure lacks.
A matching generator or a separately reviewed RPC backport is required;
no arbitrary field was added to the kernel ABI. A new fail-closed check
prevents another compile attempt with that demonstrated mismatch.
No first XNU launch has occurred and no new device commands were executed.

Current checkpoint: run 40210488155 successfully compiled all 17 hash-pinned
legacy-RPC candidates through genuine XNU make rules and exported kernel headers.
All 94 invocation unions have compile-time size, alignment, field-offset and
inline-content assertions. This is real object compilation, not runtime IPC
validation. An explicit opt-in generation hook now applies only these reviewed
outputs inside disposable build directories; the default ABI guard still blocks
unadapted generator output. Run 40210738486 passed that guard and reached 55
LLVM bitcode .o files before the diagnostic limit, but no kernel was linked.
Subsequent run 40212280204 reaches 59 LLVM bitcode objects. Real compilation
validates the pinned firehose header/SPI declarations, 21 diagnostic format
repairs and explicit startup/sysctl initializer defaults. Numerous other
compiler errors remain, and libfirehose_kernel still needs a genuine build;
there is no linked XNU or boot image. See KERNEL_BUILD.md for the evidence and
the still-outstanding platform/loading gates. A fresh read-only TWRP capture
confirms the same hardware tree except /chosen/pureason; no device writes or
reboots were performed.

Latest compile checkpoint: run 40213517191 reaches 168 LLVM bitcode objects
with compact diagnostics, not a linked kernel. The 55 reviewed no-op switch
defaults and 52 same-width diagnostic casts have real Apple compilation
coverage. A deeper partial log exposes more source/configuration failures.
The subsequent local candidate selects genuine IPC importance inheritance,
adds missing socket/log headers and gates KPERF/KPC AST code while profiling
remains disabled. Native DEVELOPMENT/DEBUG configuration generation and 226
Python regressions pass; these newest dependency changes await cloud compile
validation. See KERNEL_BUILD.md for the distinction between these checkpoints.

## Source pins

Apple repository: apple-oss-distributions/xnu.
Selected reference tag: xnu-8796.141.3.
Annotated tag object: f625db25f47631424dc62ac1c3414b6e530f7e8a.
Peeled source commit: 1b191cb58250d0705d8a51287127505aa4bc0789.
These are different objects; use the source commit for a checkout pin.

Relevant primary files at that commit:

- pexpert/pexpert/arm64/boot.h: boot_args and Boot_Video ABI.
- pexpert/pexpert/arm64/BCM2837.h: existing ARMv8 architectural baseline,
  with Raspberry Pi-specific platform definitions that must not run on mido.
- config/MASTER.arm64.bcm2837: configuration reference, not a mido target.
- osfmk/arm64/start.s: entry and translation setup still require a full audit.

Comparison repository: dipa-studio/ios-sweet, commit
45263bee51df4a0f55cdf9c649af886399488ddb.
Its workflow pins blacktop/darwin-xnu-build at
663906528d1cd5ea8fde7de6f16de73db9511549.
The reviewed workflow specifies macos-14 / Xcode 15.x for its build ABI.
This is a historical recipe, not a guarantee that the hosted runner and
dependencies are still available. Do not execute its shim on mido.

## Port boundaries

| Component | Evidence / required change |
| --- | --- |
| CPU | Cortex-A53 ARMv8-A. Sweet patch 0004 selects armv8.2-a+crypto; replace the configuration and audit emitted instructions. ARM64_ALL metadata alone does not establish an ARMv8-A instruction baseline. |
| Interrupts | Mido has GICv2 distributor 0x0b000000 and CPU interface 0x0b002000. Sweet uses GICv3 ICC system registers and redistributors; implement and review a GICv2 backend instead. |
| Timer | Counter reads and reported 19.2 MHz frequency confirmed, but no timer interrupt has been tested. Derive interrupt routing from the live platform data rather than copying sweet IDs. |
| Storage | Mido uses eMMC/SDHCI, not sweet UFS. Keep all storage drivers and persistent logging disabled for initial kernel entry. |
| Display | Runtime loader handoff is 1080x1920, stride 3240, 24bpp at 0x90001000. Recovery fb0 is a different layout. Audit XNU video routines before exposing this surface. |
| Memory | Live RAM banks are not an allocation map. Validate reserved-memory, loader, payload, framebuffer, kernel segments, stacks and page tables before selecting any destination. |
| Entry | EL1 confirmed only for our diagnostic. XNU entry, MMU/cache state and physical/virtual mappings need their own contract. |
| Device tree | Linux FDT is not Apple Device Tree. A dedicated converter/generator and validation are still missing. |

## AArch64 boot_args layout

From the selected Apple boot.h using the AArch64 LP64 ABI; this is a layout
record, not a populated handoff. Pointer interpretation and revision selection
must be checked against the selected start.s and platform code before use.

| Field | Byte offset | Bytes |
| --- | ---: | ---: |
| Revision | 0 | 2 |
| Version | 2 | 2 |
| virtBase | 8 | 8 |
| physBase | 16 | 8 |
| memSize | 24 | 8 |
| topOfKernelData | 32 | 8 |
| Video | 40 | 48 |
| machineType | 88 | 4 |
| deviceTreeP | 96 | 8 |
| deviceTreeLength | 104 | 4 |
| CommandLine | 108 | 608 |
| bootFlags | 720 | 8 |
| memSizeActual | 728 | 8 |

Total 736 bytes, alignment 8. Video contains six 64-bit unsigned long fields:
base address, display, row bytes, width, height, depth. Padding is significant.
Do not serialize this with a Windows-native unsigned long or pointer layout.

## Host-only preflight

Run: python tools/inspect_xnu.py PATH_TO_UNCOMPRESSED_THIN_MACH_O

The tool reads a local file only, prints JSON and never invokes ADB/fastboot.
It rejects ARM64E, non-ARM64_ALL subtypes, filesets, malformed command tables,
overlapping segment ranges, invalid thread state and entry points outside
file-backed executable memory. Chained fixups are bounds-checked only and
reported as unresolved blockers; unknown commands are also blockers.

This is not a full Mach-O validator, section validator, instruction decoder,
kernel authenticator, linker, loader or boot approval. A success exit means
only that this limited structural inspection completed. boot_approved is
always false, including synthetic test images. No physical load addresses
or bootable package are generated.

## Next implementation gates

1. Create a minimal dedicated MIDO configuration, initially one CPU, with
   storage disabled, no ARM64E/PAC assumptions and an audited ARMv8-A baseline.
2. Implement the early platform and GICv2/timer backend, using the existing
   BCM2837 target only as an architecture reference.
3. Establish a macOS/Xcode build environment for the selected recipe and
   review dependency availability. Local Windows NDK is sufficient for our
   diagnostic payload, not a demonstrated full-XNU toolchain.
4. Build a kernel, inspect actual output and implement a validated fixup
   resolver if required. Complete Apple DT, boot_args and RAM placement.
5. Only after these gates, review a RAM-only first-entry image. Working
   XNU would still not establish an iOS userspace, graphics or device drivers.

The user authorized private cloud build preparation, the initial commit/push
and one bounded preflight against the screenshot-confirmed included allowance.
See CLOUD_BUILD.md for the billing and deployment gates.
Never include phone dumps, personal backups or firmware readbacks in CI inputs.
