# Experimental typed AES-CBC adapter

mido_aes_cbc.c supplies the two original ccmode_cbc descriptors using the
hash-pinned BearSSL 0.6 constant-time bitsliced implementation. It supports
128-, 192- and 256-bit keys in bytes, without ARM crypto instructions, NEON,
heap allocations or Apple implementation code. The 272-byte aligned context
is statically checked against both original XNU aes_encrypt_ctx and
aes_decrypt_ctx allocations. No provider table or startup hook is installed.

The original CBC callback signatures and inline cccbc_init/update dispatch
are used directly. Both directions preserve the key context, update the
caller-owned IV, and support exact in-place operation or disjoint buffers.
Lengths are block counts, including a no-op zero-block update. There is no
padding or authentication; callers retain those protocol responsibilities.

Invalid key lengths, null/range-overflow pointers, partial overlaps, context
or IV aliasing, misalignment, direction mismatch and uninitialized contexts
return CCERR_PARAMETER before output/IV mutation. A failed reinitialization
of a valid context allocation wipes the entire context, preventing reuse
of the old key. Context lifetime and final key erasure remain caller-owned.
The caller must supply actual accessible storage for every validated range;
numeric validation is not a memory-probing mechanism or a corruption guard.

The Cortex-A53 fixture calls through the real original descriptors and
six-argument ARM64 ABI. It compares both directions, all key sizes, split
updates, IV continuation, exact in-place and disjoint buffers against the
independent cryptography AES backend. That reference is checked against
the NIST SP 800-38A AES-128 CBC example. It also checks output guards,
key-context immutability, failure atomicity and failed reinitialization.

This component does not provide ECB descriptors, CTR, XTS, GCM, DES, RSA or
a complete crypto function table. Real kernel registration, entropy/locking
startup, full relink and original bootstrap execution remain required.
It has not changed the packaged image or accessed a phone.
