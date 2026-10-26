# Local make/config generation checkpoint

No XNU kernel or boot image is built at this checkpoint. The phone, CI,
repository history and remote repository are untouched by these checks.

## Actual GNU Make evaluation

tools/check_mido_make.py applies the existing architecture patch to hash-pinned
Apple sources, then evaluates the complete MakeInc.def and MakeInc.kernel
with GNU Make 4.4.1. Three declarative platform lines are extracted verbatim
from hash-pinned MakeInc.cmd; SDK discovery and the rest of that file are not
executed. The harness supplies lowercase configuration names, separated
artifact-shaped paths and disables compiler bounds-attribute detection.

The requested goal is an empty probe target with --just-print, not any kernel
or installation recipe. This is real make expansion and upstream validation
of those includes, NOT evaluation of the full top-level recursive target.

Run from the workspace root with an explicit GNU Make executable:

    python tools/check_mido_make.py --make MAKE_EXE --output-directory artifacts/NEW_DIRECTORY

Evidence: artifacts/mido-make-v4/report.json. DEVELOPMENT/DEBUG on both
MacOSX and iPhoneOS preserve arm64, Cortex-A53, ARMv8-A and strict alignment.
They use the upstream static-link path. They do NOT share a memory contract:

| Platform | Memory define | Kernel link address | DEVELOPMENT filename |
| --- | --- | --- | --- |
| MacOSX | -DARM_LARGE_MEMORY=1 | 0xfffffe0007004000 | kernel.development.mido |
| iPhoneOS | -UARM_LARGE_MEMORY | 0xfffffff007004000 | mach.development.mido |

Neither platform is approved for a kernel boot. The harness does not provide
SDKVERSION, so the recorded minimum-deployment-version flags are incomplete.
iPhoneOS also introduces the upstream minimal UBSan flags and an expected
sanitizer ignorelist path. Selecting an SDK, memory layout and sanitizers
requires a separate full build/pmap audit; do not silently strip these flags.

The first failed make probes are preserved. They exposed missing harness
platform declarations, colliding empty output paths and an incorrect harness
assumption that iPhoneOS uses the same kernel filename as MacOSX. These were
probe corrections, not handset or kernel execution failures.

## Actual config compiler and osfmk headers

tools/check_mido_headers.py downloads 14 hash-pinned Apple files: the complete
config utility sources/grammar plus the real osfmk file manifests and make
templates. WinFlexBison generates the parser/lexer and Zig builds a native
x86_64 Windows executable. No Apple source is patched; the explicit
tools/xnu_config_host_compat.h supplies the BSD u_char alias and index/rindex
string aliases. The host is compiled as GNU89, not as ARM64 kernel code.

The master selector is reused, its path tail is added, and the real executable
parses the resulting configurations. It generates ioconf.c, feature headers,
meta_features.h and an osfmk Makefile. No generated Makefile is executed.

    python tools/check_mido_headers.py --zig ZIG_EXE --bison BISON_EXE --flex FLEX_EXE --shell BASH_EXE --output-directory artifacts/NEW_DIRECTORY

The v2 run correctly failed because the previous master candidate excluded
all four audited core sources: start.s, arm_init.c, arm_vm_init.c and pmap.c.
The root cause was missing nos_arm_asm, nos_arm_pmap and config_pmap_ppl
selectors. The master and selector checks now require these, and the actual
generated source list must contain all four paths. In this XNU revision,
CONFIG_PMAP_PPL is also a source-implementation selector; treating its name
as equivalent to enabling the Apple secure monitor was incorrect. The board
scaffold independently keeps NO_MONITOR=1 and checks XNU_MONITOR=0.

Evidence: artifacts/mido-headers-v3/report.json. DEVELOPMENT produces 56
files and DEBUG 57, including the generated Makefile and ioconf.c, not just
headers. Both produce MACH_ASSERT=1; debug.h differs as DEBUG=0/1. The host
compiler log is clean. Only osfmk generation is covered, not BSD, IOKit or
the other component configurations and dependency closure.

An additional local integration probe compiled the existing ARM64
config-probe.c with each generated CONFIG_DEFINES list and meta_features.h,
using the patched board/proc_reg headers and NDK Clang. Both passed the
existing no-Apple-monitor/PAC/PMAP_CS and 4KB-granule assertions. Its report
is artifacts/mido-headers-v3/generated-architecture-report.json. This still
uses the documented empty mach/machine.h stub and ASSEMBLER exclusion; it
does not compile entry assembly, pmap or the full kernel.

## Local tool acquisition and regressions

Tools are portable downloads under ignored artifacts, not system installs.
The GNU Make package and its two runtime DLLs came from the official MSYS2
repository with package-page SHA-256 checks; package pins are recorded in
artifacts/gnu-make-local-v1/packages.json. Zig 0.15.2 was verified against
the official download index:

    3a0ed1e8799a2f8ce2a6e6290a9ff22e6906f8227865911fb7ddedc3cc14cb0c

WinFlexBison v2.5.25 came from lexxmark/winflexbison's GitHub release.
The release exposes no asset digest; the locally observed zip SHA-256 is:

    8d324b62be33604b2c45ad1dd34ab93d722534448f55a16ca7292de32b6ac135

That last hash records the downloaded bytes, not an independent publisher
signature. Both bundles are under artifacts/config-host-tools-v1. No tools,
generated binaries, private phone data or caches are added to source control.

All 94 ordinary Python tests pass, including 12 new make-output guards and
ten config-output guards. The 16 PowerShell mock regressions also pass.
No automatic workflow or cloud job was added. The next gate remains a full
macOS make/SDK/component-configuration check and actual kernel compilation,
followed by platform integration and memory/entry validation before any boot.

Follow-up: SDK_GRAPH.md describes the complete source tree now prepared
locally and the new, unexecuted macOS-only top-level make diagnostic.
