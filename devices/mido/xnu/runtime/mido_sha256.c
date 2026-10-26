#include "mido_sha256.h"
#include <bearssl_hash.h>

#if defined(KERNEL) && KERNEL
#include <kern/debug.h>
#else
extern void panic(const char *format, ...) __attribute__((noreturn));
#endif

static const uint32_t initial_state[8] = {
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
};

static void erase(void *pointer, size_t length)
{
    volatile unsigned char *bytes = pointer;
    for (size_t index = 0; index < length; index++)
        bytes[index] = 0;
}

static void export_words(const uint32_t *words, unsigned char bytes[32])
{
    for (size_t index = 0; index < 8; index++)
        for (size_t byte = 0; byte < 4; byte++)
            bytes[index * 4 + byte] = (unsigned char)(words[index] >> (24 - byte * 8));
}

static void import_words(uint32_t *words, const unsigned char bytes[32])
{
    for (size_t index = 0; index < 8; index++) {
        words[index] = 0;
        for (size_t byte = 0; byte < 4; byte++)
            words[index] = (words[index] << 8) | bytes[index * 4 + byte];
    }
}

static void compress(ccdigest_state_t state, size_t blocks, const void *input)
{
    if (!state || (uintptr_t)state % 8 || (!input && blocks) || blocks > SIZE_MAX / 64)
        panic("MIDO SHA256: invalid compression arguments");
    br_sha256_context hash;
    unsigned char serialized[32];
    export_words(ccdigest_u32(state), serialized);
    br_sha256_init(&hash);
    br_sha256_set_state(&hash, serialized, 0);
    br_sha256_update(&hash, input, blocks * 64);
    br_sha256_state(&hash, serialized);
    import_words(ccdigest_u32(state), serialized);
    erase(&hash, sizeof(hash));
    erase(serialized, sizeof(serialized));
}

const struct ccdigest_info mido_sha256_info = {
    .output_size = 32,
    .state_size = 32,
    .block_size = 64,
    .oid_size = 11,
    .oid = CC_DIGEST_OID_SHA256,
    .initial_state = initial_state,
    .compress = compress,
    .final = mido_sha256_final,
    .impl = 0,
};

_Static_assert(sizeof(void *) == 8, "MIDO SHA256 requires ARM64 ABI");
_Static_assert(ccdigest_ctx_size(32, 64) == 108, "SHA256 context ABI changed");

static void checked_context(const struct ccdigest_info *info, ccdigest_ctx_t context)
{
    if (info != &mido_sha256_info || !context || (uintptr_t)context % 8)
        panic("MIDO SHA256: unsupported digest or invalid context");
}

static void checked_buffer(ccdigest_ctx_t context, const void *buffer, size_t length)
{
    uintptr_t address = (uintptr_t)buffer;
    uintptr_t state = (uintptr_t)context;
    size_t context_size = ccdigest_di_size(&mido_sha256_info);
    if ((!buffer && length) || length > UINTPTR_MAX - address || context_size > UINTPTR_MAX - state ||
        (length && address < state + context_size && state < address + length))
        panic("MIDO SHA256: invalid or overlapping buffer");
}

void mido_sha256_init(const struct ccdigest_info *info, ccdigest_ctx_t context)
{
    checked_context(info, context);
    ccdigest_nbits(info, context) = 0;
    ccdigest_num(info, context) = 0;
    for (size_t index = 0; index < 8; index++)
        ccdigest_state_u32(info, context)[index] = initial_state[index];
    for (size_t index = 0; index < 64; index++)
        ccdigest_data(info, context)[index] = 0;
}

void mido_sha256_update(const struct ccdigest_info *info, ccdigest_ctx_t context, size_t length, const void *input)
{
    checked_context(info, context);
    checked_buffer(context, input, length);
    uint64_t bits = ccdigest_nbits(info, context);
    unsigned int buffered = ccdigest_num(info, context);
    if (buffered >= 64 || bits % 512 || length > UINT64_MAX / 8 - bits / 8 - buffered)
        panic("MIDO SHA256: invalid state or message length");
    const unsigned char *bytes = input;
    while (length) {
        if (!buffered && length >= 64) {
            size_t blocks = length / 64;
            compress(ccdigest_state(info, context), blocks, bytes);
            size_t consumed = blocks * 64;
            bits += consumed * 8;
            bytes += consumed;
            length -= consumed;
        } else {
            size_t chunk = length < 64 - buffered ? length : 64 - buffered;
            for (size_t index = 0; index < chunk; index++)
                ccdigest_data(info, context)[buffered + index] = bytes[index];
            bytes += chunk;
            length -= chunk;
            buffered += (unsigned int)chunk;
            if (buffered == 64) {
                compress(ccdigest_state(info, context), 1, ccdigest_data(info, context));
                bits += 512;
                buffered = 0;
            }
        }
    }
    ccdigest_nbits(info, context) = bits;
    ccdigest_num(info, context) = buffered;
}

void mido_sha256_final(const struct ccdigest_info *info, ccdigest_ctx_t context, unsigned char *output)
{
    checked_context(info, context);
    checked_buffer(context, output, 32);
    uint64_t bits = ccdigest_nbits(info, context);
    unsigned int buffered = ccdigest_num(info, context);
    if (buffered >= 64 || bits % 512)
        panic("MIDO SHA256: invalid final state");
    br_sha256_context hash;
    unsigned char serialized[32];
    export_words(ccdigest_state_u32(info, context), serialized);
    br_sha256_init(&hash);
    br_sha256_set_state(&hash, serialized, bits / 8);
    br_sha256_update(&hash, ccdigest_data(info, context), buffered);
    br_sha256_out(&hash, output);
    erase(&hash, sizeof(hash));
    erase(serialized, sizeof(serialized));
}

void mido_sha256_digest(const struct ccdigest_info *info, size_t length, const void *input, void *output)
{
    ccdigest_ctx_decl(32, 64, context);
    mido_sha256_init(info, context);
    mido_sha256_update(info, context, length, input);
    mido_sha256_final(info, context, output);
    volatile unsigned char *bytes = (volatile unsigned char *)context;
    for (size_t index = 0; index < ccdigest_di_size(info); index++)
        bytes[index] = 0;
}

void mido_sha256_final_callback(const struct ccdigest_info *info, ccdigest_ctx_t context, void *output)
{
    mido_sha256_final(info, context, output);
}
