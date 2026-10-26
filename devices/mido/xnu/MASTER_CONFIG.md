# MIDO master option-selection candidate

MASTER.arm64.mido is a dedicated, deliberately minimal DEVELOPMENT/DEBUG
candidate for the pinned XNU source commit
1b191cb58250d0705d8a51287127505aa4bc0789. It is not a proven build target,
complete dependency closure or a bootable kernel configuration.

## Selection and installation boundary

The candidate's intended source-tree destination is config/MASTER.arm64.mido.
The pinned SETUP/config/doconf selects one architecture master in this order:

1. MASTER.arm64.mido.PLATFORM
2. MASTER.arm64.mido
3. MASTER.arm64.PLATFORM
4. MASTER.arm64

It combines that selected file with config/MASTER. It does NOT layer all
these architecture files together. Consequently this candidate declares its
own option groups, machine and OSFMK_MACHINE rather than assuming that the
Apple ARM64 defaults will be inherited. The existing architecture patch is
still needed for MIDO compiler flags, board header and machine registration.
No primary upstream checkout has been modified or master installed there.

Only DEVELOPMENT and DEBUG are reviewed here. Do not invoke a default
RELEASE build with this candidate; no RELEASE, PROFILE or KASAN group is
defined or validated. The existing macOS preflight does not run this probe.

## Candidate scope

The groups select a single traditional scheduler family, Mach/BSD, basic
IOKit/libkern facilities and devfs/fifo/named streams. INET selects NETWORKING and SOCKETS
because the pinned BSD startup unconditionally includes TCP headers whose
types depend on that configuration. This is software dependency closure,
not working Wi-Fi, cellular connectivity or permission to access radio hardware.
The first broad compile also demonstrated unconditional BSD exec/exit/protection
dependencies on memorystatus, jetsam and MAC framework declarations. These three
standard upstream selectors are now required rather than inventing missing
functions or process fields. This enables framework configuration, not working
security policies or a validated runtime memory-pressure implementation.
Run 40210738486 further exposed unconditional memorystatus references to pressure
events and coalition APIs. vm_pressure_events and config_coalitions now close
those selectors locally; their sed/awk selection passes in
artifacts/mido-pressure-coalitions-v1, not yet a new full kernel compile.
CONFIG_NOMONITORS is selected;
CONFIG_KERNEL_INTEGRITY, KPC, KPERF, KASAN and kernel TBI are not.
CONFIG_PMAP_PPL, NOS_ARM_PMAP and NOS_ARM_ASM select the pinned source
implementation of entry and pmap. These options do not establish hardware
compatibility or turn on XNU_MONITOR; the separate board probe still checks
XNU_MONITOR is zero and NO_MONITOR is one. CONFIG_NOMONITORS is not a
substitute for that board-level check.
This is an experimental port configuration, not a production
security policy, and omitting an option does not implement its replacement.

The base MASTER also emits unconditional defaults, including SERIAL_CONSOLE
and VIDEO_CONSOLE. The checker preserves them; it does not prove that these
console paths are safe or connected to MIDO. Filesystem selection does not
register a storage driver or authorize access to eMMC. No timer/GIC backend
is registered with XNU by this file.

Minimal groups can expose missing cross-component dependencies when the
real kernel is compiled. The option list must be revised against compiler
and linker evidence, not described as complete because selection succeeds.

Run 40215492662 reached the end of the compilation attempt without the log/time
guard terminating it. Its broader log exposed network code that assumes NECP,
multipath TCP, traffic management and Skywalk packet/channel types. The local
candidate now selects their genuine implementations, including the same five
nexus groups as the pinned ARM64 SKYWALK_BASE recipe. NAMEDSTREAMS and
CONFIG_IOSCHED close the directly observed VFS/resource-fork and metadata-tier
references. These are software dependency selections, not MIDO Wi-Fi/GPU
drivers, hardware initialization or a complete dependency proof. KPC/KPERF
remain disabled. Both DEVELOPMENT and DEBUG pass the actual upstream selector
and native config utility for osfmk and BSD; BSD makefiles select necp.c,
mptcp.c and skywalk/core/skywalk.c. Evidence: artifacts/dependency-closure-v1.
This newest option closure has not yet been validated by an Apple compile.

Follow-up run 40216034991 at 3a9db97 now exercises that option closure with
the real Apple compiler. Configuration/header stages pass, but the overall
kernel compile still fails. In particular, telemetry-dependent bank fields,
zone logging and further network option/header dependencies remain unresolved.
This is not a complete configuration or a validated network runtime.

## Reproducible local check

From the workspace root, using Git for Windows Bash:

    python tools/check_mido_master.py --shell "C:\Program Files\Git\usr\bin\bash.exe" --output-directory artifacts/NEW_DIRECTORY

The tool downloads only config/MASTER and SETUP/config/doconf at the pinned
commit and requires their reviewed SHA-256 hashes. It copies the candidate
into a fresh artifact directory and extracts the original sed/awk selector
verbatim from doconf. Bash runs that selector against the same concatenation
of MASTER, architecture master, +configuration, MASTER, architecture master.
No Python reimplementation of the selection algorithm is used.

The csh wrapper, unifdef, config compiler and build makefiles are NOT run.
Since unifdef is omitted, both master inputs must contain no preprocessing
directives; the tool rejects those rather than silently selecting both arms.
The output is intentionally named .fragment: doconf's builddir, objectdir
and sourcedir tail is absent. No config-generated headers are produced.

Local evidence: artifacts/mido-master-v2/report.json records successful
DEVELOPMENT and DEBUG selection for the earlier candidate, not the revised
entry/pmap selectors. The current selection evidence is under
artifacts/mido-headers-v3/selection. The tool checks required/forbidden options,
duplicates, machine declarations and variant separation. Sixteen new unit
tests exercise these guards. See BUILD_CONFIG.md for subsequent native
config-compiler and real make-include checks; all 94 Python tests now pass.

## Remaining build gate

Two actual make includes and osfmk config/header generation now have local
checks; see BUILD_CONFIG.md for their boundaries. Next evaluate the complete
make target and SDK discovery with a suitable macOS toolchain. Compile kernel sources to identify
missing option dependencies, platform source registration and unresolved
symbols. Entry/MMU ownership, safe MMIO mappings and vector/timer hooks
remain independent gates before any hardware boot attempt.

## IPC dependency follow-up

The deeper compiler log in run 40213517191 shows that the disabled
IMPORTANCE_INHERITANCE path hides special-reply-port APIs and task importance
fields still used by other selected IPC sources. The candidate now selects
importance_inheritance instead of inventing fields or function declarations.
The real pinned selector and native config compiler generate the enabled
importance_inheritance.h and select genuine ipc_importance.c for both
DEVELOPMENT and DEBUG. Both are required by the configuration/header guards.
KPC and KPERF remain forbidden; the disabled AST include/callback is guarded
instead of enabling Apple performance counters on mido. Evidence:
artifacts/mido-importance-selection-v1 and artifacts/dependency-frontend-v1.
These local checks are not Apple kernel compilation or hardware validation.
