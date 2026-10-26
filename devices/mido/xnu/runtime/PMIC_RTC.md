# Experimental read-only PM8953 RTC

This is not device-boot approval. The low-level C backend has eleven passing
host register-model tests and cross-compiles for Cortex-A53/ARMv8-A.
The XNU wrapper requires a native build and an offline protocol-model test
before any proposed device execution. No raw device MMIO was performed.

Read-only TWRP diagnostics identified qpnp_rtc on PM8953, SID 0, peripheral
0x6000, PMIC arbiter v2 0x20010000, EE 0. The observed RTC advanced once per
second but reported a date in 1972. The backend returns its actual seconds;
it does not add a host-time offset or claim a calibrated UTC clock.

Register facts were checked against the recovery kernel's reported source
commit 1bf4601a044920feba9d76898c8cf225b7d19477 in
zeelog/android_kernel_xiaomi_mido: drivers/rtc/qpnp-rtc.c and
drivers/spmi/spmi-pmic-arb.c. The implementation is independent; those
third-party implementations are not included in the native sources.

The diagnostic platform remains opt-in and synthetic-identity-only.
An additional /chosen property mido,pm8953-rtc-readonly must contain exactly
ten little-endian uint32 words:

    0x0200f000 0x1000 0x02c00000 0x800000 0 0 0x6000 0 0x20010000 19200000

These describe core address/size, observer address/size, EE, SID, peripheral,
PMIC time-write permission (zero), controller version and counter frequency.
They are an explicit diagnostic contract, not evidence of memory ownership.
Without the property the original unsupported RTC-read panic remains.

Only the 4-KiB core and the discovered observer channel's 4-KiB page are mapped,
not the full 8-MiB observer aperture. The APID is discovered from the
runtime mapping table, never assumed from the host tests. Missing, duplicate
or out-of-window mappings are rejected. The only controller writes issue
allowlisted EXT_READL requests for subtype, enable status and seconds.
No PMIC write opcode, clock enable, alarm, interrupt acknowledgement or time
adjustment is implemented. Time-setting continues to panic explicitly.

Each transaction is bounded by 100 microseconds of the 19.2 MHz architectural
counter and 4096 polls. Seconds are read with a bounded carry retry. Unknown
versions, disabled clocks, denied transactions and unstable reads fail;
they never fabricate a successful time value. Single-CPU native transactions
preserve and mask interrupt state; MMIO mappings are established during
platform start, not lazily from potentially preemptible clock reads.

Host validation:

    python tools/test_mido_pmic_rtc.py --toolchain <NDK-bin> --output artifacts/<new-directory>

An initial native build passed compilation and linking, but the original
8-MiB observer mapping panicked in the constrained offline kernel VM before
issuing any PMIC command. Mapping is now bounded to the discovered channel
page. This failure is retained in the v19 trace; it was not bypassed.

Raw recovery captures stay local and must not be committed.

## Verified offline milestone, 2026-10-26

Native Action 40327548127 at d80327b passed in 4m41s. Its kernel SHA-256 is
08d11683009bb08e603c9858f5574653908e7a52d65de9a30cd472fcde533690.
All six staged platform source/header hashes match normalized local sources.

The v21 offline image reaches the original vfsinit entry without panic or
invalid access. The native backend discovers modeled APID 17, maps two 4-KiB
pages, issues five allowlisted observer reads and returns status zero.
The original platform calendar getter returns 65478384 seconds, matching the
modeled seconds word. The initial 65478350 seconds are explicit sampled RTC
input, advanced by modeled time; they are not fresh device wall time.
One native self-SGI, 44 timer exceptions and one WFI wakeup are observed.
Execution inputs remain hash-identical throughout the run.

This proves native code execution against a synthetic peripheral protocol,
not actual handset MMIO, calibrated UTC, completed VFS initialization, a root
filesystem, userspace or installation safety. The image remains do-not-flash.

Eleven C register tests and 96 targeted Python tests pass. Full local discovery
also encounters 19 failures/errors in the pre-existing modified
test_check_xnu_build module; no all-suite-pass claim is made.

A subsequent v22 run observes the original vfsinit return, but does not reach
bsd_autoconf within its 600-second host budget. CoreAnalyticsHub waits forever
in a service-matching worker; that observation alone does not establish that
it blocks the original BSD thread. A separate 200-second v23 trace identifies
the original thread through TPIDR_EL1 and records its preemption and mutex
sleep boundaries. It is still executing inside VFS work when that shorter
budget expires. Neither timeout justifies disabling telemetry, patching
cache-maintenance instructions or fabricating a root-storage service.

The verified v21 offline ZIP has 201 members, 30494069 bytes and SHA-256
81772a458052e10acee529d4e79745dd347dc9eaec17e7745619b33e11fc9341.
Its per-member hashes and ZIP CRCs are verified. It contains exact tracing
source snapshots, the image, native provenance and the successful VFS-entry
report. Later diagnostic changes do not alter that frozen evidence package.

## Post-VFS checkpoint and CPU lifecycle correction

The frozen v21 package was independently extracted, its member hashes checked,
and its VFS-entry test rerun from the extracted source snapshots. The complete
case object matched the reference report, with unchanged execution inputs.

Direct ARM64 BL decoding establishes that this kernel inlines bsd_autoconf
inside bsd_init. There is no direct bsd_init call to the standalone symbol;
waiting for that symbol was an invalid checkpoint. The root-discovery stage
instead verifies and observes the real direct call to IOFindBSDRoot.

The v24 root-discovery trace observes VFS returning and the original BSD
thread entering mcache_init, then sleeping through lck_mtx_sleep. The original
mcache_init calls ml_wait_max_cpus; unlike AppleARMSMP, the MIDO diagnostic
platform had never published CPU initialization completion. Its single-CPU
contract now calls the genuine ml_set_max_cpus(1), only after successful
IOPlatformExpert startup. No scheduler return, lock state, global CPU flag,
or missing storage service is fabricated.

Native Action 40336475616 successfully builds that correction. Its v25 trace
observes ml_set_max_cpus with argument one and two original ml_wait_max_cpus
returns of one. The original BSD thread progresses through mbinit,
eventhandler_init and aio_init, then hits the explicit missing-pthread-table
panic. Thus the CPU wait is resolved, but root discovery is not reached.
See PTHREAD.md for the separately opted-in matching open provider experiment.
