# Dedicated MIDO architecture scaffold

Status: local compile-only groundwork, not a full XNU configuration or port.
No kernel binary or boot image is produced. No device commands are issued.

## Patch scope

The separate 0002-mido-exclude-amcc.patch adds a not-mido dependency to
the two AMCC sources in osfmk/conf/files.arm64. Only MASTER.arm64.mido
declares the mido_no_amcc pseudo-device; other targets retain their source
selection. CONFIG_PMAP_PPL remains enabled because it also selects public
ARM initialization sources. MIDO does not enable XNU_MONITOR or the Apple
KTRR/CTRR features guarding AMCC declarations and calls. No success-returning
AMCC stubs are provided. This change does not establish link or boot success.

patches/0001-mido-architecture-scaffold.patch applies to three exact files
from Apple XNU commit 1b191cb58250d0705d8a51287127505aa4bc0789 and adds MIDO.h.

- makedefs/MakeInc.def registers MIDO, provides Cortex-A53/ARMv8-A flags and
  strict alignment, and explicitly overrides the ordinary machine
  architecture selection to arm64 rather than the fallback arm64e.
- pexpert/pexpert/arm64/board_config.h selects a dedicated MIDO header and
  limits the declared bring-up topology to one CPU and one cluster. PMU
  counters are zero because no PMU backend is implemented.
- pexpert/pexpert/arm64/MIDO.h defines the basic ARMv8 architecture macros,
  no Apple monitor and no efficiency-core distinction. It rejects ARM64E,
  PAC/LSE feature macros and any definition of __ARM_16K_PG__, including zero.
- osfmk/arm64/proc_reg.h gets a separate MIDO cache-line branch. It does not
  define BCM2837 or select Raspberry Pi UART, panic-buffer or timer routing.

The 4KB path is a provisional scaffold choice, not a hardware MMU test.
The MAX_CPUS limit is not a demonstrated SMP-disable or CPU-affinity mapping.
Defining ARM_ARCH_TIMER does not configure a timer interrupt or GIC.

## What the probe actually checks

tools/check_mido_config.py downloads only the three public source files,
checks their SHA-256 values, dry-runs the patch, then applies it in a new
isolated artifact source tree. Existing output is never overwritten.
The primary source tree and private recovery dumps are not modified or used.

It reads the exact reviewed machine-flags line, compiles config-probe.c for
arm64-apple-macos13.0 and checks topology, cache-line and TCR granule macros.
The probe supplies an empty mach/machine.h and defines ASSEMBLER to exclude
C-only proc_reg.h declarations. GNU make is NOT evaluated, and the actual
kernel C/assembly, linking, deployment SDK and platform backend are not built.
The make architecture override still needs full build-system validation.

The first local attempt exposed a real toolchain hazard: with NDK Clang 19
and the Darwin target, -march=armv8-a alone still advertised PAC, LSE and
FP16 features. Explicit -mcpu=cortex-a53 removed those unwanted defaults.
The scaffold does not certify every optional instruction extension or
instruction emitted by a future kernel build. That needs an output audit.

## Local validation, 2026-10-25

Command, from the workspace root, with COMPILER set to the local Clang path:

    python tools/check_mido_config.py --compiler COMPILER --output-directory artifacts/NEW_DIRECTORY

Original successful local result: artifacts/mido-config-scaffold-v3/report.json.
All eight compiler scenarios pass: baseline compiles, while ARM64E, injected
LSE/PAC macros, an actual Apple-A14 CPU override, 16KB defined as either one
or zero, and an Apple-monitor override are rejected. The LSE/PAC macro
scenarios are configuration injections, not hardware execution tests.
The resulting baseline assembly contains only mov w0, #1 and ret.
Ordinary regressions: 44 Python tests and 16 PowerShell mock cases pass.
The failed v1 artifact is preserved as evidence, not a usable candidate.

## First scaffold cloud result

Commit b3b6c0e was pushed with the user's approval. Run 40196665410 completed
with failure in eight seconds on Apple Clang 17 / Xcode 16.4. Apple boot_args
and all 44 ordinary tests passed. The scaffold checker reported only
apple-cpu-rejected as failed: overriding the CPU to apple-a14 while retaining
-march=armv8-a did not produce the expected rejection on Apple Clang, although
the same negative scenario was rejected by local NDK Clang 19. The overall
cloud run is NOT green; this is a compiler-probe portability issue, not a
demonstrated kernel failure. No kernel was built.

The local follow-up replaces that ambiguous mixed CPU/architecture test
with a coherent Apple-A14 plus ARMv8.5-A negative case, retaining all eight
scenarios rather than dropping the failed test. Failure output now includes
the compiler exit code and extra flags. All eight follow-up scenarios pass
locally in artifacts/mido-config-scaffold-v4/report.json. The user authorized
committing this follow-up and one additional bounded cloud run; check that
run's result separately. The first cloud log and result are saved under
artifacts/cloud-preflight-40196665410; no automatic retry was made.

The macOS-preflight workflow includes this check. The user authorized one
commit/push and one bounded cloud run; verify its result separately before
claiming the scaffold passes Apple Clang. The earlier
cloud run 40195920314 passed only the toolchain/boot_args/39-test preflight at
commit 92ba58e, using macOS 15.7.9 arm64, Xcode 16.4 and Apple Clang 17.

Follow-up checkpoint: commit 938beb2 passed run 40196896677 on Apple Clang
17 / Xcode 16.4. All eight architecture scenarios, the boot_args ABI probe
and 44 Python tests passed. Evidence is saved under
artifacts/cloud-preflight-40196896677. This validates the compiler scaffold,
not a full kernel build. Subsequent standalone IRQ/timer changes have only
local validation; they were not included in that cloud run.

## Required before a kernel build or device test

A dedicated DEVELOPMENT/DEBUG master candidate now exists in
MASTER.arm64.mido. Its actual pinned sed/awk selection passes locally;
see MASTER_CONFIG.md. Separate make-include and native config-compiler checks
now pass, including generated osfmk headers and core entry/pmap source-list
validation; see BUILD_CONFIG.md. These do not build the kernel or establish
complete kernel dependencies.

- Complete and evaluate a dedicated master configuration and target-specific
  build rules. Registration alone does not make the MIDO target buildable.
- Implement early platform entry, GICv2, timer routing and failure reporting.
- Audit 4KB pmap/early page tables and the physical/virtual entry contract.
- Implement and validate Apple DT, boot_args and reserved-memory placement.
- Review Xcode/iig/KDK and dependency compatibility for XNU 8796.
- Build and inspect an actual kernel; resolve fixups if present.

No storage driver is added here. This does not prove storage writes are
disabled in a future kernel build. No MMIO or storage-writing code from
sweet or Raspberry Pi should be executed on mido to fill these gaps.
