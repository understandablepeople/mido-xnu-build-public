# Offline counter and idle-time experiment

This work changes the CPU model only. It does not modify the linked XNU
kernel, publish an RTC resource, provide a wall-clock date, or approve a phone
boot. All new clock modes are explicit offline stages; previous stages retain
their original timing behavior.

## Verified changes

tools/model_mido_counter.py handles native CNTFRQ, CNTPCT and CNTVCT reads
with one 19,200,000 Hz timebase. Architectural timer TVAL, CVAL and control
accesses use the same counter as interrupt eligibility and exception entry.
These accesses share a single instruction dispatcher: independent Unicorn
MRS hooks cannot safely be assumed to chain. Native ARM64 instruction tests
check the frequency, physical/virtual counter and timer delta together.

The host-monotonic mode scales integer nanoseconds at 19.2 MHz. Its full
kernel run reached the original 30-second IORTC resource wait and delivered
256 bounded timer exceptions, but did not reach calendar initialization.
It still ties device time to emulator host speed and is not a CPU timing model.

The event-clock experiment charges executed translation blocks and can
advance idle time only at actual WFI/WFE instructions with an eligible timer.
SEV/SEVL set a modeled single-CPU event flag; WFE consumes that flag without
advancing time. Original instructions execute unchanged, including WFI itself;
no kernel return or PC increment is fabricated to skip an instruction.

Its nominal 2.016 GHz execution clock and either 1 or 64 assumed cycles per
instruction are explicit functional-model assumptions, not measurements of a
Snapdragon CPU. The counter is installed before image entry; expensive block
and hint observation starts only at native XNU entry, not in the copying shim.

## SHA diagnosis and native idle gate

The first short event-clock runs expired in SHA compression. Bounded entry
observation subsequently counted thousands of separate single-block HMAC/SHA
calls, not one oversized or stuck compression. The early_random caller was
zone_scramble_va_and_unlock. Caller symbol lookup is cached so diagnostic
sampling does not scan the whole symbol table on every SHA entry.

A 600-second bounded run reached the real IORTC wait, processed 44 native
timer IRQs and entered the idle thread. The narrower rtc-event-idle-return
diagnostic established the actual barrier: idle_enable, wfi and wfe_allowed
were one, but the original cpu_idle branch loaded SIGPdisabled (0x80000000)
and returned through Idle_load_context without WFI. Earlier reports are
preserved under artifacts/mido-xnu-platform-v15.

## Boot self-SGI verification

Commit 56df350e4105542d486004ea4ad71feb453eb6f8 added an explicitly opted-in
single-CPU boot self-SGI route. Action 40321847735 built the native kernel
successfully. Its SHA-256 is
813643b653bca10860d06ae0a51733d0e42d147c83495144f6570f0d10c8ca1b.
The downloaded build report's staged IRQ source hashes match the local
normalized sources. The old timer-only mode remains the default.

The offline fixture opts in with --boot-self-sgi and --platform-expert.
The model exposes a Group 1 SGI 0 route, observes the native GICD_SGIR write
targeting the current CPU, and injects one architectural exception once IRQs
are unmasked. It does not call cpu_signal_handler or clear SIGPdisabled itself.
The kernel acknowledges SGI 0, retires the raw GIC token and calls its original
CPU signal handler. Native idle observation then reads cpu_signal=0.

ISR_EL1 reports the modeled controller IRQ line independently of PSTATE.I,
allowing the original masked idle polling to observe a pending interrupt.
Native instruction tests verify this without modifying PSTATE or instruction
bytes. The modeled WFI advances to the real programmed timer deadline.

artifacts/mido-xnu-self-sgi-v18/c-rtc-event-calendar-entry-emulation.json
passes: one native CPU signal handler, one SGI 0 acknowledgement/EOI,
48 native timer exceptions, one WFI wakeup, and entry to the original
clock_initialize_calendar after the real IORTC timeout. This is evidence of
native scheduling/timeout progress, NOT a functioning RTC or a phone boot.

The linked image is mido-xnu-synthetic-handoff.img in the same directory.
It retains unapproved synthetic RAM placement. Do not flash or boot it on a
phone. The platform's RTC, suspend and reboot operations remain fail-closed;
calendar/VFS completion, a root device and userspace are not established.

The follow-up rtc-event-vfs-entry run reaches the real diagnostic platform
getGMTTimeOfDay and its explicit panic: RTC read is not implemented. It does
not time out or invent a date. The VFS target remains unreached. Further
hardware work requires a real PM8953 RTC/SPMI implementation and independently
validated RAM/storage ownership, not another warning or panic bypass.
