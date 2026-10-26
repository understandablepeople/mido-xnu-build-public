# Synthetic-only diagnostic platform expert

MidoDiagnosticPlatform derives directly from the open IOPlatformExpert. It is
an opt-in offline bring-up component, not a phone platform driver. It does not
enumerate storage, provide a root device, publish IORTC/IONVRAM, or claim a
working calendar clock, suspend, reboot or power controller. Unsupported RTC,
halt/restart and sleep requests panic explicitly instead of returning success
or an invented date. The normal IOPlatformExpert startup machinery is retained.

## Matching contract

The additive built-in personality uses IOProviderClass=IOPlatformExpertDevice,
IONameMatch=mido,synthetic-abi-only and IOProbeScore=1000. The original
IOPanicPlatform personality and implementation remain unchanged. Probe rejects
all other compatible strings, including xiaomi,mido, before calling superclass
probe. Start rechecks the same contract before superclass startup.

/chosen/mido,diagnostic-platform must contain exactly seven little-endian
uint64 values: version=1, cpu_count=1, boot_cpu=0, frequency=19200000,
timer_intid=20, distributor=0x0b000000, interface_base=0x0b002000. Runtime CPU
count, boot CPU number and CNTFRQ_EL0 must also match. These declarations are
not proof of hardware ownership. Native IRQ startup separately validates its
device-tree GIC/timer routing. The offline image producer injects this property
only with its explicit --platform-expert option; device placement is not approved.

## Build isolation

Use --experimental-platform-expert only with the explicit bootstrap crypto,
IRQ timer and non-Apple startup options. The manual workflow input
approve_platform_expert defaults to false. Staging pins the prepared
KernelConfigTables.cpp hash, inserts a new personality without removing the
panic fallback, and adds one C++ source to the MIDO runtime build graph.
The per-object flags target MidoDiagnosticPlatform.cpo, not a C .o file.
Original kernel C/C++ sources are not manually edited in the workspace.

## Current verification boundary

Local tests check additive staging, pinned-source rejection, graph isolation,
default-off CLI behavior and dependency requirements. The exact contract
checker compiles as ARM64 Mach-O in both C and C++, and its ARM64 ELF machine
code executes in Unicorn. Positive and negative checks cover unaligned DT
data, every contract field, real-phone/unknown identities, CPU/frequency
mismatches, null pointers and incorrect lengths.

The native macOS build in Action 40266172143 compiled and linked the full
subclass. Offline execution of that exact kernel stopped at the real
IOCatalogue::initialize assertion before matching: the inserted personality
lacked the comma separating it from IOPanicPlatform in OSUnserialize array
syntax. The staging generator now emits that comma and a regression test
checks the serialized dictionary boundary. The existing kernel is unchanged;
a fresh native build is required to test this source correction.

## Subsequent native build and offline execution

Action 40267311920 at e9964f212a00a08b55dc3447d05d054897b45921
successfully rebuilt the corrected catalogue. Its 15,262,272-byte kernel has
SHA-256 38e4b2267debf8906ae42ab58f3a1889703909a4a97faaab6d9d133d13bca768.
The earlier build failure described above is historical, not the current gate.

The original subclass probe and start now execute successfully in the offline
CPU model, including the original IOPlatformExpert superclass startup and both
native platform globals. A separate negative fixture rejects the missing
diagnostic contract. Reports are retained in artifacts/mido-xnu-platform-v15
and artifacts/mido-xnu-platform-v15-negative.

The next observed native gate is the 30-second IORTC resource wait. Native
timer IRQ entry, acknowledgement and EOI have been observed, but calendar/VFS
initialization and a device boot have not. No RTC wait or panic bypass is
introduced. See EMULATOR_TIME.md for the clock-model experiment and its limits.

The event-clock idle-return diagnostic subsequently reached the original
cpu_idle and Idle_load_context after 44 native timer exceptions. idle_enable,
wfi and wfe_allowed were all one, but the original cpu_idle branch observed
cpu_signal=0x80000000 (SIGPdisabled). Thus the native kernel deliberately
returns without reaching WFI; increasing the emulator timeout alone does not
repair this missing CPU-signal lifecycle.

The optional IRQ backend now has a boot self-SGI path, selected only by an
explicit 32-bit zero mido,boot-self-sgi-intid property on the diagnostic
interrupt-controller node. It requires one boot CPU numbered zero and an
already non-secure Group 1 SGI 0 route. It does not reclassify secure interrupts.
The GIC sends SGI 0 to the current CPU only; its native interrupt handler calls
the original cpu_signal_handler after retiring the raw GIC token. Timer service
retains its existing service-before-EOI ordering. The SIGPdisabled field is not
modified directly. Without the property the previous timer-only path remains.

Thirty-six host C register-model tests pass, and the low-level sources
cross-compile for Cortex-A53/ARMv8-A with warnings treated as errors. Native
Action 40321847735 at 56df350e4105542d486004ea4ad71feb453eb6f8 also passes.
The resulting kernel SHA-256 is
813643b653bca10860d06ae0a51733d0e42d147c83495144f6570f0d10c8ca1b.

The offline self-SGI fixture observes one native SGI 0 acknowledgement/EOI,
one original CPU signal handler, cpu_signal=0, a native WFI wakeup and entry
to clock_initialize_calendar after 48 timer exceptions. A separate VFS-targeted
run then stops at the explicit RTC-read panic in getGMTTimeOfDay. This is the
current real service boundary, not an execution-budget failure. No successful
calendar initialization, VFS entry or device boot is claimed. Both reports and
the synthetic image are under artifacts/mido-xnu-self-sgi-v18.
