# Experimental single-CPU GICv2 timer integration

This backend is opt-in through --experimental-irq-timer, requires the
diagnostic bootstrap-crypto build, and is not enabled by ordinary builds.
It does not authorize device access or approve any physical RAM layout.

The EARLY_BOOT/LAST startup callback maps only the two saved MIDO GICv2
apertures using XNU ml_io_map, checks a masked IRQ context, the explicit
Apple-tree timer INTID, the 19.2 MHz CNTFRQ and the exact register translation.
It requires an already enabled distributor/CPU interface, accessible Group 1
level-triggered PPI 20 from the saved MSM8953 tree, combined EOI mode and a working enable-bit readback.
It does not change security groups, reset the distributor, or claim ownership
of firmware interrupts. PMR is set to 255 and only PPI 20 priority/enable are
programmed. These are active operations, not passive inspection.

The backend installs a correctly typed handler with the original
ml_install_interrupt_handler. Original sleh_irq dispatches that registered
handler on this non-AppleARMSMP configuration. The handler acknowledges the
GIC token, calls the original rtclock_intr, and only then writes the original
token to EOIR. Original timer_intr/setPop/ml_set_decrementer remain intact.
The CPU's typed decrementer callback programs CNTV_TVAL_EL0 and reenables
CNTV_CTL_EL0 when original ml_set_decrementer requests a deadline. The
interrupt service masks/disables the timer before calling rtclock_intr;
if original timer_resync_deadlines finds no next deadline, it stays disabled
instead of repeatedly asserting the expired interrupt. Startup enables the
previously programmed comparator after registration. Unknown interrupts panic without EOI rather than silently
discarding an unserviced level interrupt. Spurious IDs do not invoke the
timer handler or write EOI. This is not yet a general IOKit interrupt domain.

The saved-tree fixture supplies mido,virtual-timer-intid from its parsed
architectural timer route, not from an inferred Apple timer interrupt.
Nonsecure access, firmware routing, real exception delivery and device
ownership remain hardware prerequisites, not conclusions of a green build.

Verification distinguishes native register-model tests, actual XNU
compilation/linking, packaged-image execution and handset execution.
None substitutes for the next. No phone commands are part of these tools.

## Packaged v10 execution evidence

Actions run 40259512477 rebuilt commit ca09b3b with this backend. The local
image is artifacts/mido-xnu-platform-v10/mido-xnu-synthetic-handoff.img.
Its SHA-256 is
80a05316e165a081516212ba3de1ef667bde940a8772cea59494fbad0955f4d4.

Primary passing execution report:
artifacts/mido-v10-irq-verification-v2/c-bsd-irq-emulation.json.
Original startup reaches BSD entry, maps both GIC apertures and installs
the native handler once. The harness then models one architectural IRQ
entry through the original EL1-SP0 vector, without replacing kernel handlers.
Original sleh_irq, rtclock_intr, timer_intr and entropy_collect execute;
the real exception return restores all 31 general registers, SP and PSTATE.
Two comparator writes occur before the timer EOI in this execution.

Separate calls of the native handler verify spurious handling, the original
ml_set_decrementer-to-typed-callback reenable path, timer service and a panic
without EOI for an unknown interrupt. These calls are diagnostic, not later
BSD boot or hardware delivery evidence. The explicit GIC/timer model supplies
device register semantics: the installed Unicorn build otherwise discards
CNTV_CTL writes, as confirmed with a separate MSR/ISB/MRS probe. Timer MRS/MSR
modeling is hardware emulation, not a successful-return stub for kernel code.

Earlier v8/v9 and first v10 diagnostic reports remain preserved as failed
experiments. They must not be used as the passing report. The corrections
retain strict checks: use the saved tree's INTID 20, mask a serviced timer
until a real new decrementer request, and account for compiler-inlined
deadline programming by observing actual register writes before EOI.

This closes a software integration gap only. Current RAM ownership,
firmware routing, actual handset IRQ/timer behavior, rootfs and userspace
remain unverified. No device boot or installation is approved.
