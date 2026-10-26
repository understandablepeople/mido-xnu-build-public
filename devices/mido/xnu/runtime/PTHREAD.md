# Diagnostic native pthread provider

The CPU lifecycle correction in native Action 40336475616 removes the observed
mcache_init sleep: offline v25 records ml_set_max_cpus(1), two original
ml_wait_max_cpus returns of one, mbinit, eventhandler_init and aio_init. It then
hits the original panic that the pthread kernel extension function table is
NULL. No root filesystem or device boot has been reached.

The optional --experimental-pthread build stages the real open kernel
implementation from libpthread-514.100.2, commit
a6c70ca0e544347a0377babf748f831577ec24f9. Apple's distribution-macOS
rel/macOS-13 tree pairs this commit with our exact xnu-8796.141.3 commit
1b191cb58250d0705d8a51287127505aa4bc0789. The downloaded archive is bounded,
hash-checked and inspected before any files are staged. Original license
notices remain in the upstream files; no external source is vendored here.
The audited distribution tree is 1103a82bbc0ce0def4c198db70251c29c27b2040.

All three original kernel units are compiled only for mido_runtime. Their
private pthread_kern callback pointer and current_uthread helper are namespaced
per object to avoid colliding with the kernel's independent shim symbols.
The native pthread_start registration runs at THREAD_CALL/LAST; the original
BSD pthread_init still initializes its real synchronization subsystem later.
There are no fake function tables or successful no-op synchronization hooks.

The three external units use kext-visible header conditions, not the raw BSD
internal uthread/workqueue structures. The separate native registration/KPI
adapter retains full kernel headers. Its directed-thread conversion calls the
real two-argument port_name_to_thread and requires the current task. Reviewed,
count-checked staging corrections parenthesize the redundant panic declaration,
use integer zero for user_addr_t null addresses, and explicitly cast the
unslide input to vm_offset_t. Original and staged hashes are recorded for
changed dependency files. No compiler type error is globally disabled.

This experiment requires the explicit diagnostic platform option. Its manual
workflow approval defaults to false. Native compilation, pointer-table ABI and
offline execution must be verified before claiming that this provider works.
Even successful offline registration is not userspace or hardware validation.

## Verified build and execution

Action 40343852734 at 67ce37f compiles and links all three real units and the
native adapter. The kernel SHA-256 is
e5fd32774a153c41277ed422bf93e2249409735361cbd01978c3363c49a1d289.
All 42 staged pthread source/header hashes match the local staging result.

The v27 trace observes native table registration and the real _pthread_init,
then progresses through network initialization. It stops on Unicorn's absent
architectural delivery of a demand-page store translation fault, not a pthread
panic. A read-only v28 table walk proves a missing L2 descriptor at the exact
STR W9,[X8]; Unicorn leaves ESR_EL1 and FAR_EL1 zero instead of entering VBAR.

The bounded synchronous-exception model accepts only aligned STR W operations
with a proven missing original upper-address descriptor in EL1t. It supplies
architectural exception-entry registers and enters the original synchronous
vector, without changing page tables or forcing a function return. A minimal
ARM64 machine-code test maps the page in its handler, ERETs and retries the
original store successfully. Unknown exception kinds remain errors.

The v29 root-discovery trace then passes: real VFS return, pthread, network,
Skywalk, memorystatus and sysctl complete far enough to enter IOFindBSDRoot.
One modeled synchronous data abort is delivered. Execution inputs remain
hash-identical. This is entry to root discovery, not a storage service,
mounted root filesystem, userspace or device boot. The image remains do-not-flash.

The frozen v29 offline ZIP contains 212 members and 30845406 bytes; SHA-256 is
f34a756452f35b14f16c6c7074cbe6861842785cc038046833b2b8923e30174b.
ZIP CRC and every manifest member hash are verified. Independent extraction
and execution from the packaged source snapshots reproduces the complete case
object identically, with completed=true and unchanged execution inputs.
The successful image and report are under artifacts/mido-xnu-pthread-fault-v29;
the archive is artifacts/mido-xnu-pthread-fault-v29-offline.zip.
