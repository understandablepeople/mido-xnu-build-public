# EL1 exception and counter diagnostic

This extends the hardware-confirmed screen test. It is not XNU/iOS and does
not enable timer interrupts, GIC, MMU, caches, secondary CPUs, USB or storage.
The diagnostic image is now confirmed on the handset by the user's photograph.

Build host files only:

    powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\tools\build-arm64-screen.ps1 -Diagnostics

Default output is artifacts/arm64-diagnostics-build-v1. Existing outputs are
never overwritten. This reuses the screen parser, strict-alignment compiler
settings, linker and pinned recovery-ID packer, but selects diagnostics/entry.S
and adds diagnostics.c. The common C sources reserve x28 with -ffixed-x28.
The first image is 30720 bytes, SHA-256:
1f9ade93811b15b3111c25a151b27647965256c5b696c9a1e442751c4a053b04.

## Scope

Only EL1h is accepted. Interrupts remain masked. After the incoming framebuffer
is validated, x28 records its address for unexpected-exception reporting.
All vectors except the current-SPx synchronous slot go to a non-returning
fault renderer. Until a framebuffer is validated they simply halt.

The test issues BRK #0x4d49 at one known instruction address. Its handler saves
x9-x12, checks the exact ESR_EL1 value 0xf2004d49 and exact ELR_EL1, advances
ELR by four bytes, restores those registers and executes ERET. It does not
resume arbitrary instructions or silently ignore other faults. The caller
checks the reported syndrome and saved EL1h status before claiming success.

Unexpected exceptions switch to the lower 4 KiB of the 16 KiB stack reserve.
The framebuffer pointer is then cleared from x28 to prevent recursive fault
rendering. The screen shows ESR, ELR, FAR and SPSR followed by a halt. FAR is
not meaningful for every exception class. This is not a complete crash dump
or general exception-recovery mechanism.

After the BRK test, the code reads CNTFRQ_EL0 and serialized CNTVCT_EL0. It
accepts a nonzero frequency no greater than 1 GHz and polls at most one
million times, stopping early when the counter advances by frequency/1000.
A positive monotonic delta yields COUNTER OK; it is not a calibrated wall
clock, timer interrupt test or proof of a specific elapsed duration. Stalled
and backwards counters have separate messages. No timer control register,
comparator or interrupt-controller register is programmed. Firmware may still
trap register access to an exception level outside the payload's control.

## Expected screen

- MIDO DIAG EL1
- BRK ERET OK
- ESR F2004D49
- FRQ followed by hexadecimal counter frequency
- COUNTER OK
- CNT followed by a hexadecimal counter sample
- DEL followed by its hexadecimal delta
- NOT XNU OR IOS

The test then halts by design. A forced button restart is required to leave
it; there is no USB command service. Lower remnants of lk2nd are stale pixels.

## Host emulation

    python tools/emulate_screen_test.py artifacts/arm64-diagnostics-build-v1

The harness executes the built instructions and verifies rendered status text,
ELR advance, scratch-register preservation and ERET continuation. BRK vector
entry/state and counter register values are supplied by the harness; Unicorn
is not a Qualcomm firmware or hardware-timer model. Additional cases cover
counter stalls/backwards movement, bad frequencies, unexpected syndromes,
register-access faults, EL2 rejection, relocation and invalid framebuffer DTs.
The exact image hash is recorded in the output report. Emulation is necessary
evidence but does not replace an actual handset photograph.

## Reviewed build and first launch: 2026-10-25

All 20 diagnostic emulation scenarios pass in emulation-reviewed.json. This
includes the full one-million-poll stalled-counter bound, scratch-register
preservation through the actual handler/ERET instructions, unexpected syndrome
handling and a synthetic counter-instruction fault. The initial emulator run
needed a harness correction: changing PC inside an MRS hook did not model an
exception reliably, so fault injection now occurs in a pre-instruction hook.
That was a host-model fix, not a change to the built handset payload.

There are 24 passing Python packaging/inspection tests and 16 PowerShell mock
cases. The original screen-only build was rebuilt after the shared-source
changes and remains byte-identical to hardware-tested v2; its 13 emulation
scenarios still pass. The diagnostic ELF has no relocations, unresolved
symbols, GOT or BSS. Its disassembly confines x28 to the intended frame pointer
record/clear operations. The generated screen preview was inspected.

The handset was found in stock fastboot (product mido; oem log unsupported),
then the verified official lk2nd candidate was temporarily booted again. Its
fresh log confirmed mido and the expected framebuffer before the diagnostic
image was sent. Log: artifacts/lk2nd-before-diagnostics-v1.log. The diagnostic
image hash and complete matching emulator report were checked immediately
before fastboot boot. Sending and Booting both returned OKAY. No flash or
erase command was issued. The subsequent photograph supplies the hardware
evidence described below. Do not claim a timer interrupt, GIC or XNU milestone
from this test.

## Hardware confirmation: 2026-10-25

The user's photograph shows MIDO DIAG EL1, BRK ERET OK, ESR F2004D49,
FRQ 0124F800, COUNTER OK and a positive DEL value. Thus the controlled
EL1 synchronous BRK handler returned through ERET, and the virtual-counter
register was readable and advanced monotonically over the bounded probe.
The reported frequency register is 19200000 Hz (19.2 MHz); no external
wall-clock calibration was performed. This does not test timer interrupts.

Photo: artifacts/hardware-proof-diagnostics-v1/mido-el1-brk-counter.png.
SHA-256:
a883bda398922e3b98e971eb9c4235c336523403ea48310f54088ab7505ce546.
The code is halted after the completed probe, with no USB service or active
lk2nd menu. Old lower-screen text remains only as framebuffer pixels. No
hardware claim is made for the unexpected-fault renderer: those fault cases
were exercised in the host model, not deliberately injected on the phone.
