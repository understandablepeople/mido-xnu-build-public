# Real host setup, not another cold-tree dry-run

Status: commit a55c8a0 passed real macOS host setup in run 40204223224.
All 140 Python tests passed, six native host programs were compiled,
linked and ad-hoc signed, and all twelve setup outputs passed inspection.
The pinned open-source availability dependency removed the earlier
missing-resource blocker. No XNU kernel has been compiled or run.
SDK_GRAPH.md records the two earlier cold-tree graph attempts.

## Reviewed upstream scope

The pinned top-level Makefile exposes setup independently of all/build.
MakeInc.top maps it to build_setup_bootstrap and timestamp updates.
The root SETUP_SUBDIRS are SETUP, san and bsd; MakeInc.dir creates their
directories before recursive make in a real (non-dry) setup run.

SETUP/Makefile builds six host programs: config, kextsymboltool, setsegname,
decomment, installfile and replacecontents. Their recipes compile, link
and ad-hoc sign executables for the Mac host. The san setup generates four
blacklist files and validates source paths. The bsd/sys setup generates
_posix_availability.h and _symbol_aliasing.h. This is actual host-side
execution, not a no-op or a simulation; it does not request kernel all,
build, config, install or boot targets.

The symbol-aliasing script requires an executable SDK resource at
usr/local/libexec/availability.pl. Finding clang and iig alone does not
prove that this resource exists. Run 40200866542 confirmed its absence in
the hosted iPhoneOS 18.5 SDK. Do not substitute an empty script, generated header,
fake SDK or default-success tool if the check fails.

## Tool behavior

tools/check_xnu_setup.py requires real macOS before preparing the full
hash-pinned source tree in a new artifact directory. It audits both the
explicit target SDK and macosx host SDK, discovers host clang, flex, bison,
gm4 and codesign_allocate, and checks codesign and availability.pl.
SDK discovery timeouts become reportable failures, not green results.

Without --execute-setup, only source preparation and prerequisite audit
are performed; setup_passed remains false. With that explicit option and
all prerequisites available, the tool invokes the original setup target
without --just-print. MAKEJOBS=--jobs=1 and -j1 keep upstream recursive
make serial. Without --open-availability no source recipe is patched;
SDK content is never patched in either mode.

    python3 tools/check_xnu_setup.py --sdk iphoneos --output-directory artifacts/NEW_AUDIT
    python3 tools/check_xnu_setup.py --sdk iphoneos --execute-setup --output-directory artifacts/NEW_SETUP

Each command needs its own new artifact directory. Source download,
patching and extraction are the same bounded operations as SDK_GRAPH.md.
The setup make process uses the existing 90-second process-group timeout
and monitored 4-MiB log threshold. Its last 120 log lines and JSON report
are printed. A prerequisite failure prevents actual compilation.

setup_passed requires successful make completion without a timeout plus
all twelve nonempty outputs. Before an explicitly requested setup, the
availability script must actually emit validated iOS/macOS version lists;
this catches missing Perl/interpreter modules before any host compilation.
The generated BSD headers must contain the expected POSIX and version-alias
macros, not just boilerplate from a silently failed command substitution.
Host programs additionally need an executable
file mode and an ARM64/x86_64 Mach-O executable header. Output size/hash
records are evidence, not cryptographic authentication or a full Mach-O
validation. Synthetic fixtures in unit tests are not real compiled tools.

Even successful setup leaves graph_passed, kernel_built, boot_approved and
platform_memory_approved false. It does not export all kernel headers,
run the full kernel configuration stage, compile/link kernel objects or
repair the known all-target cold-tree dry-run. Those are separate gates.

## Cloud gate

.github/workflows/macos-setup.yml is manual-only and requires both
approve_quota_use and approve_host_setup; both default to false. The
five-minute macos-15 job has read-only repository access and credential-free
pinned checkout. It runs tests, then exactly the setup command, printing
the report even after failure. It installs no dependencies, retries nothing
and uploads no phone data or binaries. It shares the graph concurrency
group so these experiments do not overlap.

Publishing and dispatching require explicit user authorization and a
review of included quota. A five-minute timeout is not a financial cap.
Never enable overages or change billing settings to run this stage.

## Observed macOS result

Run 40200866542 used commit cd9ee3d399f5dfc78a37020ce0b54c4916f38ae9
on October 25, 2026. Both SDKs, all five host tools and codesign were
available. The only reported blocker was the absent executable
iPhoneOS18.5.sdk/usr/local/libexec/availability.pl. The run took about
15 seconds overall, and the real make command was not started.
Evidence is under artifacts/cloud-host-setup-40200866542, including
run.json, run.log, timing.json and setup-report.json. No automatic retry,
phone access or billing changes were performed.

## Optional original Apple dependency, not a fake SDK

Apple's AvailabilityVersions-121 repository contains the original
availability.pl used to emit OS-version lists. The candidate is pinned to
commit f3b52ca75ee842a8ac593bd7b03f9f4768c15755 and SHA-256
10f764f1a7b9d56626fae0499b893fb05f25e302c6ea68f1ce3d6654c6fe1de1.
The public import commit is dated August 14, 2023, as is our XNU import;
that correspondence alone is not a guarantee of SDK ABI compatibility.

tools/prepare_xnu_availability.py downloads only this hash-pinned original
script, or accepts the same exact bytes via --script. It caps download
size, checks the original XNU generator hash, and applies
patches/0002-open-availability-path.patch only within the prepared source.
This changes one path-selection line: the generator accepts an explicit
MIDO_AVAILABILITY_PL override, otherwise retaining its SDK lookup and
missing-resource failure. The Apple Perl script itself is not changed.
No SDK files are copied, synthesized, patched or installed.

tools/check_xnu_setup.py --open-availability opts into this preparation
and passes the explicit path to make. The manual workflow has a matching
use_open_availability boolean, default false. Without this choice the
old missing-resource blocker remains. Executing the original Perl script
and source-tree override passed on macOS in run 40204223224.

Local non-mocked evidence: artifacts/xnu-availability-v1 has a fresh full
XNU tree, availability-report.json, ios-versions.txt, macos-versions.txt,
_symbol_aliasing.h and local-generator-report.json. Git Bash/Perl executed
the real Apple script and XNU shell generator using the override. It
produced a 697-line header containing iOS 16.6 and macOS 13.5 alias macros,
SHA-256 2d2bd7dfc69db01109682be89af531450a97222928f7ac1d793957f0bb171284.
The no-override/missing-SDK case still failed without producing a header.
This verifies that generator path only, not host compilation, SDK 18.5
compatibility or full setup by itself. The subsequent macOS result below
provides separate evidence for the real setup stage.

## Successful real setup, October 25, 2026

Commit a55c8a0127123c6f1674db6348268c3d3653cd52 passed run 40204223224
with sdk=iphoneos and use_open_availability=true. This was exactly one
new authorized run, with no CI retry. The job took about 29 seconds
(33 seconds overall); make setup returned 0 in 11.098 seconds.

Both SDK and host-tool discovery and the real Perl version-list probes
passed. The original setup recipes compiled, linked and ad-hoc signed
config, decomment, installfile, kextsymboltool, replacecontents and
setsegname. Their six native executable headers passed inspection.
All four sanitizer blacklist files and both generated BSD headers were
nonempty and passed their checks. The macOS _symbol_aliasing.h SHA-256
matches the locally generated file recorded above exactly.

The log contains upstream unused-variable and deprecated Mach-O API
warnings; no warning-suppression patches were added. setup_passed=true,
but graph_passed=false, kernel_built=false and boot_approved=false. This
does not establish full XNU compilation or target SDK ABI compatibility.

Saved evidence: artifacts/cloud-host-setup-40204223224/run.json, run.log,
timing.json and setup-report.json. The first log-download transport
attempt failed; downloading it again succeeded without rerunning CI.
No host binaries were uploaded or downloaded as artifacts, and no phone
or billing settings were accessed. This result update remains local.

The next build gate is genuine kernel header export and target
configuration using the compiled config tool, followed by component
compilation. It must run with real generated prerequisites rather than
claiming that the original cold-tree all-target dry-run is fixed.
