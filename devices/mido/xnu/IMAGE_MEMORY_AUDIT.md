# Packaged-image memory audit

This audit compares the actual kernel and its synthetic transfer fixture with
saved recovery evidence. It does not allocate RAM, authorize a handset boot,
release loader buffers, or access a device.

Run from the repository root:

```powershell
python -X utf8 tools/audit_mido_image_memory.py --kernel artifacts/mido-xnu-platform-v7/kernel.macho --fixture artifacts/mido-xnu-platform-v7/transfer-fixture.json --dtb artifacts/live-recovery/live.dtb --loader-audit artifacts/lk2nd-23.1-audit/memory-contract.json
python -X utf8 -m unittest tests.test_audit_mido_image_memory tests.test_inspect_mido_memory
```

The checker verifies kernel identity, the complete segment-copy plan, entry
translation and handoff-buffer bounds. It checks the entire advertised RAM
range, not merely the copied segments, against fixed reservations and optional
loader runtime/scratch exclusions. Adjacent declared banks are supported;
holes are not. Dynamic reservations remain unresolved even without a known
fixed overlap. Supplied loader audit JSON is historical input, not independently
authenticated live ownership evidence. Every input blob is SHA-256 identified.

## v7 result, October 26, 2026

- Kernel SHA-256: `5f5bd857d0f63fe7fa6782737ceac4549b96fa2e040649efb368a386e0ad3d10`.
- Claimed synthetic RAM: `[0x20000000, 0x24000000)`, 64 MiB.
- The full claim lies within the saved declared RAM banks.
- No intersection with nine conservative exclusions: seven fixed recovery
  reservations plus the supplied loader runtime and scratch envelopes.
- Report: `artifacts/mido-v7-memory-audit.json`; 21 focused tests pass.
- `platform_memory_approved`, `boot_approved` and
  `transfer_of_control_allowed` remain false. No load address is recommended.

The original v7 BSD-entry execution evidence remains unchanged. This audit
does not prove interrupt delivery, timer operation, completed BSD initialization,
root filesystem mounting or userspace startup. Current loader buffer/DMA
lifetimes, dynamic pools and firmware/secure-world ownership still need a
handoff contract before any device placement can be approved. IRQ/timer
integration remains a separate implementation task, not an accomplished gate.
