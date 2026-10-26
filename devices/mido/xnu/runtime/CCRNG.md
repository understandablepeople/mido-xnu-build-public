# Experimental typed system-RNG compatibility

mido_ccrng.c supplies the original ccrng_fn_t getter and ccrng_state.generate
interface using the tested MIDO kernel PRNG through read_random. This is a
system-RNG adapter to the HMAC-DRBG-backed port, not a separate AES-CTR DRBG,
not the Apple provider, and not a claim to the FIPS certifications mentioned
in the original ccrng header. It never adds a fixed-seed fallback or treats
caller input as trusted entropy.

The getter returns NULL with CCERR_CRYPTO_CONFIG before PRNG registration
has returned successfully. A release/acquire publication flag is set only
after register_and_init_prng returns, not when installation merely begins.
The opaque state is a stable singleton. The fixture checks that it remains
unpublished throughout the registration callback. Native startup ordering,
single-CPU restriction and real XNU mutex initialization are still mandatory.

Generation validates state identity, range overflow and aliases before
calling the original read_random interface in requests of at most 256 bytes.
It inherits the PRNG's entropy health, locking and generation-budget failure
policy: a backend panic is never turned into successful random output.
The interface does not promise atomic output if a fatal backend failure
occurs after some chunks have been produced. Zero-length output is a no-op.
Invalid output and attempts to overwrite the singleton callback through
either output or the getter's error pointer are rejected.

ARM64 tests check pre/post-registration publication, exact original typedefs,
stable identity, zero/chunk-boundary/multi-chunk requests against independent
Python HMAC-DRBG results, actual read_random call counts, invalid/copy-state
rejection and guards. Synthetic registration, locks and entropy are fixture
services, not evidence of original XNU startup or real hardware entropy.

The adapter has not been installed in the existing image. Complete provider
coverage, original registration/startup, a full kernel rebuild and offline
execution of that rebuilt image remain required before installation work.
