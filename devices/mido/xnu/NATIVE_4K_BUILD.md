# Native 4-KiB build checkpoint

2026-10-30: GitHub run 41094338254 completed successfully on macos-15 with
Xcode 16.4, source commit b6e0896060abd7529bf4c5af07dd092961de7088.

The source-staging regressions, actual header export, compilation and linking
passed. build-report.json records kernel_built=true, pipeline_passed=true,
and an empty blockers array. This is compilation evidence, NOT boot approval.

- Artifact: mach.development.mido, 15,287,608 bytes.
- SHA-256: cc775278d62f492d424ae998663bdb370c909203f3fd69c9a66c2961cdce32f3.
- Native page-policy candidate: seven hash-pinned source files plus MIDO flags.
- Bootstrap pool: sixteen pages, full clearing, checked L2 allocation boundary.
- Original Apple compiler checks were retained; no Linux allocator workaround.

This build enabled bootstrap crypto and the existing non-Apple startup option.
IRQ/timer, framebuffer checkpoints, platform expert, pthread, memory-root, mockfs
and entitlement diagnostics were NOT enabled. It must not replace the previous
hardware diagnostic image without rebuilding the required providers and auditing
the new binary's addresses, bootstrap instructions and memory placement.

The checkpoint stager accepts the exact reviewed native-4K startup hash as well
as the baseline hash; it does not accept arbitrary modified startup source.
Its combined staging regression suite has 23 passing tests.

Still unverified: hardware execution of this binary, full VM/scheduler startup,
16-KiB code signatures on 4-KiB VM, dyld shared cache and actual Apple userspace.
No phone partition was written and no RAM boot was attempted for this build.
