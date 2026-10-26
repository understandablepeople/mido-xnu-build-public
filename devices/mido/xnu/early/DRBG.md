# Isolated random-backend component

Status: a real SHA-256 HMAC-DRBG adapter compiled for Cortex-A53 and executed
offline. It is NOT registered with XNU, NOT linked into the experimental
kernel/image, and NOT evidence of a working kernel crypto provider.

drbg.c uses the upstream BearSSL implementation rather than replacing
crypto with constant results or implementing a new hash/cipher. BearSSL
0.6 is an experimental dependency here, not a production security approval.
The MIT license is retained in the original dependency tree and copied
alongside each successful ARM64 test report.

## Dependency and reproducibility

The archive was retrieved from the official bearssl.org release location:
https://bearssl.org/bearssl-0.6.tar.gz

Archive SHA-256:
6705bba1714961b41a728dfc5debbe348d2966c117649392f8c8139efc83ff14

This pin identifies the retrieved bytes; it is not an independently
verified release signature or a vulnerability review. The test tool checks
the archive hash and every extracted file and rejects changed files, extra
headers and symbolic links before compilation. Source/adapter hashes and
the compiler version are recorded in report.json.

Run tools/test_mido_drbg.py with --toolchain pointing to the existing NDK
LLVM bin directory and --output pointing to a new artifact directory.
The dependency archive and extracted source are under artifacts, not
silently installed as a production kernel dependency.

## Measured behavior

artifacts/mido-drbg-v5/report.json records 34 passing ARM64 scenarios:
multiple seed/request lengths, repeated output matching an independent
Python HMAC/SHA256 reference, reseeding, uniform sampling, rejected invalid
and overlapping buffers, byte-budget exhaustion and full context clearing.
This is not CAVP validation, entropy-source validation or a security audit.

The compiled state is 160 bytes, within the original 256-byte kmem limit.
The adapter allocates no memory and acquires no locks. Compilation uses
-mgeneral-regs-only; it must not assume SIMD/FP availability in the kernel.
The emulator maps code read/execute only, with synthetic caller-owned data
and stack. Test-only libc replacements are not production kernel symbols.

## Caller contract

- Supply aligned, caller-owned context and valid retained input/output
  buffers. Context ownership and synchronization are the caller's job.
- Initialization requires at least 48 seed-material bytes; reseeding
  requires at least 32. Length does not prove entropy or independence.
  Production entropy provenance and boot-seed lifetime remain unresolved.
- A request is limited to 65536 bytes. After 16 MiB generated since init or
  reseed, generation fails with RESEED_REQUIRED. There is no weak fallback.
- Uniform sampling uses rejection sampling, rejects bound zero and returns
  RETRY after 128 rejected draws instead of returning a biased substitute.
- Callers must handle every nonzero status. XNU's void callback signatures
  need explicit typed wrappers with a correct fail-closed/reseed policy;
  casting this status-returning API into the table would be an ABI error.
- Context clearing uses volatile stores. No claim is made that every
  library stack temporary or caller-supplied seed copy is erased.

## Integration still required

Implement and verify the separate kernel PRNG registration, entropy and
reseed path, complete crypto function-table coverage, and startup ordering.
Then rebuild the real kernel and rerun the original kmem hook. The existing
platform-v5 image still has g_crypto_funcs == 0 and prng_ready == false.
Do not patch those pointers from the emulator or label this component a
completed crypto provider. No phone or GitHub Action was used.
