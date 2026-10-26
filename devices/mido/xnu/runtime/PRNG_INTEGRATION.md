# Kernel PRNG integration work

Status: functional single-CPU lifecycle component and a typed registration
bridge, not installed into the downloaded kernel or platform-v5 image.
The full crypto function table is still missing. mido_prng_lock.c now supplies
a real XNU mutex backend candidate, but original kernel startup and locking
behavior have not been executed with this backend.
Do not advertise a working complete provider until those dependencies and
actual startup ordering are implemented. BOOT_CRYPTO.md documents a separate,
explicitly opted-in diagnostic integration: supported callbacks use these
backends, while every unsupported callback panics rather than claiming success.
It permits an actual kernel rebuild and bootstrap test without pretending that
the full-table or installation-readiness gates have passed.

## Components

early/kernel_prng.c wraps the tested BearSSL-backed early/drbg.c component.
It accepts the actual original register_and_init_prng input: a 32-byte
bootseed and an 8-byte nonce. It appends a fixed domain-separation string,
not additional entropy. The seed/nonce lengths are deliberately checked.
Initialization is single-threaded, with a zero-initialized caller-owned
state. After publication, every operation uses supplied lock services.

mido_prng_bridge.c uses the original corecrypto/cckprng.h callback types,
without function-pointer casts. It owns a genuine cckprng_ctx token object
and separate typed backend state; it does not overwrite or reinterpret the
private corecrypto context layout. Its six callbacks implement initialization,
CPU initialization, input mixing, refresh and generation. Nonzero errors
become panic, except unavailable try-lock in refresh, which simply defers
refresh. The bridge refuses installation before crypto_init or twice.

The bridge and its dependencies have passed native KERNEL=1 compilation on
Xcode 15.4 with original XNU exported headers and -Wall -Wextra -Werror.
Actions run 40251209763 produced 21 actual ARM64 Mach-O objects, including
the bridge, native mutex backend, kmem, all five digest/HMAC algorithms,
lifecycle, DRBG and their BearSSL dependency units. Downloaded object hashes
were checked against the native report.
This is not a linked XNU kernel, execution of register_and_init_prng, kernel
locking validation or evidence that registration states changed in the image.

mido_prng_lock.c uses original LCK_GRP_DECLARE and LCK_MTX_DECLARE startup
registration plus lck_mtx_lock/unlock and lck_mtx_try_lock. The try-lock's
boolean result is converted to the service convention (zero means acquired).
Installation refuses to run before STARTUP_SUB_LOCKS is complete. It does
not automatically register a provider or set crypto_init; the future complete
provider must explicitly call mido_kernel_prng_install_native at a valid
startup phase. No synthetic spinlock replaces kernel mutexes.

## Entropy and failure policy

The prepared XNU entropy_provide returns a sample count, not a byte count.
It supplies 32 conditioned bytes only after its health/startup tests and
at least 256 new samples; no entropy is signaled by zero count and length.
This port matches that specific source contract, not arbitrary external
entropy callbacks. A negative health result, malformed length, or positive
count below 256 permanently fails and clears this backend instance.
The original source hashes are recorded in the test report.

No entropy from a refresh leaves the existing generation budget unchanged.
Qualified refresh reseeds and renews that budget. A write_random reseed is
attacker-controlled input: it is mixed into state without renewing entropy
credit or bypassing the 16 MiB limit. The bridge hashes arbitrary supplied
input to 32 bytes before mixing; this is not treated as newly trusted entropy.
On exhaustion without qualified refresh, the backend fails closed.

Only CPU0 is supported; max_cpus != 1, duplicate CPU initialization and
requests beyond the original 256-byte callback limit are rejected. This
does not claim SMP support or a measured entropy rate on Snapdragon.

## Offline execution evidence

tools/test_mido_drbg.py builds and executes the actual Cortex-A53 machine
code for DRBG plus the lifecycle component. Tests cover original seed/nonce
lengths, reference output, CPU ownership, lock contention, entropy absence,
qualified refresh, sticky health failure and user-input credit preservation.
The lock and entropy services in tests are explicit synthetic fixtures,
not implementations of kernel mutexes or handset interrupt entropy.

tools/test_mido_prng_bridge.py additionally executes the compiled bridge on
a Cortex-A53 emulator. Its recipient named register_and_init_prng is an
explicit synthetic fixture, NOT the original XNU implementation. It invokes
the typed seven- and eight-argument initialization callbacks and compares
generation, arbitrary-input mixing and qualified refresh to an independent
Python HMAC-DRBG reference. Negative cases observe the actual compiled panic
entry without returning from it or substituting successful results.

Code and constants are read/execute-only; writable globals are non-executable.
The runner builds with -Wall -Wextra -Werror and records dependency, source
and original corecrypto-header hashes. Synthetic services cover lock
contention and entropy failures, but do not prove real kernel locking.

The test support does not replace a function in the existing XNU emulator
and is not linked into any phone image. Original registration, kernel builds
and bootstrap execution remain required before calling integration complete.

## Next integration gates

KMEM_RANDOM.md describes the separate experimental lock-free kmem callback
backend and its tests through this bridge. It does not complete the crypto
function table or install either provider into the current image.

SHA256.md documents the typed digest adapter needed by original entropy
conditioning. Its ARM64 reference tests do not execute entropy_provide or
complete the other crypto function-table callbacks.

HMAC_SHA256.md describes the matching 144-byte HMAC callback adapter and
independent key/message tests. It does not supply other digest algorithms
or complete cipher and RSA function-table coverage.

DIGEST_HMAC.md covers the newer general digest/HMAC adapters for all five
algorithms named by this XNU revision. It supersedes the SHA256-only
coverage limitation for these adapter components, not the incomplete
provider registration or remaining cipher/RSA interfaces.

AES_CBC.md and AES_CTR.md describe the native-compiled CBC and streaming
CTR candidates. Actions run 40251842984 produced 28 actual ARM64 objects;
all downloaded object hashes match its report. AES_XTS.md describes the
full-block XTS candidate, which passed native compilation in Actions run
40252083473: all 29 downloaded object hashes match the report. These
components are not registered in XNU
and do not close the remaining cipher, RSA or startup integration gates.

AES_GCM.md documents real decryption-tag verification and the original
managed-IV lifecycle. Actions run 40252834220 compiled all 33 units with
the original Darwin kernel headers; downloaded object hashes were verified.
CCRNG.md describes the separate system-RNG adapter candidate and explicit
release/acquire publication only after PRNG registration returns.

The isolated runner now snapshots source, port/ABI header and Python-harness
hashes before compilation and refuses to issue evidence if they change
during execution. Earlier debug-only runs without that check must not be
used to certify a concurrently edited source revision. The current combined
run is artifacts/mido-aes-gcm-ccrng-v2, not the earlier GCM debug directory.

1. Complete and validate crypto function-table coverage, including the SHA256
   functions used by original entropy_provide, before setting crypto_init.
2. Supply genuine initialized XNU lock services and a valid startup phase.
3. Stage the dependency and adapter sources under an explicit MIDO-only
   configuration, preserving upstream licenses and exact input hashes.
4. Rebuild/relink XNU, then execute original registration and kmem startup
   in the packaged-image offline model without pointer injection or skips.
5. Continue IRQ/timer and physical-memory handoff validation separately.

The existing image remains unchanged. No phone commands were executed.
The user-authorized manual native audit runs do not build a linked kernel
or install these adapters into an image.

## Native-build prerequisite check

tools/check_mido_native_provider.py checks the adapters and dependencies using the
Darwin arm64-apple-ios16.6 target, KERNEL=1 and XNU_KERNEL_PRIVATE=1 rather
than the isolated Android test configuration. It accepts an explicit Apple
SDK root; no Android sysroot or fabricated SDK header is substituted.

The earlier Windows-host report in artifacts/mido-native-provider-v1/report.json
failed at missing string.h. This host prerequisite was subsequently resolved
by the authorized macOS Actions audit using Xcode 15.4 and its actual iPhoneOS
SDK. The native report is preserved under
artifacts/actions-native-provider-40251209763/native-provider/report.json.

Before treating a provider as integrated, finish callback coverage and
registration, rebuild the kernel, and execute the original bootstrap path.
Native objects and isolated offline tests are not a substitute for those gates.

The native checker now verifies the pinned archive and every extracted
BearSSL file before invoking the compiler, just like the isolated runner.
It records the actual crypto ABI-header hashes and requires the plain
ARM64_ALL Mach-O subtype, rejecting ARM64E objects that a Cortex-A53 cannot
execute. This is object-header classification, not a linker or boot test.
