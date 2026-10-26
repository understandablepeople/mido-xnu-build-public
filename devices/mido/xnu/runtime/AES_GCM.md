# Experimental typed AES-GCM adapter

mido_aes_gcm.c provides both original ccmode_gcm descriptors and the two
typed managed-IV callbacks from register_crypto.h. It uses the pinned
BearSSL 0.6 AES-CT CTR and GHASH-CTMUL32 backends, without ARM crypto
instructions, NEON, dynamic allocation or imported Apple implementations.
The opaque, 16-byte-aligned context owns its AES and GCM states. Its address
is bound at initialization because BearSSL retains an internal key pointer;
moving or cloning an initialized context is rejected, not silently accepted.

The lifecycle is initialize, set IV, stream AAD, stream payload, finalize.
AAD cannot resume after payload begins. Reset retains the key but requires
a fresh IV before another message. Empty AAD/payload and exact in-place
processing are supported. Partial overlaps, context aliases, null/wrapping
ranges, invalid call order and oversized lengths fail before mutation.
Payload is bounded to 2^36-32 bytes; AAD and IV bit lengths cannot overflow
the original 64-bit GCM encoding. Invalid initialization clears old key state.

The original ccgcm_finalize contract explicitly requires decryption to
verify its input tag, return an integrity error on mismatch, and overwrite
that tag with the computed value even when verification fails. This adapter
implements that contract using a non-early-exit comparison. The supported
tag lengths are 4, 8 and 12 through 16 bytes, not zero-length authentication.
A finalized context cannot finalize again or process further payload until
reset. As with the original streaming API, provisional decrypted plaintext
must not be used until successful finalization; this is the caller's duty.

Managed-IV initialization accepts exactly the original 12-byte nonce input:
four salt bytes followed by an eight-byte big-endian counter. Manual set-IV
and managed increment operations cannot be mixed. Increment requires reset,
preserves the salt and refuses 64-bit counter wrap before changing state or
output. Callers must still prevent initial key-IV reuse across contexts.
No FIPS certification or entropy-source approval is claimed.

The Cortex-A53 fixture checks both directions and every AES key size against
an independent cryptography AES-GCM backend, including non-96-bit IVs,
padding boundaries, split AAD/payload updates, in-place buffers and output
guards. It also checks the standard zero-key/zero-IV vector, real truncated
tag verification and rejection, finalization state, alias/range errors and
managed-IV increment/carry/exhaustion. Original managed-IV function typedefs
are checked without function-pointer casts. Panic or authentication failure
is never converted into success.

This is a candidate component, not provider registration or an image update.
The rest of the crypto function table, actual startup/locking, full XNU relink
and execution of original bootstrap remain required. No phone is accessed.
