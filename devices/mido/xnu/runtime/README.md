# MIDO bring-up runtime

These files are copied to osfmk/kern by tools/stage_mido_runtime.py after the
existing frontend compatibility transforms, before header/config generation.
The manifest selects them only through the MIDO mido_runtime pseudo-device.
KPC/KPERF, the Apple monitor and Apple-specific cache implementations must not
be enabled simultaneously; compile-time guards reject those combinations.

## Disabled performance services

Definitions use the real kernel declarations: kpc_off_cpu_active is boolean_t
data, kpc_off_cpu_internal takes thread_t, and kperf_is_sampling returns bool.
Sampling is always off; disabling an already disabled service returns zero.
Timer setup and reset do no hardware work. Activating KPC without a provider
panics rather than claiming to collect counters. ml_enable_monitor does nothing
only for this NO_MONITOR configuration; it does not claim Apple PPL, KTRR or CTRR.

## Cache maintenance

CleanPoC_DcacheRegion_Force_nopreempt_nohid(vm_offset_t, size_t) rejects
overflowing ranges and handles zero length without touching memory. Nonempty
ranges call the existing CleanPoC_DcacheRegion_Force implementation. In the
pinned non-Apple ARM64 path it branches directly to CleanPoC_DcacheRegion_internal:
line alignment using MMU_CLINE, dsb sy, dc cvac for each line, then dsb sy.
It does not alter Apple HID registers or preemption state. MIDO selects
MMU_CLINE=6. This is not a device-validated cache/MMU backend.

## Firehose unavailable mode

This is NOT a Firehose ring buffer or logd transport. MIDO forces unified
logging off before and during OSLOG startup. oslogopen and oslogioctl return
ENOTSUP so no nonexistent buffer can be mapped or acknowledged. Existing
printf/msgbuf code is not replaced; working serial/display output still
depends on the platform console backend.

The shim includes genuine pinned Firehose SPI declarations. Reservations fail
with NULL and clear the private-data pointer; no payload is accepted or
reported as delivered. Configuration is not accepted, and merge reports no
pending work. Unexpected buffer creation or flushing a non-NULL tracepoint
panics. Unified logging requires a real matching Firehose provider, not removal
of these checks.

## Minimal integer sanitizer runtime

The five minimal arithmetic handlers and abort variants use the void(void)
minimal-runtime ABI. Every violation panics with its operation name; none
silently suppresses undefined behavior. Handlers disable undefined/integer
sanitizer instrumentation to avoid recursion. This is not full descriptor-based
UBSan support.

## Core dumps and validation scope

config_coredump selects original bsd/kern/kern_core.c implementations of
process_cpu_type and process_cpu_subtype. No CPU-type data aliases are added.

Tests cover staging, modeled freestanding AArch64 contracts with the real
Firehose SPI header, incompatible-feature rejection, and minimal UBSan IR.
Modeled header tests are not full Xcode compilation or hardware tests.
Neither these definitions nor a successful link approve a device boot.
