# Experimental XNU digest and HMAC compatibility

mido_digest.c supplies MD5, SHA1, SHA384 and SHA512 descriptors alongside
the existing mido_sha256_info. General digest callbacks dispatch only among
these five exact descriptors, never silently changing an unknown algorithm.
MD5 and SHA1 are provided for legacy XNU ABI compatibility, not as a choice
for new security protocols.

All contexts retain the original ccdigest layout: processed bit count,
native-endian chaining words, pending block and pending byte count. The
adapter converts state through BearSSL public export/import APIs, including
the little-endian MD5 and big-endian SHA state serialization. There is no
opaque BearSSL context placed in an XNU allocation. SHA384/SHA512 support
the conservative 64-bit bit-count domain of this adapter; oversized input
panics instead of wrapping the length.

mido_hmac.c implements all four original HMAC callback signatures for the
same five descriptors. Actual digest/block sizes govern long-key hashing,
inner/outer pads, context-size/overlap checks and final output. Maximum
temporary capacity is 272 bytes for the SHA384/SHA512 HMAC context, not a
hard-coded SHA256 allocation. Temporary normalized keys, digest states and
inner results are wiped. Streaming context lifetime remains caller-owned.

The isolated fixture asserts all eight original callback typedefs and uses
the original enum values. Cortex-A53 tests compare one-shot and split-update
results against independent Python hashlib/hmac implementations, covering
padding boundaries and keys below/at/above both 64- and 128-byte blocks.
The six-argument HMAC call executes through the real ARM64 register ABI.
This remains isolated testing, not execution of original XNU consumers.

The native Actions audit compiles these adapters and all added BearSSL
dependency units against actual Xcode kernel headers. Source/object hashes
and original diagnostics are preserved in its report. Passing compilation
does not install a provider, fill cipher/RSA callbacks, or rebuild the XNU
image. Those integration gates remain open.
