# Freestanding root diagnostic payload

root_probe.S is a small original ARMv8-A userspace diagnostic, not Apple
launchd or an iOS userspace. It requests getpid using the original Darwin
ARM64 syscall convention, saves the returned value in x19 and then yields
in a loop. That describes its instructions, not evidence of execution.
There is no filesystem-writing or device-control code.

Build on the Windows development host with:

```
python tools/build_mido_root_probe.py --toolchain PATH_TO_NDK_LLVM_BIN --output artifacts/NEW_ROOT_PAYLOAD
```

The assembler emits the real ARM64 instructions. The builder wraps that
text in a bounded thin MH_EXECUTE with an ARM_THREAD_STATE64 LC_UNIXTHREAD
entry, a protected page-zero region, a read/execute text segment and an iOS
LC_BUILD_VERSION. File and segment alignment is 16 KiB. No dynamic linker,
external library or injected syscall result is needed by the payload.

The NDK ld64.lld experiment warned that -static was unimplemented and emitted
LC_MAIN plus a dynamic-linker request. That experimental file is NOT used.
The explicit standalone container avoids treating that warning as success.

The payload is unsigned. No signature-verification code is changed or
bypassed by its builder. A kernel may reject it under its original execution
policy. The report deliberately records signed=false, loaded_by_xnu=false,
executed=false and boot_approved=false. Mounting mockfs, reading the Mach-O
header, loading segments, reaching EL0 and completing the real getpid syscall
are separate gates requiring their own native evidence.
