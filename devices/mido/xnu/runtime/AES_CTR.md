# Experimental typed AES-CTR adapter

mido_aes_ctr.c supplies the original ccmode_ctr descriptor with byte-sized
updates and a 16-byte AES block size. It reuses the tested BearSSL-backed
CBC encryption descriptor with a fresh zero IV for each counter block;
this computes the single-block AES primitive, not chained CBC encryption.
No new cipher algorithm or CPU-specific assembly is introduced.

The counter is a big-endian 128-bit integer. Partial-block keystream survives
across calls; consumed bytes are wiped. setctr discards buffered bytes and
resets exhaustion without changing the key. This operation is explicit:
the caller remains responsible for never reusing a key/counter pair.
The adapter adds no padding or authentication and must not be treated as
an authenticated encryption protocol.

Before changing state or output, the implementation validates all ranges,
alignment, exact/disjoint buffer overlap and context ownership, then checks
whether every new counter block fits before 128-bit wraparound. A request
that would wrap returns CCERR_OVERFLOW without partial output. The final
counter value may be used once and its remaining buffered bytes consumed;
later requests fail closed. Zero-length updates remain no-ops.
Invalid initialization wipes the valid context allocation, preventing old
key reuse. The caller owns final context erasure and accessible storage.

Cortex-A53 tests use original ccctr_init/update and typed setctr callbacks.
They compare all AES key sizes, odd-sized streaming chunks, both directions,
exact in-place buffers, explicit counter resets and low-32-bit carry with
an independent cryptography backend. Both backends are checked against
the NIST SP 800-38A example. Additional tests check full 128-bit exhaustion,
rejected-request atomicity, key/IV/context aliases, null pointers, range
overflow and invalid initialization/reset. The report records reference
version, original header hashes and every actual compilation command.

This descriptor is not registered in XNU or linked into the image. Native
compilation, full provider coverage, real startup ordering and execution of
the rebuilt kernel remain separate integration gates. No phone is accessed.
