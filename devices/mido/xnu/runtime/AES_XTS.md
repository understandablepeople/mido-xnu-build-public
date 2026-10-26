# Experimental typed AES-XTS adapter

mido_aes_xts.c supplies both original ccmode_xts descriptors. Data and tweak
keys have separate checked CBC-backed AES contexts; tweak generation always
uses encryption, including the decrypt descriptor. Static assertions verify
both context allocations against the original symmetric_xts layout. No
function-pointer casts, Apple implementation code or ARM crypto instructions
are used. Descriptor implementation identity is CC_IMPL_UNKNOWN, not an
untrue claim to be an Apple assembly implementation.

Each key must contain 16 or 32 bytes, and their values must differ. Equality
is checked without a key-dependent early exit. The callbacks support full
16-byte blocks only, as required by original corecrypto_aesxts.c; there is
no ciphertext stealing or authentication in this descriptor. GF multiplication
advances the little-endian tweak after each block. Separate tweak state
preserves progress across split updates and enforces a conservative maximum
of 2^20 blocks per data unit, cumulatively, without length arithmetic wrap.

set_tweak resets the count and computes the encrypted sector IV. It validates
all ranges and aliases before changing the supplied tweak. init returns a
typed error and clears the context on invalid keys. key_sched and xts cannot
return an error to the original wrapper: invalid state, length, buffers or
key schedules panic instead of allowing the wrapper to report fake success.
Valid xts calls return the actual tweak pointer, including zero-block calls.
Callers own sector-IV uniqueness, accessible storage and final key erasure.

The Cortex-A53 fixture calls through original ccxts_init/set_tweak/update
and key_sched signatures. Independent cryptography AES-XTS results cover
both key sizes, multiple IVs, both directions, full-block split updates,
exact in-place and disjoint buffers, key-context immutability and output
guards. Negative cases cover invalid keys, state/direction, tweak setup,
aliasing, pointer and length overflow and cumulative data-unit exhaustion.
Expected panic execution is observed at the panic entry, never skipped or
turned into a successful return. The isolated limit test deliberately edits
only its fixture counter to exercise the boundary without encrypting 16 MiB.

These descriptors are not installed in the original kernel or packaged image.
They do not complete GCM, DES, RSA or the rest of the crypto function table.
Native compilation and a full rebuild with genuine provider registration
remain required before original XNU bootstrap execution can advance.
