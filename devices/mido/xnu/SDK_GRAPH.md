# Full source and first real SDK/make-graph probe

Status: complete source preparation passes locally on Windows and macOS.
The first authorized macOS SDK/full-make diagnostic ran on October 25,
2026, at commit 1d1f96b8dc1ccfc7c1599015ebe24c28a37eee51. SDK discovery
passed, but the make dry-run failed during directory bootstrap.
No XNU kernel has been compiled. The initial directory correction was
published as 4c6f611 and tested in a second authorized run; it passed the
first directory barrier but did not solve recursive dry-run bootstrapping.

## Source preparation

tools/prepare_xnu_tree.py retrieves the complete archive for Apple source
commit 1b191cb58250d0705d8a51287127505aa4bc0789, not a mutable branch.
It requires a fixed archive SHA-256 before unpacking, rejects links, special
entries, traversal, case collisions and size/count excesses, and checks the
three original architecture-patch inputs against their existing hashes.
It then applies the reviewed architecture patch and installs our current
MASTER.arm64.mido into this new tree only. No original reference checkout,
git history, phone data or partition is modified.

    python tools/prepare_xnu_tree.py --archive artifacts/xnu-source-download-v1/xnu.tar.gz --output-directory artifacts/NEW_DIRECTORY

Omit --archive to download from the official GitHub codeload endpoint.
The fixed archive hash was observed on that canonical download; it is not
an independently published Apple signature. A changed archive fails closed.

Local evidence: artifacts/xnu-full-tree-v1/source-report.json records
5,330 archive entries, 14,712,443 compressed bytes and 70,440,341 expanded
bytes. The complete source is at artifacts/xnu-full-tree-v1/source, with the
MIDO architecture patch applied and the master at config/MASTER.arm64.mido.

## Actual macOS-only probe

tools/check_xnu_build_graph.py refuses to emulate SDK discovery on Windows.
On real macOS it prepares a fresh tree, queries xcrun for an explicit SDK
path/version and clang, clang++, mig, migcom, iig and unifdef, then invokes
the original top-level Makefile for the explicit target tuple
DEVELOPMENT ARM64 MIDO. It uses --just-print, one make job and separate
artifact-only object/symbol/destination paths.

    python3 tools/check_xnu_build_graph.py --sdk iphoneos --output-directory artifacts/NEW_DIRECTORY

The sdk parameter accepts only iphoneos or macosx. These are diagnostic
selections, not an approved memory map or kernel platform. The actual
MakeInc.cmd and top-level recursion are used, unlike the earlier two-include
probe. No SDK paths, target compilers or build flags are filled with stubs.
Only a small OS/toolchain environment allowlist reaches xcrun/make; inherited
tokens and build-control overrides are not forwarded.

GNU make --just-print is NOT a no-execution sandbox: recursive make recipes
and parse-time shell functions can run. This probe therefore permits host
side effects in the isolated tree/build paths. It does not deliberately
request kernel compilation or linking, and neither SDK availability nor a
successful dry-run proves that the kernel compiles. Missing generated
prerequisites may stop a dry-run before later dependency problems are seen.

The make process has a 90-second process-group timeout and a monitored
4-MiB log threshold. build-graph-report.json records missing tools, SDK
results and make status; boot_approved and kernel_built stay false even if
graph_passed is true. Timeouts and absent SDKs/tools are not green results.

## Manual CI gate

.github/workflows/macos-build-graph.yml is a manual-only workflow. It
has a false-by-default quota acknowledgement, read-only contents access,
credential-free pinned checkout, macos-15 standard label and five-minute
job timeout. It installs no SDKs or third-party packages, performs no auto
retry and uploads no backups, phone dumps or binaries. Reports are printed
to the private job log. No push/schedule trigger is present.

Before publishing changes or dispatching again, obtain explicit approval for the new
commit/push and exactly one run, and confirm that the included Actions
allowance remains available. A timeout is not a financial spending cap.
No billing settings or overages are changed by this work.

## First real macOS result and local follow-up

Run 40200196198 was the only dispatched run for commit 1d1f96b. It used
Xcode 16.4 and found the iPhoneOS 18.5 SDK plus all six required tools,
including migcom and iig. The pinned source archive and patch preparation
succeeded, and all 112 then-current Python tests passed on the runner.

The job failed after about 19 seconds of job time (22 seconds overall).
The make process returned 2 after 7.169 seconds. MakeInc.top prints its
mkdir recipe under --just-print but executes the recursive make -C recipe;
the DEVELOPMENT_ARM64_MIDO/.. path therefore did not exist. This is a
dry-run bootstrap failure, not an observed compiler or SDK incompatibility.
Later generated prerequisites and actual compilation remain untested.

The local correction creates empty obj/DEVELOPMENT_ARM64_MIDO, sym and
dst directories within the isolated artifact build tree before make.
It creates no fake headers, generated sources or binaries. All 113 local
Python tests pass, including a new directory-bootstrap regression; this
mocked test does not prove that the corrected graph passes on macOS.

Evidence is saved under artifacts/cloud-build-graph-40200196198:
run.json, run.log, timing.json and build-graph-report.json. No phone was
accessed. No second run, billing changes or paid overages were requested.
The user reported 31 of 2,000 included Actions minutes used before this run;
the post-run allowance has not been independently verified.

## Second authorized run: recursive dry-run limitation

Run 40200396134 tested commit 4c6f611bdedeaea556a7f09e875cc15076ffe101
on October 25, 2026. This was exactly one new run after explicit approval,
not an automatic retry. All 113 Python tests passed on macOS; iPhoneOS
18.5 and all six tools were again found, and source preparation succeeded.

The first make -C into DEVELOPMENT_ARM64_MIDO/.. succeeded. Nested make
then failed on absent obj/SETUP, obj/san and obj/bsd directories. Make
returned 2 after 8.122 seconds; the run took 23 seconds overall. No kernel
compilation or link was requested, and graph_passed remains false.

The initial correction is insufficient: creating only the top-level
directories does not handle the mkdir/recursive-make pattern throughout
MakeInc.dir. Do not spend another run merely adding these three paths.
SETUP/Makefile recursively builds actual host tools (including config),
and MakeInc.dir also has separate configuration and compilation phases.
A useful follow-up must review and explicitly prepare the real setup and
generated-prerequisite phases, or implement a tested general directory-only
preparation strategy while still reporting missing generated files honestly.
Neither approach has been implemented or authorized for a new cloud run.

Evidence is saved under artifacts/cloud-build-graph-40200396134:
run.json, run.log, timing.json and build-graph-report.json. The source and
runner are unchanged after this run; this evidence update remains local.
No additional commit, push, CI dispatch, billing changes or phone actions
were performed after collecting this result.
