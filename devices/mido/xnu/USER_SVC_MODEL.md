# Diagnostic EL0 syscall evidence

The v46 offline run uses the unchanged native kernel from public Action
40374524389, SHA-256
72e7265189ed7cf3f9f4c5b45fb262f0d9d0832d25ed2397ce59fcb555f58553.
The unsigned 32 KiB root payload is unchanged from v36. This is synthetic
CPU/RAM execution, not an installed OS or a physical handset boot.

## Observed native path

Original mockfs and VFS mount the reserved md0. Original load_machfile
returns LOAD_SUCCESS, load_init_program returns, and the original kernel
ERET selects PC 0x100004000 in EL0t on the native exec thread. The native
TTBR0 mapping and all 28 code bytes match the RAM root.

The original payload executes mov x16, #20 and SVC #0x80. The pinned
Unicorn runtime reports the SVC interrupt with PC 0x100004008. The model
validates that exact boundary, instruction bytes, native EL0 mapping,
syscall number and a single-delivery budget. It then sets architectural
ELR_EL1, ESR_EL1=0x56000080, SPSR_EL1 and exception stack state and enters
VBAR_EL1+0x400. SPSR is written through the coprocessor API after PSTATE
to refresh the pinned runtime execution flags. No syscall result, kernel
function return, user register value or page table is injected.

The actual XNU getpid function is entered through native syscall dispatch,
returns status zero and writes PID 1 into its native retval pointer. The
observer records that original return on the same thread. Original kernel
ERET then selects PC 0x100004008 and EL0t. The payload moves the returned
PID into x19 and constructs 0x444f4d49 in x20. A hook before its yield at
0x100004014 verifies x0=x19=1, the marker, original native getpid return
and the matching native exception return. completed=true, fault=null and
inputs_unchanged=true.

The isolated regression executes an actual SVC, a tiny native EL1 test
vector, ERET and mapped EL0 continuation instructions. It records each
instruction boundary and verifies that delivery leaves memory and result
registers unchanged. The synthetic test vector writes its own test result;
that vector is not installed in the XNU run. Unknown SVC instructions,
wrong privilege state and mismatched return evidence fail closed.

## Evidence and limits

Local report:
artifacts/mido-xnu-user-getpid-v46/c-rtc-event-user-getpid-emulation.json

CRC/SHA-256-verified replay archive:
artifacts/mido-xnu-user-getpid-v46-offline-complete.zip
SHA-256 19a509b15969a74910861d85fe55ad1d5715091f56d911a393797100128f8037.
The archive includes the exact offline harness, helper sources, tests,
native build report, kernel, root payload and fixture. Archive integrity
verification is not an independent fresh execution of the entire replay.

The same carrier passes the conditional known-collision audit using the
saved recovery and incoming-loader DTBs, load-base 0x10080000 and DTB-base
0x13400000. These are explicit placement assumptions, not verified future
loader allocations. The audit retains unresolved dynamic reservations,
DMA/firmware ownership, loader workspaces and allocation lifetimes.

The proof is a diagnostic EL0 program performing one real native syscall.
It does not establish complete userspace, filesystem persistence, storage,
display input, SMP, live hardware IRQ delivery or an installation image.
boot_approved and device_boot_proven remain false. No phone writes or new
GitHub build were needed for this milestone.
