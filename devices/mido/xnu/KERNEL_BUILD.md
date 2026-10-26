# Real header/configuration stages and bounded compilation attempt

Status: commit 9be1920 ran on macOS in run 40204919828. All 154 then-current
Python tests passed, as did real setup, header export and MIDO configuration
generation. The first kernel compiler invocation failed; no kernel was
built. A local obsolete-flag correction adds four tests, bringing the local
total to 158; it has not yet been committed or tested on macOS.
Unit fixtures are not real kernel outputs. See HOST_SETUP.md for the
earlier successful host-tool milestone.

tools/check_xnu_build.py prepares a new full pinned source tree and runs
the already verified real setup stage with the pinned Apple availability
dependency. It then executes the original top-level exporthdrs target,
with no --just-print or generated-header stubs. Three representative
exported headers must be nonempty and inside the isolated build tree.
Their hashes are recorded; this is not a complete exported-header audit.

The next phase executes the original SETUP/config/doconf wrapper with
-c -cpu arm64 -soc mido and the explicit iPhoneOS/MacOSX platform, source
manifests, master directory and DEVELOPMENT output directory. -c selects
configuration generation only. The resulting osfmk Makefile and headers
are inspected by the existing verify_generated checker: assertions/debug
flags, entry/pmap source selection and CONFIG_PMAP_PPL must match.
No custom manifest generator or host compatibility header is substituted.

Only --attempt-kernel enables the subsequent real top-level build target.
Unlike setup, this is a genuine attempt at kernel C/assembly compilation
and linking, not a promise that it succeeds. It uses all the actual SDK,
source recipes and generated prerequisites from the preceding stages.
The default invocation stops after header/configuration validation.

    python3 tools/check_xnu_build.py --sdk iphoneos --output-directory artifacts/NEW_CONFIGURATION
    python3 tools/check_xnu_build.py --sdk iphoneos --attempt-kernel --output-directory artifacts/NEW_BUILD

Make phases remain serial through -j1 and explicit MAKEJOBS=--jobs=1.
The elapsed-time budget is 180 seconds from the start of the tool; each
post-setup subprocess is limited to the smaller of 90 seconds and the
remaining budget. Setup retains its own existing limits; source download
and SDK queries have their own bounded timeouts. The five-minute cloud
job is the outer bound. On expiry the active process group is killed,
the phase fails, and later phases are not started.

build-report.json records each phase command/result, first blocking error,
header and configuration hashes and any final kernel inspection. Per-phase
logs are retained in the artifact directory and their last 120 lines are
printed. A successful make exit with missing generated files is not green.
A successful build exit without an expected thin baseline-ARM64 executable
passing inspect_xnu is not reported as kernel_built. This structural check
does not authenticate a kernel or prove its instruction-set baseline.

boot_approved and platform_memory_approved always remain false, including
after a successful compile/link. The MIDO platform, GICv2/timer integration,
MMU/pmap contract, Apple DT, fixups and safe RAM placement are still gates
before any handset execution. This tool does not use ADB or fastboot,
generate a boot image or write any device partition.

.github/workflows/macos-kernel-attempt.yml is manual-only. Quota and real
configuration acknowledgements both default false. Kernel compilation has
a separate false-by-default approval. The private five-minute macos-15 job
uses the same pinned, credential-free checkout and concurrency group as
the earlier experiments. It installs nothing, automatically retries
nothing and prints reports rather than uploading binaries or phone data.
Consequently a produced kernel is not automatically saved off the runner;
safe artifact retention must be added before claiming a local usable image.
No billing settings or paid overages may be enabled for this stage.

## First real header/configuration and compile attempt

Commit 9be1920521c1a5bb1bc237988145e8c8695866bb ran once in 40204919828
on October 25, 2026. There was no automatic CI retry. Overall time was
42 seconds; the stage tool completed in 33.094 seconds. Evidence is in
artifacts/cloud-kernel-attempt-40204919828: run.json, run.log, timing.json,
setup-report.json and build-report.json.

Setup passed again. Real exporthdrs returned 0 in 9.444 seconds; the three
representative exported headers were present and hashed. Real doconf -c
returned 0 in 0.568 seconds and produced 57 files including the osfmk
Makefile, feature headers and configuration fragment. All existing source
selection, assertion/debug and pmap-implementation checks passed.

The real build target returned 2 after 4.102 seconds at CC mac_base.o.
Clang rejected the obsolete
-enable-trivial-auto-var-init-zero-knowing-it-will-be-removed-from-clang
option. It also reported nonexistent include search directories:

- OBJROOT/EXPORT_HDRS/libsa
- SDKROOT/usr/local/include/kernel
- SDKROOT/System/Library/Frameworks/Kernel.framework/Versions/A/PrivateHeaders/platform

These diagnostics are missing search paths, not yet proof that particular
required headers are unavailable from every source. Their actual role must
be audited before changing include policy. No dummy directories, headers,
SDK substitutions or broad warning suppressions have been added.
The compile attempt did not produce a demonstrated kernel object or kernel
binary; requested compilation is not successful compilation.

## Local frontend correction after that run

prepare_frontend validates the exact architecture-patched MakeInc.def
SHA-256 before removing only the obsolete consent-option line for an
explicit kernel attempt. It retains -ftrivial-auto-var-init=zero, CPU/ISA
flags and warning policy. It records before/after hashes in the build
report and never patches an installed SDK. Unexpected input or missing/
duplicate zero-initialization flags fail closed. Configuration-only runs
do not apply this correction.

Local evidence is artifacts/frontend-compat-v1. The real source copy was
transformed, and Android NDK Clang 19 targeting ARM64 Darwin/Cortex-A53
accepted the retained zero-initialization flag and emitted a zero store
in LLVM IR. The same compiler rejected the obsolete consent flag. This
is not Apple Clang 17 validation or a compiled XNU object.

The public-SDK search policy now conditionally includes only three known
optional search locations: libsa exports (the pinned libsa Makefiles declare
no exported headers), SDK kernel includes and SDK platform includes. Existing
directories remain searched; absent directories are omitted rather than
fabricated. Every other component include path and all strict warnings remain
unchanged. Required missing headers still fail compilation. The installed SDK
is not modified. This policy needs validation in the next real compile attempt.
Local regression suite: 176 tests and 16 PowerShell mock cases pass. No phone was accessed.

## Real frontend progress on 2026-10-25

Run 40205671040 stopped at the exact-source guard: the locally prepared
Windows copy had CRLF while the macOS archive had LF. The guard now hashes
canonical LF content; it does not accept arbitrary source changes.

Run 40205762154 passed those guards and exposed the missing MIDO board
header export plus the new pre-C11 compatibility diagnostic. The real board
header is now exported through the pinned pexpert Makefile, not copied into
the SDK or replaced by a dummy header. Only pre-c11-compat is disabled;
cast-function-type-strict remains visible but is not promoted to an error.
Other diagnostics, including missing includes and format checks, remain fatal.
This is a narrow change to warning policy, not unchanged warning flags.

Run 40205941493 exposed a real typo in the disabled-MAC branch: a pragma
named p although the parameter is cred. A hash-guarded correction names cred.
Run 40206189084 exposed unsigned-format diagnostic argument mismatches in
memdev.c; six explicit unsigned argument conversions fix only those prints.
No device behavior or persistent-storage access was added by those repairs.

Run 40206351110 produced six LLVM bitcode files under the target build
directory before stopping in BSD startup. These are not a linked kernel or
ARM64 machine-code proof. The report distinguishes bitcode from baseline
ARM64 Mach-O objects and does not claim to validate the bitcode target.
BSD startup unconditionally includes TCP types, so the master now selects
INET/NETWORKING/SOCKETS; the real pinned selector validates both configurations
locally in artifacts/mido-master-networking-v1. No network hardware support
is established. Run 40206485105 still failed in unix_startup.o; its warning
expansions pushed the actual errors out of the old 120-line log tail. The
runner now prints the first 80 compiler errors separately from that tail.

No successful kernel link, loading image or XNU execution is established.

## Broader compile and generator ABI blocker

Run 40206742494 reached 14 LLVM bitcode files after the BSD include repair.
Run 40206905234 passed the real Apple Clang UIO probe and reached 15 files.
The UIO correction moves alignment from an over-aligned byte typedef onto
each declaration; fixed and variable-size arrays keep byte counts and 8-byte
alignment. Nine queue panic line-number arguments now explicitly match %u.
VFS diagnostic repairs preserve format checking rather than disabling it.

Run 40207369644 used one shared three-job make limit and --keep-going to
collect independent failures, still under the existing time/log ceilings.
It produced 21 LLVM bitcode files before the 4 MiB log ceiling stopped it.
Its complete generated diagnostics are saved locally under
artifacts/cloud-kernel-attempt-40207369644/diagnostics. Remaining failures
include incomplete memory-status/MAC configuration, newer style warnings,
format mismatches and an actual generator/kernel ABI incompatibility.
The non-PAC pmap padding rename fixes a duplicate reserved10 name without
adding/removing fields; it has local source-transform tests, not a successful
pmap compile or hardware validation. Every applied source repair now records
its before/after hashes in the build report.

The installed IIG is DriverKit-427.100.5 from Xcode 16.4. It generates
rpc.kernelContent and designated initializers for that field, while the
pinned kernel's IORPC has only message/reply pointers and send/reply sizes.
Installed Xcode choices start at 16.0; no matching older tool was found.
Run 40207676338 captured real IIG help but its configuration-only shell
branch hit Bash 3's empty-array/nounset behavior. Nonempty argument-array
construction fixes that workflow bug.

Run 40207890758 passed real setup, exports, configuration and 174 then-current
Python regressions. It deliberately did NOT request kernel compilation.
Separate successful IIG invocations for deployment targets 16.6, 20.0 and
21.0 each emitted 17,557-byte OSObject implementations with eight occurrences
of kernelContent. Changing deployment target did not solve the mismatch.
Evidence is artifacts/cloud-iig-40207890758/diagnostics/iig-probe. Passing
this configuration-only workflow is not a successful kernel build.

inspect_iig_abi now checks the real generated OSObject implementation against
the actual IORPC declaration and blocks compilation on the demonstrated field
mismatch. Missing, escaped, empty or oversized generated files also fail.
This is a narrow ABI guard, not full RPC validation. A compatible generator
or a reviewed legacy-RPC code-generation backport remains necessary. Do not
invent a new structure field to make the compiler green.

The workflow retains only explicit generated logs/reports for one day using
the pinned official upload-artifact action. A separate success-only artifact
can retain the inspected linked kernel; no such kernel exists yet. Phone
dumps, backups and firmware readbacks are not artifact inputs.

The guard was verified on real generated output in run 40208223918 at
commit cd5bb12. All 176 Python regressions and the Apple Clang alignment
probe passed; host setup, exports and configuration succeeded. The guard
then recorded compatible=false, header_has_kernelContent=false and eight
occurrences in obj/DEVELOPMENT_ARM64_MIDO/iokit/DriverKit/OSObject.iig.cpp.
It stopped before invoking the kernel build target, as intended. Evidence
is artifacts/cloud-iig-guard-40208223918/diagnostics. The red workflow is
an expected ABI rejection, not a successful kernel or first boot. No cloud
run is still active, and no device was accessed during these build changes.

## Offline RPC reference inventory

The ABI report now inventories kernelContent references by line and role,
without modifying generated code or approving a backport. All three retained
OSObject probes contain the same eight references: two invocation-union fields,
two generic message lookups, two RPC initializers and two typed message lookups.
There are no unclassified reference lines in these particular probe outputs.
The local report is artifacts/iig-reference-audit-v1/report.json.

This establishes that deleting an initializer field alone cannot restore the
old ABI. A candidate backport must also preserve the four-field invocation
overlay, select the inline-content message representation, and keep the
MESSAGE_CONTENT accessor consistent with it. Existing IPC size, descriptor,
object-reference and string checks must remain intact. Other generated classes
have not been inventoried, and lexical classification is not semantic proof.
The compile guard remains blocking; no generator output or kernel ABI was
changed. All 178 Python regressions pass after this diagnostic improvement.
No cloud run or device command was needed for this offline investigation.

## Isolated legacy-RPC candidate

tools/prepare_iig_legacy_probe.py now produces a candidate only for the exact
retained OSObject implementation SHA-256
39d669f6a505167c6cc268baca4e29a99cea0c66c154358c4865837ab040c10a
and the exact pinned IORPC header. It selects eleven existing legacy branches:
the eight reference sites plus two invocation message types and the shared
MESSAGE_CONTENT accessor. The original four-field kernel ABI is not changed.
Unknown source hashes, conditional layouts or branch counts are rejected.
Outputs go to a new isolated directory; no build tree is patched.

All three retained deployment-target outputs produce the same candidate hash:
f6f0f6c19730e599bf11a76ffb558d785d28a6ac40ed68f0605382af5afde05a.
The optional bounded compiler probe uses the entire pinned IORPC header with
its self-contained DriverKit declarations and KERNEL=1, not mocked descriptors.
It compiles extracted generated unions with ARM64 iOS target, warnings as
errors, and static assertions for both invocation sizes, alignments, all four
field offsets and both inline-content offsets relative to the descriptor walk.
Local NDK Clang passes this check; evidence is
artifacts/iig-legacy-candidate-v3/report.json. This compiler target is not a
successful Apple SDK or full generated OSObject compilation.

A separate source-local preprocessing comparison, with include directives
removed and KERNEL undefined, confirms byte-identical userspace output.
Defining KERNEL=0 is not equivalent because the generator also uses ifdef.
Counts of descriptor, IPC error, send/reply size, object-cast and string checks
are unchanged. Evidence is preservation-report.json beside the candidate.
Neither token counts nor preprocessing equivalence prove runtime IPC safety.

All 185 Python tests pass, including rejection, branch-preservation, layout
probe and compiler-failure cases. The next gate is full generated-source
compilation against genuine exported kernel headers and coverage of other IIG
classes before any build integration. The original compile guard remains in
force. No cloud minutes or phone commands were used; no new boot image exists.

## Genuine RPC object compilation and integrated build checkpoint

The earlier isolated-only notes above are historical. A bounded native make
probe now generates the actual IOKit configuration and requests the real
OSObject.iig.cpo target with exported kernel headers, normal warnings-as-errors,
baseline MIDO flags and BUILD_LTO=0 to retain an inspectable Mach-O object.
Run 40209665564 exposed ten missing override annotations in OSMetaClass.h.
A hash-guarded source repair adds only override tokens; it does not change
method signatures, fields or vtable slots. Runs 40209805410 and 40209892625 then
passed genuine OSObject compilation. The latter retained all generated classes.

tools/iig_legacy_profiles.json pins the exact inputs, outputs and branch counts
for all 17 generated implementations from DriverKit-427.100.5. Additional
reviewed forms cover reply-content lookup, a nested reply lookup and a kernel
content-pointer assignment. All source-local userspace preprocessing comparisons
remain equal before the subsequent maybe_unused annotations; these annotations
do not change behavior. Unknown inputs and partial class sets fail closed.

Run 40210155228 attempted all 17 classes and exposed implicit-zero designated
initializers and seven unused one-way RPC return variables. Hash-guarded source
repairs make VM guard and typed-allocation default zeros explicit, preserving
the private/external view field variants. Exactly seven void one-way wrappers
now explicitly annotate their already-ignored result variables maybe_unused;
no calls or error propagation were removed. No warning category was suppressed.

Run 40210488155 at 8dc8d1d successfully produced 17 ARM64_ALL Mach-O objects,
2,389,976 bytes in total. The genuine compiler also checked all 94 invocation
unions for size, alignment, all four RPC field offsets and inline-content offsets.
Evidence: artifacts/cloud-rpc-probe-40210488155/mido-rpc-probe.
This does not test RPC execution or hardware drivers.

tools/backport_iig_output.py installs an opt-in post-generation hook in the
isolated source Makefile. Each output must have an exact reviewed hash and one
of two reviewed generated locations beneath workspace artifacts. Adaptation is
atomic and adds the same compile-time assertions. SDKs and kernel ABI headers
are not modified. Unit cases reject escaped paths, unknown bytes and recipes;
the local integration test verified all 17 rewrites and 94 assertion groups.

Run 40210738486 at e6072ae explicitly enabled this hook for a full build attempt.
Real setup, exports and configuration passed, as did the ABI guard with zero
kernelContent references in adapted OSObject. The build produced 55 LLVM bitcode
.o files before the existing diagnostic budget stopped it. The count excludes
.cpo outputs and is not an instruction-baseline audit or linked kernel.
The log has 488 error lines, predominantly format/type diagnostics, plus more
configuration dependencies and a missing os/firehose_buffer_private.h.
Evidence: artifacts/cloud-kernel-attempt-40210738486/mido-build-diagnostics.

Local follow-up selects pressure events and coalitions for demonstrated BSD
references. The official distribution-macOS macos-135 tree maps the pinned XNU
commit to libdispatch cdb61e93e803d0093635f356753a9a30c09836db. Its real firehose
header is now downloaded with SHA-256
b1da2269d930974d1fb122d90446534553829dc2a3b090b3d0ea0813fd95dd45
into isolated EXTERNAL_HEADERS only, never the SDK. Staging passes locally in
artifacts/firehose-header-stage-v1. The required libfirehose_kernel library is
not built by this header-staging step. Parseable compiler fix-its are enabled
for the next bounded attempt; no compiler-proposed edits are automatically
applied.

Run 40211813154 compiled the dependency changes: setup, exports, configuration
and the reviewed RPC ABI check pass, but kernel compilation still fails. There
are 51 LLVM bitcode objects, no linked kernel. The real firehose header requires
OS_FIREHOSE_SPI=1; its absence hides declarations rather than supplying them.
The follow-up enables that explicit SPI in isolated kernel compile definitions.
It also changes 21 reviewed integer format specifiers across ten hash-pinned
sources, leaving arguments, control flow, ABI and warnings-as-errors intact.
Only fixed source coordinates are accepted; compiler fix-its are never applied
automatically. These follow-up repairs require another cloud compilation.

Run 40212095712 at acd8c23 validates those 21 format repairs against real
compilation, and no missing firehose declarations remain in its bounded log.
The build produced 57 LLVM bitcode objects before the 4 MiB log guard stopped it;
this is not a linked kernel. The follow-up makes formerly implicit zero values
explicit in the TUNABLE/TUNABLE_STR and SYSCTL_STRUCT_INIT macros. It preserves
field order, the DT tunable macro and the extension-node macro. The exact real
macro/structure extracts compile with ARM64 Clang19 in GNU C++17 mode with
missing-designated-initializer and reorder diagnostics treated as errors.
Evidence: artifacts/initializer-probes-v1. Run 40212280204 at dfbc146 then
validated these changes with the real Apple compiler: the previously observed
24 oid_link and seven var_is_str missing-field errors no longer occur. The
bounded log still contains 34 missing-designated-initializer diagnostics,
primarily allocation-site and IOKit aggregates, plus format, switch-default,
unused-variable and other diagnostics. It produced 59 LLVM bitcode objects
before the log guard stopped it. All counts describe partial, scheduling-
dependent build evidence, not a successful full compilation or link.

All 211 Python regressions and 16 PowerShell mock cases pass. The handset was
reconnected in TWRP 3.7.0_12-0 and a fresh read-only capture was saved locally at
artifacts/live-recovery-followup-v1. Its parsed FDT differs from the earlier
capture only in /chosen/pureason; the reservation map is unchanged. Recovery
reports 43 percent battery and the same NT35532 framebuffer configuration.
The final read-only check still finds the same TWRP, with 44 percent charge.
No reboot, temporary boot, flash, erase, relock or partition write was performed.
There is no new bootable kernel/image and no XNU first-entry evidence.

## Batched diagnostic repairs and quota conservation

The next batch adds 105 reviewed decimal signedness corrections at exact source
coordinates in 23 pinned files. Combined with the earlier 21 replacements,
the format inventory is 126 replacements in 27 files. The static manifest
tools/reviewed_decimal_profiles.json records the input hashes and evidence run
40212280204; no live compiler log is consumed by the build repair tool.

After format repairs, a separately hash-pinned aggregate pass preserves implicit
zero initialization in VM_ALLOC_SITE_TAG, the eight existing IOPMPowerState
entries and the performance-control interface/work-state initializers. Existing
callback bodies and started expressions are unchanged; omitted callbacks remain
null. Release, development and debug allocation-site layouts are covered, with
the zero-length array initializer emitted only for C++, not C11. No structure
declaration, kernel ABI or warning-as-error policy is changed.

All 216 Python regressions and 16 PowerShell mock cases pass locally. Exact
source structure/macro extracts pass ARM64 Clang19 checks in C11 and GNU C++17
for release/development/debug allocation-site layouts, plus C++ power-state and
performance-interface probes. Evidence: artifacts/aggregate-probes-v2. These
isolated checks are not full Apple compilation, platform validation or a boot.
Cloud validation will use one bounded five-minute job for this entire batch,
not a run per repair. Runner time is not a statement of billed Actions minutes.

Run 40212971703 at 70f3191 validates that batch with the real Apple compiler.
Its partial log contains no missing-designated-initializer errors, while format
error occurrences drop from 301 in run 40212280204 to 140. These are partial log
counts, not a full-build error census. Seventy LLVM bitcode objects were retained
before the diagnostic guard stopped compilation; no kernel was linked.

The next local batch records 52 same-width unsigned diagnostic argument casts
in 17 files and 55 explicit no-op switch defaults in 23 files. Only simple
identifiers/member accesses are cast; there are no duplicated evaluations,
pointer conversions or narrowing types. Defaults precede the first case, so
they neither create a last-case fallthrough nor cross case-local initializers.
Seven conditional-compilation switches are intentionally excluded. No switch
case body, error handling or warning policy is removed. The manifests pin the
formatted inputs and exact original switch-opening lines.

A native C before/after model passes all 16,641 input pairs, including unknown
values, nested switches, intentional fallthrough and a last case without break.
The transformed model also passes ARM64 C11/C++17 syntax checks with switch and
fallthrough diagnostics as errors. Evidence: artifacts/switch-semantics-v1.
All 223 Python regressions and the 16 PowerShell mock cases pass locally.

For the next cloud attempt, compiler messages retain errors, warnings, source
locations and Werror, but omit caret/source excerpts and bound macro backtraces
to two frames. This reduces repeated diagnostic output without suppressing any
warning category or raising the existing time/log limits. Parseable fix-its are
no longer emitted in this compact mode; future repairs must still be reviewed
against pinned source. The source transformations above are not yet Apple-
compile validated. The matching libfirehose_kernel build and platform/loading
gates remain outstanding.

Run 40213517191 at 1919d32 validates the switch/cast batch with Apple Clang.
It reaches 168 LLVM bitcode objects before the unchanged 4 MiB log guard,
compared with 70 in the previous, more verbose attempt. This reflects broader
compilation coverage, not a completion percentage. The deeper partial log
contains new format/initializer diagnostics and actual source/configuration
errors; its 565 format error occurrences must not be compared as a regression
against the earlier, narrower 140-error sample. No kernel was linked.

The subsequent local dependency follow-up selects IMPORTANCE_INHERITANCE
and requires both its generated header and ipc_importance.c. It adds real
net/if_var.h and os/log.h includes in socket sources. The AST profiling header
and callback are guarded by KPERF && KPC, leaving their enabled implementations
unchanged and keeping both hardware-profiling options disabled in MIDO. No
fake ifnet definition, log API, task field, counter count or IPC stub is added.
The source edits retain hash/layout guards.

The actual pinned selector and previously built native config utility pass
DEVELOPMENT/DEBUG generation, including the importance header/source and
disabled profiling checks. The complete prepared-source frontend pass also
passes locally, as do three ARM64 C11 disabled-profiling gate scenarios.
Evidence: artifacts/mido-importance-selection-v1 and
artifacts/dependency-frontend-v1. All 226 Python regressions and the 16
PowerShell mock cases pass. These newest dependency repairs have not been
Apple-compile validated; no extra cloud attempt was launched for them yet.

Only two cloud runs were launched for this batched follow-up, each reporting
51,000 ms run_duration_ms in the Actions timing API and each bounded to five
runner minutes. This API result is elapsed workflow time, not a quota balance
or billing conversion. Its zero-valued billable fields are not evidence of
free usage. The reported included allowance remains the spending boundary;
no billing settings or paid-overage options were changed. No phone command,
reboot, temporary boot or partition write was executed.

The user subsequently observed allowance consumption increasing from about
330.7 to 350 minutes for those two short macOS runs. Their elapsed runtime
must not be presented as allowance consumption. Per-job rounding and the
account's observed macOS conversion are consistent with about ten allowance
minutes per rounded runner minute. For planning, reserve 50 allowance minutes
for a single five-minute macOS job, rather than calling it a five-minute quota
cost. This is a conservative planning model, not an independently verified
billing balance or authorization for paid overages.

The next local batch explicitly preserves the existing zero defaults in six
IOReportChannelType initializers and the KALLOC_HEAP_DEFINE accounting view.
The reserved channel byte remains zero; heap statistics/list pointers remain
null, numeric fields remain zero, and the original heap identity and startup
registration remain unchanged. Eight aggregate source profiles are now pinned
after the earlier source, format and switch transformations. A fresh complete
frontend preparation passes all hashes. Actual pinned structure/macro extracts
pass freestanding ARM64 C++17 compilation with warnings as errors (the existing
reporter designation order is retained). Evidence is stored locally in
artifacts/channel-heap-probes-v1 and artifacts/channel-heap-frontend-v1.
All 228 Python tests and 16 PowerShell mock scenarios pass locally. This is
not a linked kernel, a whole-source Apple compiler result or boot approval.

Run 40214603688 at 0da07ec validates that batch with Apple Clang. Header export,
configuration generation and the reviewed IIG ABI guard pass. The partial
compiler log no longer contains the earlier designated-initializer, IPC
importance, missing log type or disabled KPERF AST errors. The build still stops
at the unchanged 4 MiB diagnostic limit (4,239,969 bytes, 17.09 build seconds),
retaining 168 LLVM bitcode objects, not a linked kernel. The Actions timing API
reports 56 seconds elapsed; this is not the allowance deduction. Only one new
cloud run was dispatched. An artifact download was retried without rerunning
the workflow.

The remaining explicit declaration failures in this partial log are optional
NECP, SKYWALK and multipath socket operations compiled while their features are
disabled. The next locally validated transformation gates the two NECP tracker
attribute updates with NECP, the UUID cellular-fallback socket option with
SKYWALK, and the multipath restriction propagation with MULTIPATH && MPTCP.
Without SKYWALK, the omitted socket option reaches the existing ENOPROTOOPT
default, rather than reporting fake success. The flow reporter advertises and
populates its domain extension only with NECP; its existing zero-size return
denotes an unavailable extension otherwise. Existing general socket restrictions
and tracker flags are retained. Enabled feature bodies are unchanged. No fake
network APIs, new hardware features or success-returning stubs are added.

Both post-aggregate source inputs are hash-pinned and all are validated before
writing. Fresh full frontend preparation and all 234 Python tests pass. Actual
gated source fragments pass ARM64 preprocessing checks for all 16 combinations
of NECP, SKYWALK, MULTIPATH and MPTCP. Evidence is local under
artifacts/network-gate-frontend-v1 and artifacts/network-gate-probes-v1.
These latest feature gates have not yet been Apple-compile validated; no second
cloud job was launched. Hundreds of format and other compiler diagnostics,
the real firehose archive, linking and all platform/loader gates still remain.

The subsequent local batch fixes the shared NVRAM diagnostic prefix in three
macro definitions, rather than changing hundreds of call sites. The existing
unsigned line-number format is retained and __LINE__ is explicitly converted
to unsigned int. File/function names, user formats, arguments, log conditions
and enabled/disabled macro branches are unchanged. The three NVRAM translation
units account for 262 format occurrences in the last partial log; these are not
262 independent source bugs or a full-build count. ARM64 actual macro extracts
pass both DEVELOPMENT and DEBUG type-checked fixtures, with the original signed
line argument failing the paired type assertions. NDK Clang does not reproduce
Apple's original printf signedness diagnostic, so this local evidence is a type
check, not a substitute for Apple compiler validation.

All 21 signed-decimal microsecond formats in pinned clock.c now use unsigned
decimal, matching the genuine clock_usec_t declaration and reviewed arguments.
No clock calculations, arguments, logging conditions or timing code change.
Both sources retain whole-file SHA-256 and exact-layout/count guards. Fresh
complete frontend preparation and all 236 Python tests pass locally. Evidence:
artifacts/log-prefix-frontend-v1. The next cloud check batches these edits with
the previously local optional-network gates; it reserves 50 allowance minutes
under the documented planning model, with no phone commands or paid settings.

The dispatch request for d378706 failed at the GitHub API connection. The run
list was checked before any retry: no run for that commit exists. Instead of
spending a run solely to reproduce the 4 MiB diagnostic cutoff, the next batch
allows at most 16 MiB for the actual kernel build log; other phases remain at
4 MiB. Compiler warnings/errors are not filtered or suppressed. The compiler
phase still has at most 90 seconds, the pipeline 180 seconds and the macOS job
five minutes. The selected byte cap is recorded in each subprocess result.
Even a completed process exceeding the cap is rejected as a capped result.
Tests cover invalid caps before process creation, process-group termination,
completed-process overshoot and phase-specific limits. All 239 Python tests pass.

Run 40215492662 at 3a287b7 completes the compiler attempt in 29.513 seconds
with exit 2, not a time/log kill. Its 9,874,309-byte raw log fits the explicit
16 MiB cap, retaining 357 LLVM bitcode files. This is the first broader
untruncated compilation census, not a completion percentage or a kernel link.
The shared NVRAM line-prefix error and clock microsecond diagnostics are absent
from this log. Many more network configuration and compiler compatibility
errors are now visible; previous partial counts cannot be compared as a
regression. Header export, configuration and reviewed IIG checks pass.

The next local batch selects genuine upstream networking/VFS dependencies as
recorded in MASTER_CONFIG.md. It also guards the processor KPERF timer-table
entry with the same KPERF condition as the existing enum, preserving the table
size assertion. For MIDO only, startup omits the unavailable Apple CPU-tunable
include and APPLY_TUNABLES invocation. No empty replacement macro is invented;
other platforms retain their original paths. This does not implement or audit
Cortex-A53/Qualcomm-specific errata, startup, MMU or interrupt initialization.

The shared vnode argument-offset macro now uses __builtin_offsetof on the
existing pointed-to type, retaining its int result and caller API. qsort checks
alignment through uintptr_t rather than undefined subtraction from a null
pointer. The raw log contained 144 vnode offset occurrences and one qsort
occurrence; these are addressed at their two definitions, not each caller.
The actual qsort body passes 576 native Windows cases across element sizes,
input orders, duplicates and misalignments, including buffer guards. It also
compiles for ARM64; actual vnode macro extracts pass ARM64 offset assertions.
The actual running-timer enum/table passes ARM64 C11 with KPERF both off and
on, while the extracted MIDO tunable gates exclude both Apple-only references.
Evidence: artifacts/null-arithmetic-probes-v1 and artifacts/dependency-closure-v1.

A fresh complete source/frontend preparation, 242 Python tests and 16
PowerShell mock scenarios pass. Evidence: artifacts/dependency-closure-frontend-v1.
These newest changes remain local-compiler/config evidence until the next
Apple validation. No kernel output, phone command or boot approval exists.

Run 40216034991 at 3a9db97 exercises the latest batch with Apple Clang. Header
export, configuration and reviewed IIG checks pass. Compilation completes its
attempt with exit 2 in 32.709 seconds, without a log/time kill; the raw log is
13,025,595 bytes. The report identifies 37 ARM64 Mach-O object headers and 432
LLVM bitcode files. These counts are not linked output, an instruction audit,
a runtime test or a completion percentage. The log contains no errors attributed
to start.s, processor.c, vnode_if.c or qsort.c, and the null-pointer-subtraction
category is absent. The old Skywalk/multipath missing-type cascade is replaced
by a broader view of the newly selected real implementations, including many
additional format diagnostics. Increasing format counts after selecting more
sources must not be presented as evidence of either a regression or progress.

Still-observed blockers include an unconditional disabled-KPC task-field write,
zone-log and coalition/telemetry field gates, remaining network dependencies,
and missing arm64/ppl/sart.h in pmap.c. The latter also includes uat.h and calls
Apple UAT/SART initialization. Those references require a target-specific
platform review, not invented headers or empty-success implementations. The
matching firehose implementation/archive, successful linking, complete loader
and memory/Apple-DT contracts, hardware IRQ integration and instruction audit
remain outstanding. No image exists that is approved for a phone boot.

Two new cloud jobs were actually dispatched in this continuation, not one job
per repair. Their timing API reports 71 and 74 seconds respectively; these are
elapsed runtimes, not included-allowance deductions. Each retained the five-minute
job bound and the 50-minute allowance planning reserve. Failed API/DNS requests
were checked against the run list before retries. No paid settings or device
commands were used.

### Platform and optional-network guard follow-up

The next hash-pinned frontend batch gates the task KPC initializer with the
same KPC condition as its field, and the bank resource-coalition accesses with
the same COALITIONS-and-TELEMETRY condition as their field. It corrects the
ZONE_ENABLE_LOGGING typo to the genuinely defined ZALLOC_ENABLE_LOGGING in
the zone header and implementation, preserving the existing DEBUG/DEVELOPMENT
and KASAN policy instead of disabling logging or inventing fields.

Only for MIDO, the pmap frontend excludes the two Apple UAT/SART includes and
their two bootstrap calls. Generic pmap initialization is unchanged, as are
non-MIDO references. This is NOT a Qualcomm SMMU implementation, DMA isolation
or proof that pmap compiles or boots. DMA-capable device bring-up remains
blocked until actual platform ownership and protection are implemented.

Three additional network repairs match existing field/operation conditions:
the PCB socket-export CFIL flag is conditional on CONTENT_FILTER; UDP's
skipit local follows its actual NECP users rather than the unrelated IPSEC
flag; raw connected sockets use the PCB peer address when CONTENT_FILTER is
absent and retain the original saved-destination expression when enabled.
No optional subsystem is enabled by these changes.

Local validation passes 251 Python tests, 16 PowerShell mock scenarios and
fresh complete pinned source/frontend staging. Twenty-four ARM64 checks on
actual source extracts cover KPC on/off, all coalition/telemetry pairs,
DEBUG/DEVELOPMENT/KASAN combinations, MIDO/non-MIDO Apple-reference exclusion,
CONTENT_FILTER on/off and independent NECP/IPSEC combinations. These checks
are not whole-translation-unit compilation or runtime evidence. Local evidence:
artifacts/platform-network-frontend-v1 and
artifacts/platform-gates-frontend-v1/probe-report.json. No phone commands or
boot approval result from these local checks.

Apple validation run 40217379538 at 0f81731 confirms header export,
configuration and the reviewed IIG checks pass. The compile attempt finishes
with exit 2 in 32.616 seconds, without a log/time kill; the raw log contains
13,059,310 bytes. It reports 37 ARM64 Mach-O object headers and 433 LLVM
bitcode files, not a linked kernel. The previous t_kpc, z_btlog,
bt_rsrc_coal_id, so_cfil, IPv4 UDP skipit and raw IPv4 filter-local errors
are absent. Other format/switch diagnostics still prevent compilation of
several touched translation units; disappearance of selected errors is not
evidence that those entire units compile.

Opening the pmap translation unit exposes unresolved ptep_get_iommu,
pmap_ppl_lockdown_pages and pmap_ppl_unlockdown_pages calls. Their definitions
are not present in the staged pinned source tree. pmap_phys_write_disable
has a genuine later definition but lacks a visible declaration at its call.
These are not fixed by the Apple DMA include exclusion. Do not insert empty
protection helpers, disable memory protection, or claim a bootable pmap.
Remaining network dependencies include IPv6 IPSEC/NECP guards and IPV6_MMTU;
the matching firehose archive, linking and hardware contracts remain open.

Exactly one new cloud job was dispatched for this batch. GitHub reports a
70-second job duration; this is not a verified allowance deduction. The
five-minute cap and 50-minute allowance reserve were retained. The initial
push failed DNS before dispatch, then succeeded on retry; there was no
duplicate cloud run. No phone access occurred. Evidence:
artifacts/cloud-kernel-attempt-40217379538/mido-build-diagnostics.

### pmap visibility and IPv6 policy follow-up

The next pinned frontend transformation adds a declaration for the existing
pmap_phys_write_disable definition before its earlier caller. Its original
implementation remains unchanged: non-monitor targets call pmap_page_protect
with VM_PROT_READ; monitor targets call pmap_ppl_lockdown_page. Actual extracted
ARM64 LLVM IR retains the respective protection calls in both configurations.

The two code-signing range wrappers are now compiled under the union of their
actual callers' conditions, PMAP_CS_PPL_MONITOR or PMAP_CS_INCLUDE_CODE_SIGNING.
Neither is enabled by the MIDO scaffold. This removes unused wrappers, not a
live protection path, and does not implement their missing dependencies.
Three enabled-feature extract cases deliberately fail on the absent range
implementation, verifying that enabling code signing still fails closed.

For MIDO only, the two IOMMU panic diagnostics identify the opaque tagged PTE
pointer as an "iommu ptep" instead of calling the unavailable Apple decoder.
Both panic sites, their conditions and subsequent mapping logic remain intact.
Other targets retain the original decoder and original diagnostics. This is a
diagnostic-only change, not IOMMU support or a DMA protection implementation.

IPv6 UDP now declares skipit under NECP, like its actual users. Raw IPv6 source
and destination scope locals are outside CONTENT_FILTER because unfiltered
packets also require scope selection. IPv4/IPv6 skip_ipsec labels are available
under IPSEC or NECP; their original location after IPsec processing is retained.
The IPv6 packet-chain reset touches ipsec_state only when that field exists,
without changing the always-required extension-header reset. IPv4 output
directly includes netinet/ip6.h, the real owner of IPV6_MMTU, rather than relying
on an incidental IPsec include or redefining the MTU constant.

Local validation passes 257 Python tests and fresh pinned source/frontend
preparation. The preceding 24 ARM64 gate checks pass on the new staged tree.
An additional 24 extracted-source checks cover pmap visibility/protection IR,
disabled and enabled code-signing gates (including three expected dependency
failures), both diagnostic branches, all IPSEC/NECP label combinations, state
reset and IPv6 scope/UDP conditions. These are not whole-file compilation,
linked-kernel evidence or boot approval. Evidence: artifacts/pmap-policy-frontend-v1.

Apple validation run 40217929861 at ce1dc95 passes header export,
configuration and reviewed IIG checks. The compile attempt exits 2 in 33.372
seconds, with no log/time kill; the raw log is 13,051,136 bytes. It reports
37 ARM64 Mach-O object headers and 433 bitcode files, not a linked kernel.
The four previously reported pmap undeclared-function diagnostics and the
IPV6_MMTU, skip_ipsec, ipsec_state, IPv6 scope and UDP skipit diagnostics are
absent. Other diagnostics still prevent whole-file compilation. In particular,
IPv4 input exposes incomplete ip_fw_args/ip_fw_in_args types; this was not
captured by the narrower earlier undeclared-identifier search. Interleaved
parallel logs must not be treated as a complete dependency classification.

The subsequent LOCAL follow-up directly includes netinet/ip_flowid.h in
ip_input.c. That genuine header owns both structures under BSD_KERNEL_PRIVATE;
the previous incidental include came through optional DUMMYNET. This does not
enable DUMMYNET/PF, invent fields, or change packet processing. The owner-header
definitions and actual input copy helpers compile for ARM64 with DUMMYNET off
and on, preserving 56-byte flow IDs, 160-byte full arguments and 8-byte input
arguments in the test ABI. A fresh complete frontend and 258 Python tests pass.
Evidence: artifacts/pmap-policy-flow-frontend-v1. This last include repair is
not yet Apple-compiler validated; no second cloud job was dispatched for it.

Exactly one new cloud job was dispatched in this continuation, with a
71-second reported job duration, not a verified allowance deduction. The
five-minute cap and 50-minute allowance reserve are unchanged. An artifact
download failed network access and succeeded on retry without rerunning CI.
The retained log still has substantial format, switch/default, unused-variable
and other strict-compiler diagnostics. NECP trace macros repeatedly format the
same argument as signed decimal and unsigned hexadecimal, amplifying several
diagnostics through logging expansion; these require type/width review rather
than blanket warning suppression. Linking, genuine firehose dependencies and
hardware contracts remain open. No phone commands or boot approval occurred.

### Quota hold: batched local diagnostic repairs

The user reports 444 included Actions minutes consumed and requests local
batching before another combined cloud validation. No Actions job was
dispatched for this follow-up. Do not confuse local compiler/model results
with an Apple build result or infer any remaining account balance from runner
timing. All repository workflows currently require workflow_dispatch.

Six hash-pinned NECP trace macros now match their known uint32 policy/order,
application and interface fields with unsigned decimal formats. Protocols,
ports and pid_t retain their appropriate promoted signed formats. Generic
policy IDs receive checked unsigned conversion so literal zero and genuine
uint32 IDs both match. The condition trace's intentional signed-decimal and
unsigned-hexadecimal pairs now use explicit int/unsigned-int arguments, keeping
their original 32-bit interpretation. Compile-time integer/width checks reject
wide or non-integer inputs rather than silently narrowing them. Logging guards,
policy decisions, call counts and argument evaluation multiplicity are unchanged.

Two additional pinned roots preserve numeric ABI checks for Skywalk's 27
region and three arena enum mappings. Explicit int conversions compare their
numeric identifiers without comparing distinct enum types; none of the
assertions is removed. Actual enum definitions establish every compared
constant fits a nonnegative int, and individually breaking each of the 30
equalities still fails compilation.

The SMR bucket selector now panics on an invalid selector rather than using
uninitialized array/shift locals. Both valid cases and the actual array-load
implementation remain unchanged; this is not a no-op default or a claim that
SMR synchronization was validated. CoreAnalytics queue initialization checks
the real result and panics on thread-creation failure, matching the neighboring
kernel daemon initialization pattern instead of dropping an unused result.
Both panic users directly include the genuine kern/debug.h declaration.

Validation passes 269 Python tests, 16 PowerShell mock scenarios and a fresh
complete pinned source/frontend preparation. Actual trace macro extracts pass
ARM64 format and explicit argument-type checks using genuine field declarations;
wide/float/pointer cases are rejected. Native trace models preserve boundary
bit patterns (including 0x80000000 and 0xffffffff), disabled-log behavior and
the original two evaluations of a condition argument. Additional local tests
cover all 30 ABI equalities and their individual mismatch rejections, 256 valid
SMR selector/index cases and four mocked analytics queue results. The SMR
model mocks array lookup and the analytics model mocks queue/panic behavior;
neither proves hardware ordering, thread execution or actual kernel panic.

Evidence: artifacts/trace-batch-frontend-v1 and artifacts/trace-core-batch-v1.
No new Apple validation, linked kernel, handset command or boot approval exists.
The retained cloud log still contains other format, switch, unused-variable,
enum and strict-compiler failures; these changes must not be presented as
resolving every diagnostic or as a measured reduction before cloud validation.

### Continued quota hold: network types

No Actions workflow is dispatched for this batch. Five additional source-hash
profiles run after existing network/platform/trace/core transformations and
validate every input before writing any output in the new stage:

- The filter event callback now takes the genuine fixed-underlying-uint32_t
  net_filter_event_subsystems enum required by its callback typedef; its body,
  log format and event registration remain unchanged. No function-pointer cast
  hides a signature mismatch.
- Five no-argument cuckoo test helper definitions use explicit (void)
  prototypes, including all three callbacks passed to the concurrent test
  runner. Their bodies and callback invocation sequence remain unchanged.
- esp.h declares the genuine opaque ipsecrequest tag at file scope, beside
  secasvar, so the esp_hdrsiz parameter does not create a distinct scoped tag
  when the full IPsec implementation is not included. No IPsec code is enabled.
- Only the local ipobf/ip6obf one-bit flag fields change from signed boolean_t
  to unsigned int. TRUE now reads back as 1, not -1. Reviewed users test truth
  or assign boolean results; no consumer depends on sign extension. Field
  order, conditional IPsec fields, raw uint32_t member and zero initializer
  remain unchanged; global boolean_t and externally visible types are untouched.

Validation passes 275 Python tests, 16 PowerShell mock scenarios and a fresh
complete pinned frontend preparation. Evidence is under
artifacts/network-types-batch-v1, including probe.py and probe-report.json.
Nineteen extracted-source compiler/native checks cover the actual filter
callback body and typedef, all three concurrent-check callback signatures,
the ESP opaque declaration and IPv4/IPv6 local flag unions with IPSEC 0/1.
Negative mutations must reproduce the original strict diagnostics. ARM64
Apple-target syntax checks preserve four-byte flag size/alignment. CRT-free
native Windows probes exercise all 592 flag masks, preserve raw bit layout
and untouched upper bits, verify zero reset and compare old/new truth values.
Filter logging/UUID dependencies are declaration scaffolding; cuckoo bodies
are not executed. Native flag execution is not ARM64 execution, and none of
these probes validates full translation units, synchronization or networking.

The existing warning policy, build timeout and Actions quota settings are
unchanged. No handset access, linked kernel, boot image or boot approval is
produced. Other compiler failures and the genuine firehose library/linker and
hardware integration blockers remain; another full Apple build is deferred
until a larger locally reviewed batch is ready.

### Continued quota hold: aggregate defaults and optional state

Another local-only batch adds 13 source-hash profiles after network type
repairs. All inputs in this stage are validated before any of its writes.
No Actions job or handset command is executed.

Four existing aggregate initialization sites now explicitly spell out their
previous implicit zero defaults: OSSerialize's kmem guard, SMR domain per-CPU
pointer/early state, the SMR hash traits zero-length type array and the hash
iterator's prev/link pointers. Genuine upstream structures, field order,
startup hooks, callback traits and iterator operations are unchanged. The
zero-length array initializer does not allocate storage or add a field.

Optional state now follows the actual consumers' compile-time conditions:
lastReadLength uses CRYPTO; Mach-O spawn state uses CONFIG_CODE_DECRYPTION;
UART device-tree locals require one of the four existing UART implementations;
IPv4 dummynet and IPv6 routing-header locals use DUMMYNET/IPSEC; the linkat
parent vnode uses CONFIG_FSE. The socket shutdown done label, IPv4 input pass
label and IPv6 forwarding sent label use CONTENT_FILTER/IPSEC/PF, respectively.
Only labels are gated, not their fallthrough code. Debug traffic-rule refcount
snapshots require CONFIG_DTRACE as well as DEVELOPMENT/DEBUG, matching the
genuine DTRACE_SKYWALK2 macro's consumer. Without tracing, the unused snapshot
read is omitted; reference retain/release and zero-count destruction remain
unconditional. No cryptography, code-signing, packet filtering or reference
operation is replaced with a success stub.

Validation: 282 Python tests, 16 PowerShell mock scenarios and a fresh complete
pinned frontend pass. artifacts/optional-defaults-batch-v3 contains the source,
frontend report, probe.py and a 91-case compiler/native/preprocessor report.
ARM64 Apple-target C/C++ checks cover the genuine aggregate declarations and
macro/function extracts, including negative mutations reproducing the missing
initializers. CRT-free native models exercise all 65,536 guard tags and 278
iterator bucket occupancy masks in each language. All 16 UART feature masks
compile their declarations and preserve preprocessed serial_init body tokens
apart from those declarations. Optional local/label variants, both real
soshutdownlock branches and all eight development/debug/DTrace combinations
also pass; reference mutation, destructor and snapshot behavior are checked.

Dependency scaffolding mocks tag lookup, startup registration, iterator decode
and SMR loads, socket/filter callbacks and reference-count primitives. These
checks do not prove actual startup, reclamation ordering, networking or driver
operation. ARM64 compilation checks LP64 layouts; native Windows execution
does not establish ARM64 runtime behavior. Probes retain the upstream existing
nonfatal C99-designator warning policy; production warning flags are unchanged.

This targets the retained log's four missing aggregate initializer sites,
ten unused locals and three unused labels. It is not a measured new Apple
build result or a claim that all remaining compiler errors are fixed. Other
strict diagnostics, genuine firehose library construction, final linking,
boot argument/memory/interrupt integration and hardware validation remain.
There is still no linked kernel, boot image or boot approval.

### Continued quota hold: integer cookies and numeric signatures

Eleven more hash-pinned profiles run after optional-default repairs, validating
all inputs in this stage before writing. No Actions workflow or handset
command runs. Fifteen reviewed integer-cookie decodes now explicitly pass
through uintptr_t: perfcontrol/timer/performance-level sysctls, seven mbuf
allocator callbacks, timer flavor, queue event, IPv6 fragment context and two
ledger notification callbacks. Their producers encode small integer IDs or
int values in opaque pointer parameters; no pointed-to object is accessed.
The original destination enum/int conversion and validation stay in place.
This is not a general license to truncate real kernel or user addresses.

The backtrace page-number sentinel is numeric zero at its three existing
initialization/comparison sites instead of a pointer-valued NULL cast. The
SHMC, BTRC and NVV3 signatures use explicit uint32-compatible numeric constants
equal to their original Clang character constants; no byte-order conversion
or serialized format changes. Real pointer casts in caches, address logging
and 32-bit signal handling remain separate review items, not hidden by a
generic double-cast transformation.

Validation passes 288 Python tests, 16 PowerShell mock scenarios and a fresh
complete pinned frontend. Evidence: artifacts/scalar-cookies-batch-v1, including
probe.py, frontend-report.json and a 31-case compiler/native report. ARM64
Apple-target probes use genuine enum definitions and extracted decode
expressions, all three IPv6 context helpers and both ledger callback bodies.
Negative cases reproduce the original narrow-pointer and character-constant
diagnostics. Original/new signature values compare equal at compile time.
CRT-free native probes round-trip valid enum IDs and signed 32-bit boundary
patterns, scrub fragment context and check ledger warning/notification flow.
The mbuf packet-header container and ledger notification sinks are mocked;
these checks do not validate networking, allocator behavior or resource
monitoring. Arbitrary pointer values and ARM64 runtime behavior are not proven.

Production warnings and cloud limits remain unchanged. This is another local
batch, not a new full Apple build result. Other compiler errors, genuine
firehose library construction/linking and platform memory/boot/interrupt
integration remain; no linked kernel, boot image or boot approval is produced.

### Same local batch: packet class ABI

Three further profiles preserve 34 pbufpool numeric service/traffic-class
equalities using explicit int comparisons between the separate enum namespaces.
Both constants and every equality remain present; the -1 internal sentinels
are preserved. The other packet flags, offsets and class-value assertions are
untouched. Two service-class exports to statistics structures explicitly cast
to their actual packet_svc_class_t destination type. The netif KPKT_VALID_SVC
check and both exporters' other operations stay unchanged.

All 294 Python tests and a fresh complete pinned frontend pass. Evidence is
under artifacts/packet-classes-batch-v1. Its 42-case local compiler/native
report extracts all six genuine enum definitions and verifies every constant
fits int before comparing numeric values. All 34 individual equality mutations
must fail compilation; the original enum comparison/conversion diagnostics
are reproduced by negative tests. Native export probes preserve all eleven
public service classes and the unspecified sentinel; netif continues rejecting
that sentinel without modifying the destination field. The surrounding flow,
queue and statistics containers are field-only mocks, not actual flow/driver
execution or layout validation. The combined local work adds no cloud job,
device access, warning relaxation, kernel link result or boot approval.
