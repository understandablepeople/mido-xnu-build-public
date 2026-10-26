# Experimental kmem random backend

mido_kmem_random.c implements the four callback signatures in the prepared
XNU libkern/crypto/rand.h. C11 type assertions check those original typedefs;
the context must fit CRYPTO_RANDOM_MAX_CTX_SIZE and pointer alignment.
It is not registered in g_crypto_funcs or linked into the platform-v5 image.

Initialization obtains 48 bytes through read_random and appends a fixed
16-byte domain string before initializing BearSSL HMAC-DRBG/SHA256. The
domain string is not entropy. Initialization requires completed real kernel
PRNG registration and a startup context where read_random can take locks.
The temporary seed is wiped before publication of the ready marker.

Generation uses only the caller-owned context and stack. It calls neither
read_random nor lock services, splits requests into 256-byte chunks, and
does not allocate or use FP/SIMD registers in the tested Cortex-A53 build.
Uniform sampling uses little-endian 64-bit draws with rejection sampling;
zero bounds, invalid state, aliasing and wrapping output ranges panic.
Rejection is capped at 128 attempts and then panics rather than returning a
biased value. Callers must prevent concurrent use or reinitialization of
the same context, as required by this per-CPU backend design.

This implements the explicitly non-general-purpose kmem random contract.
There is no fresh entropy acquisition after initialization and no claim of
prediction resistance after compromise. It deliberately does not reuse or
weaken the separate general kernel PRNG's 16 MiB entropy-credit policy.
It must not replace read_random or serve as a cryptographic random API.

tools/test_mido_prng_bridge.py executes the actual compiled backend and
bridge with synthetic registration, lock and read_random recipients. Seed
bytes come from the compiled PRNG bridge, not a constant returned directly
by the kmem fixture. Python independently computes the bridge output and
the derived kmem stream, including chunk and uniform-sampling boundaries.
Observers check that generation makes no further seed requests or lock
service calls. Negative cases stop at the actual panic entry.

These tests do not execute original XNU registration or kmem_crypto_init.
Real kernel builds, complete crypto-table coverage, genuine kernel lock
services and original startup execution remain integration requirements.
No phone access, image patching or GitHub Actions are part of these tests.
