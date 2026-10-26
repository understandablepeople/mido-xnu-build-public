# MIDO link dependency selection

The DEVELOPMENT and DEBUG configurations select the real public implementations
from the pinned XNU tree. No ABI stubs or success-returning replacements are used.

| Selector | Sources or definitions restored |
| --- | --- |
| config_sched_multiq | osfmk/kern/sched_dualq.c: sched_dualq_dispatch |
| config_telemetry | osfmk/kern/telemetry.c: telemetry_sample_rate (data), telemetry_macf_mark_curthread |
| config_fse | bsd/vfs/vfs_fsevents.c: test_fse_access_granted |
| config_dtrace | existing osfmk/kern/thread.c: thread_get_kernel_stack |
| config_xnupost | osfmk/vm/vm_tests.c: vm_tests_in_progress (data), plus public self-tests |
| iotracking | existing iokit/Kernel/IOKitDebug.cpp: zone_leaks_scan |
| mach_kdp, kdp_interactive_debugging | public KDP protocol, ARM machine support, transport and core dump sources |
| ipsec | bsd/netkey and bsd/netinet6 IPsec implementations; also enables CRYPTO and IPSEC_ESP |
| pf | bsd/net/pf_pbuf.c: packet-buffer helpers used by NAT464, plus PF |
| content_filter | bsd/net/content_filter.c and content_filter_crypto.c |
| config_proc_uuid_policy | bsd/kern/proc_uuid_policy.c |
| crypto | libkern/crypto/register_crypto.c and real crypto wrappers |
| config_atm | osfmk/atm/atm.c: atm_get_diagnostic_config |
| config_coredump | bsd/kern/kern_core.c: process_cpu_type and process_cpu_subtype |

sched_set_thread_base_priority is already implemented in standard priority.c;
the linker lists it as a caller of a missing symbol, not as an undefined symbol.
Its implementation and thread_get_kernel_stack's prototype are unchanged.

KPC, KPERF, Apple monitor and KTRR/CTRR remain disabled. The public tree lacks
osfmk/arm64/kpc.c; enabling KPC would add another missing source rather than
provide a Snapdragon PMU backend. Serial KDP is not selected without a serial
backend. Selecting the KDP code does not establish a working device transport.

The MIDO-only runtime supplies typed disabled-performance hooks, a minimal
panic-on-violation integer sanitizer runtime, and an adapter to the existing
non-Apple ARM64 cache-cleaning implementation. Firehose is explicitly unavailable,
not emulated; see runtime/README.md for its disabled-service contract.
This is not a complete linked or bootable kernel. Crypto registration and
wrappers do not supply or initialize a functioning cryptographic provider.
Real logging transport, PMU integration and hardware validation remain separate
requirements, not untyped functions or fake successful security operations.

Local validation replays the pinned doconf selector and runs the existing native
config utility for osfmk, bsd, libkern and iokit in both configurations. All
selected concrete source paths exist in the prepared public tree. This checks
the generated graph, not macOS compilation, successful linking, or hardware.
