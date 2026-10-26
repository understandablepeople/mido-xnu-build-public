# Experimental HMAC-SHA256 callback adapter

mido_hmac_sha256.c supplies the four original cchmac callback signatures
for the mido_sha256_info descriptor. It rejects other algorithms rather
than silently replacing them. It is not a registered crypto function table.

The context follows this XNU revision's 144-byte allocation: a padded
108-byte digest context followed by the 32-byte outer chaining state.
It does not place the much larger BearSSL HMAC context in that allocation.
Keys longer than 64 bytes are hashed first; empty keys and messages are
supported. Inner/outer prefixes and SHA256 state are real computations.
Output, key and message overlap checks cover the entire HMAC context,
including the outer state, not merely the embedded digest allocation.

Initialization and one-shot hashing wipe temporary key material and local
contexts. Finalization wipes its inner digest and outer temporary context;
the caller-owned streaming context remains caller-owned. The SHA256 adapter
also wipes its own temporary BearSSL context and serialized chaining state.
This does not claim that all dependency stack spills have been audited.

The ARM64 fixture checks all four function-pointer typedefs from the
original register_crypto.h without casts. Actual Cortex-A53 execution is
compared to Python hmac/hashlib for 49 key/message combinations in both
one-shot and split-update forms, including 65- and 131-byte keys. A fixed
known-answer vector is also checked. Negative cases cover uninitialized
state, alignment, null input/output and aliasing into the outer state.

These fixtures do not run original XNU consumers or registration. Native
KERNEL=1 object compilation is checked separately by mido-provider-audit.
The full provider, other algorithms, real startup execution and a linked
kernel remain required before changing the packaged image.
