#include "mido_hmac_sha256.h"
#include "mido_sha256.h"

#if defined(KERNEL) && KERNEL
#include <kern/debug.h>
#else
extern void panic(const char *format, ...) __attribute__((noreturn));
#endif

_Static_assert(cchmac_ctx_size(32, 64) == 144, "XNU HMAC SHA256 context ABI changed");

static void erase(void *pointer, size_t length)
{
    volatile unsigned char *bytes = pointer;
    for (size_t index = 0; index < length; index++)
        bytes[index] = 0;
}

static void checked_context(const struct ccdigest_info *info, cchmac_ctx_t context)
{
    if (info != &mido_sha256_info || !context || (uintptr_t)context % 8 ||
        (uintptr_t)context > UINTPTR_MAX - cchmac_ctx_size(32, 64))
        panic("MIDO HMAC: unsupported digest or invalid context");
}

static void checked_buffer(cchmac_ctx_t context, const void *buffer, size_t length)
{
    uintptr_t state = (uintptr_t)context;
    uintptr_t address = (uintptr_t)buffer;
    if ((!buffer && length) || length > UINTPTR_MAX - address ||
        (length && address < state + cchmac_ctx_size(32, 64) && state < address + length))
        panic("MIDO HMAC: invalid or overlapping buffer");
}

void mido_hmac_sha256_init(const struct ccdigest_info *info, cchmac_ctx_t context, size_t key_length, const void *key)
{
    checked_context(info, context);
    checked_buffer(context, key, key_length);
    unsigned char block[64] = {0};
    if (key_length > sizeof(block))
        mido_sha256_digest(info, key_length, key, block);
    else
        for (size_t index = 0; index < key_length; index++)
            block[index] = ((const unsigned char *)key)[index];
    ccdigest_ctx_decl(32, 64, outer);
    for (size_t index = 0; index < sizeof(block); index++)
        block[index] ^= 0x5c;
    mido_sha256_init(info, outer);
    mido_sha256_update(info, outer, sizeof(block), block);
    erase(context, cchmac_di_size(info));
    for (size_t index = 0; index < 8; index++)
        cchmac_ostate32(info, context)[index] = ccdigest_state_u32(info, outer)[index];
    for (size_t index = 0; index < sizeof(block); index++)
        block[index] ^= 0x5c ^ 0x36;
    mido_sha256_init(info, cchmac_digest_ctx(info, context));
    mido_sha256_update(info, cchmac_digest_ctx(info, context), sizeof(block), block);
    erase(block, sizeof(block));
    erase(outer, ccdigest_di_size(info));
}

void mido_hmac_sha256_update(const struct ccdigest_info *info, cchmac_ctx_t context, size_t length, const void *input)
{
    checked_context(info, context);
    checked_buffer(context, input, length);
    if (cchmac_nbits(info, context) < 512)
        panic("MIDO HMAC: context is not initialized");
    mido_sha256_update(info, cchmac_digest_ctx(info, context), length, input);
}

void mido_hmac_sha256_final(const struct ccdigest_info *info, cchmac_ctx_t context, unsigned char *output)
{
    checked_context(info, context);
    checked_buffer(context, output, 32);
    if (cchmac_nbits(info, context) < 512)
        panic("MIDO HMAC: context is not initialized");
    unsigned char inner[32];
    ccdigest_ctx_decl(32, 64, outer);
    mido_sha256_final(info, cchmac_digest_ctx(info, context), inner);
    mido_sha256_init(info, outer);
    for (size_t index = 0; index < 8; index++)
        ccdigest_state_u32(info, outer)[index] = cchmac_ostate32(info, context)[index];
    ccdigest_nbits(info, outer) = 512;
    mido_sha256_update(info, outer, sizeof(inner), inner);
    mido_sha256_final(info, outer, output);
    erase(inner, sizeof(inner));
    erase(outer, ccdigest_di_size(info));
}

void mido_hmac_sha256(const struct ccdigest_info *info, size_t key_length, const void *key,
                      size_t length, const void *input, unsigned char *output)
{
    cchmac_ctx_decl(32, 64, context);
    mido_hmac_sha256_init(info, context, key_length, key);
    mido_hmac_sha256_update(info, context, length, input);
    mido_hmac_sha256_final(info, context, output);
    erase(context, cchmac_di_size(info));
}
