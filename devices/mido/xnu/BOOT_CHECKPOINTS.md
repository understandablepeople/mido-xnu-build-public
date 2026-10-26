# Opt-in pre-MMU XNU entry checkpoints

The successful carrier photograph proves the ARM64 diagnostic reached EL1,
read its embedded kernel structure and drew the blocked-handoff status. It
does not prove entry into XNU. The code here prepares the next diagnostic
kernel, without authorizing or executing another handset boot.

tools/check_xnu_build.py accepts --experimental-boot-checkpoints only with
the explicit experimental bootstrap-crypto kernel build. The manual bootstrap
workflow exposes approve_boot_checkpoints, default false. Nothing is enabled
for ordinary builds. This option requires a new macOS kernel build; the old
v10 kernel does not contain these marks.

The staging helper accepts only the reviewed prepared start.s hash and adds
MIDO-guarded markers without removing upstream startup instructions:

- At start_first_cpu: white 64-by-16 rectangle, column 60, row 560. This
  proves execution reached the original cold-start routine.
- Immediately after the boot-argument memory parameter loads: second white
  rectangle, column 60, row 584. This proves those loads completed, not that
  all boot arguments are semantically valid or that MMU initialization passed.

The macro uses the observed framebuffer base 0x90001000, RGB888, stride 3240.
It is exclusively pre-MMU and requires the retained framebuffer mapping and
ownership contract. It uses no stack, function call, allocation or Apple-only
register. Scratch registers x9-x12 and NZCV are clobbered; the cold-entry ABI
consumes x0 only. Boot arguments, SP, LR and x20-x26 remain untouched.
The low-level test executes actual ARMv8-A instructions and checks every
framebuffer byte, preserved register and the unchanged code region.

    python -X utf8 -m unittest tests.test_stage_mido_boot_checkpoints tests.test_mido_boot_checkpoint_machine_code

The standalone macro tests do not replace rebuilding and executing the full
instrumented kernel in the offline handoff/MMU harness. That harness recognizes
the new checkpoint symbol instead of assuming the original instruction offset.
No post-MMU framebuffer access is added: the physical framebuffer address
must not be reused after MMU activation without an explicit device mapping.
Hardware memory ownership and separate permission for XNU execution remain gates.
