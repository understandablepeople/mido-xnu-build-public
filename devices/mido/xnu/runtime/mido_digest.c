#include "mido_digest.h"
#include <bearssl_hash.h>

#if defined(KERNEL) && KERNEL
#include <kern/debug.h>
#else
extern void panic(const char *format, ...) __attribute__((noreturn));
#endif

static const uint32_t md5_initial[4] = {0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476};
static const uint32_t sha1_initial[5] = {0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0};
static const uint64_t sha384_initial[8] = {
    UINT64_C(0xcbbb9d5dc1059ed8), UINT64_C(0x629a292a367cd507), UINT64_C(0x9159015a3070dd17), UINT64_C(0x152fecd8f70e5939),
    UINT64_C(0x67332667ffc00b31), UINT64_C(0x8eb44a8768581511), UINT64_C(0xdb0c2e0d64f98fa7), UINT64_C(0x47b5481dbefa4fa4),
};
static const uint64_t sha512_initial[8] = {
    UINT64_C(0x6a09e667f3bcc908), UINT64_C(0xbb67ae8584caa73b), UINT64_C(0x3c6ef372fe94f82b), UINT64_C(0xa54ff53a5f1d36f1),
    UINT64_C(0x510e527fade682d1), UINT64_C(0x9b05688c2b3e6c1f), UINT64_C(0x1f83d9abfb41bd6b), UINT64_C(0x5be0cd19137e2179),
};

static const br_hash_class *implementation(const struct ccdigest_info *info)
{
    if (info == &mido_md5_info) return &br_md5_vtable;
    if (info == &mido_sha1_info) return &br_sha1_vtable;
    if (info == &mido_sha384_info) return &br_sha384_vtable;
    if (info == &mido_sha512_info) return &br_sha512_vtable;
    panic("MIDO digest: unsupported descriptor");
}

int mido_digest_supported(const struct ccdigest_info *info)
{
    return info == &mido_md5_info || info == &mido_sha1_info || info == &mido_sha256_info ||
           info == &mido_sha384_info || info == &mido_sha512_info;
}

static void erase(void *pointer, size_t length)
{
    volatile unsigned char *bytes = pointer;
    for (size_t index = 0; index < length; index++) bytes[index] = 0;
}

static void convert_state(const struct ccdigest_info *info, unsigned char *output, const unsigned char *input)
{
    size_t word = info->state_size == 64 ? 8 : 4;
    for (size_t index = 0; index < info->state_size; index++) {
        size_t source = info == &mido_md5_info ? index : (index / word) * word + word - 1 - index % word;
        output[index] = input[source];
    }
}

static void compress(const struct ccdigest_info *info, ccdigest_state_t state, size_t blocks, const void *input)
{
    const br_hash_class *hash_class = implementation(info);
    if (!state || (uintptr_t)state % 8 || (!input && blocks) || blocks > SIZE_MAX / info->block_size)
        panic("MIDO digest: invalid compression arguments");
    br_hash_compat_context hash;
    unsigned char serialized[64];
    convert_state(info, serialized, ccdigest_u8(state));
    hash_class->init(&hash.vtable);
    hash_class->set_state(&hash.vtable, serialized, 0);
    hash_class->update(&hash.vtable, input, blocks * info->block_size);
    hash_class->state(&hash.vtable, serialized);
    convert_state(info, ccdigest_u8(state), serialized);
    erase(&hash, sizeof(hash));
    erase(serialized, sizeof(serialized));
}

#define MIDO_COMPRESS(name) \
    static void name##_compress(ccdigest_state_t state, size_t blocks, const void *input) \
    { compress(&mido_##name##_info, state, blocks, input); }
MIDO_COMPRESS(md5)
MIDO_COMPRESS(sha1)
MIDO_COMPRESS(sha384)
MIDO_COMPRESS(sha512)

#define MIDO_DIGEST_INFO(name, output, state, block, oid_length, oid_value) \
    const struct ccdigest_info mido_##name##_info = { \
        .output_size = output, .state_size = state, .block_size = block, \
        .oid_size = oid_length, .oid = oid_value, .initial_state = name##_initial, \
        .compress = name##_compress, .final = mido_digest_final, .impl = 0, \
    }
MIDO_DIGEST_INFO(md5, 16, 16, 64, 10, CC_DIGEST_OID_MD5);
MIDO_DIGEST_INFO(sha1, 20, 20, 64, 7, CC_DIGEST_OID_SHA1);
MIDO_DIGEST_INFO(sha384, 48, 64, 128, 11, CC_DIGEST_OID_SHA384);
MIDO_DIGEST_INFO(sha512, 64, 64, 128, 11, CC_DIGEST_OID_SHA512);

static void checked_context(const struct ccdigest_info *info, ccdigest_ctx_t context)
{
    if (!mido_digest_supported(info) || !context || (uintptr_t)context % 8 ||
        (uintptr_t)context > UINTPTR_MAX - ccdigest_di_size(info))
        panic("MIDO digest: invalid context");
}

static void checked_buffer(const struct ccdigest_info *info, ccdigest_ctx_t context, const void *buffer, size_t length)
{
    uintptr_t address = (uintptr_t)buffer;
    uintptr_t state = (uintptr_t)context;
    if ((!buffer && length) || length > UINTPTR_MAX - address ||
        (length && address < state + ccdigest_di_size(info) && state < address + length))
        panic("MIDO digest: invalid or overlapping buffer");
}

void mido_digest_init(const struct ccdigest_info *info, ccdigest_ctx_t context)
{
    checked_context(info, context);
    if (info == &mido_sha256_info) { mido_sha256_init(info, context); return; }
    erase(context, ccdigest_di_size(info));
    for (size_t index = 0; index < info->state_size; index++)
        ccdigest_state_u8(info, context)[index] = ((const unsigned char *)info->initial_state)[index];
}

void mido_digest_update(const struct ccdigest_info *info, ccdigest_ctx_t context, size_t length, const void *input)
{
    checked_context(info, context);
    if (info == &mido_sha256_info) { mido_sha256_update(info, context, length, input); return; }
    checked_buffer(info, context, input, length);
    uint64_t bits = ccdigest_nbits(info, context);
    unsigned int buffered = ccdigest_num(info, context);
    if (buffered >= info->block_size || bits % (info->block_size * 8) ||
        length > UINT64_MAX / 8 - bits / 8 - buffered)
        panic("MIDO digest: invalid state or length");
    const unsigned char *bytes = input;
    while (length) {
        if (!buffered && length >= info->block_size) {
            size_t blocks = length / info->block_size;
            compress(info, ccdigest_state(info, context), blocks, bytes);
            size_t consumed = blocks * info->block_size;
            bits += consumed * 8;
            bytes += consumed;
            length -= consumed;
        } else {
            size_t available = info->block_size - buffered;
            size_t chunk = length < available ? length : available;
            for (size_t index = 0; index < chunk; index++)
                ccdigest_data(info, context)[buffered + index] = bytes[index];
            bytes += chunk;
            length -= chunk;
            buffered += (unsigned int)chunk;
            if (buffered == info->block_size) {
                compress(info, ccdigest_state(info, context), 1, ccdigest_data(info, context));
                bits += info->block_size * 8;
                buffered = 0;
            }
        }
    }
    ccdigest_nbits(info, context) = bits;
    ccdigest_num(info, context) = buffered;
}

void mido_digest_final(const struct ccdigest_info *info, ccdigest_ctx_t context, unsigned char *output)
{
    checked_context(info, context);
    if (info == &mido_sha256_info) { mido_sha256_final(info, context, output); return; }
    checked_buffer(info, context, output, info->output_size);
    uint64_t bits = ccdigest_nbits(info, context);
    unsigned int buffered = ccdigest_num(info, context);
    if (buffered >= info->block_size || bits % (info->block_size * 8))
        panic("MIDO digest: invalid final state");
    const br_hash_class *hash_class = implementation(info);
    br_hash_compat_context hash;
    unsigned char serialized[64];
    convert_state(info, serialized, ccdigest_state_u8(info, context));
    hash_class->init(&hash.vtable);
    hash_class->set_state(&hash.vtable, serialized, bits / 8);
    hash_class->update(&hash.vtable, ccdigest_data(info, context), buffered);
    hash_class->out(&hash.vtable, output);
    erase(&hash, sizeof(hash));
    erase(serialized, sizeof(serialized));
}

void mido_digest_final_callback(const struct ccdigest_info *info, ccdigest_ctx_t context, void *output)
{
    mido_digest_final(info, context, output);
}

void mido_digest(const struct ccdigest_info *info, size_t length, const void *input, void *output)
{
    ccdigest_ctx_decl(64, 128, context);
    mido_digest_init(info, context);
    mido_digest_update(info, context, length, input);
    mido_digest_final(info, context, output);
    erase(context, ccdigest_ctx_size(64, 128));
}
