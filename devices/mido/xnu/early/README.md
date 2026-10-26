# Early GICv2 / virtual timer groundwork

Status: standalone source and host register-model tests only. Not integrated
into XNU, not linked into any phone payload and never executed on the phone.
No new cloud run or commit/push is part of this local stage.

## Saved DT evidence

tools/mido_irq_contract.py inspects the saved Linux DTB without ADB/fastboot.
It resolves inherited interrupt-parent properties and checks phandles,
cycles, known intermediate controllers, cell widths and bus translation.
It rejects unsupported layouts rather than guessing. No live DTB is uploaded.

The saved recovery tree gives this path:

    /soc/timer -> /soc/wake-gic@601d4 -> /soc/interrupt-controller@b000000

The first parent is Qualcomm MPM, not directly the GIC. Its reviewed
downstream driver copies the three-cell interrupt specifier to the parent.
In the timer binding order, the third tuple is virtual: PPI index 4, giving
GIC INTID candidate 20. Other timer candidates are 18, 19 and 17. Do not
copy a common platform's timer ID 27. DT frequency is 19,200,000 Hz, agreeing
with the earlier standalone hardware counter report, not a new measurement.
The flags are 0xff08; no PPI trigger, CPU target or group state is programmed.

The /soc ranges property translates these register windows identically:
distributor 0x0b000000 size 0x1000, CPU interface 0x0b002000 size 0x1000.
These addresses are not automatically mapped or dereferenced by this code.
The downstream reference is the same device family, not proof of the exact
recovery kernel's driver binary or of interrupt delivery in our boot context.
hardware_route_verified and boot_approved remain false.

## GIC contract

irq_timer.c implements bounded software attachment, one outstanding
acknowledgement and combined-mode completion through supplied IO callbacks.
The caller must zero-initialize mido_gic, keep IO storage alive, guarantee
single-core non-reentrant use with IRQs masked, and separately establish
GICv2 identity, ownership, mapped Device memory and valid access permissions.
Callbacks must implement real ordered MMIO and the required synchronization.

- attach reads distributor/CPU controls and TYPER, never writes controller
  configuration. Enabled bits are only a readiness check, not proof that
  the timer PPI is configured or that security/group ownership is suitable.
- take checks the current EOI mode, then reads GICC_IAR. That read would
  acknowledge hardware if real MMIO callbacks were connected; it is NOT a
  passive status read. No hardware callbacks are connected in this stage.
- IDs 1020 through 1023 are returned as special/spurious, without EOI.
- For real IDs, the full IAR token is kept, including SGI source CPU bits.
  A second take or reattach cannot overwrite an outstanding token.
- finish writes that exact token to GICC_EOIR only after caller service.
  Duplicate completion and out-of-range IDs are rejected.
- Split EOI modes are rejected, not reconfigured. No GICC_DIR access is
  attempted; its offset 0x1000 is outside the saved 0x1000 CPU window.

This does not initialize GICD, priorities, groups, PPI enable/pending bits or
CPU-interface delivery. It does not dispatch handlers, configure MPM, or
enable DAIF IRQs. Unexpected IDs and access faults require a future platform
failure path; callers must not blindly EOI unserviced level interrupts.

## Timer contract

arm_delta accepts positive relative ticks below 2^63 and rejects a wrapping
deadline before any writes. It disables/masks the virtual timer, writes the
absolute comparator and enables/unmasks it with synchronization between
steps. stop leaves it disabled and masked. There is no frequency conversion
or elapsed-deadline retry; very short delays may expire during programming.

arm64_timer.c supplies serialized CNTVCT_EL0 reads, CNTV_CVAL_EL0 and
CNTV_CTL_EL0 writes, and DSB SY / ISB barriers. bind only fills callback
pointers; it does not access the timer. Real calls require an owned EL1
context, firmware-granted timer access and a separately established IRQ
route. Existing firmware timer state is not saved/restored by these APIs.
No physical timer, GICv3 ICC register, storage or USB code is involved.

## Local verification

Run from the workspace root with the local NDK Clang and universal LLD:

    python tools/test_mido_irq.py --compiler CLANG --linker LD_LLD --output-directory artifacts/NEW_DIRECTORY
    python tools/mido_irq_contract.py artifacts/live-recovery/live.dtb

The Windows runner compiles irq_timer.c into an x86_64 DLL with no entry
point, CRT or imports, and executes it with Python ctypes register callbacks.
It separately cross-compiles both C files for Cortex-A53 ARMv8-A using
strict alignment and general registers only. ARM64 code is not executed
by these tests. There is no device transport or phone boot command.

The model covers normal and special IDs, raw SGI token preservation,
single-active state, EOI ordering, missing callbacks, changed control modes,
timer programming order, invalid deltas and overflow. This does not model
GIC security banking, MMU mappings, exception vectors or real IRQ timing.

Local evidence: artifacts/mido-irq-model-v3 contains 24 passing native C
model cases and both Cortex-A53 assembly outputs. Ordinary regressions pass
56 Python tests and 16 PowerShell mock cases. The model includes timer
rearming before EOI; it is not evidence of an interrupt on the handset.

Primary references:

- Linux v6.12 include/linux/irqchip/arm-gic.h and drivers/irqchip/irq-gic.c.
- Linux v6.12 Documentation/devicetree/bindings/timer/arm,arch_timer.yaml
  and interrupt-controller/arm,gic.yaml.
- LineageOS/android_kernel_xiaomi_msm8953 commit
  0ac2c6831eabb90d18f49081bc2221a715763e50, drivers/irqchip/qcom/mpm.c,
  msm_mpm_gic_chip_translate and msm_mpm_gic_chip_alloc.

Next integration gate: complete MIDO master/build configuration, establish
safe virtual MMIO mappings and ownership, then connect XNU platform/vector
entry and timer dispatch. No image is approved for hardware testing yet.
