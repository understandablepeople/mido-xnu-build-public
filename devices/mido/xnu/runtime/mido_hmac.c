#include "mido_hmac.h"
#include "mido_digest.h"

#if defined(KERNEL) && KERNEL
#include <kern/debug.h>
#else
extern void panic(const char *format, ...) __attribute__((noreturn));
#endif

_Static_assert(cchmac_ctx_size(64, 128) == 272, "XNU maximum HMAC context ABI changed");

static void erase(void *pointer, size_t length)
{
    volatile unsigned char *bytes = pointer;
    for (size_t index = 0; index < length; index++)
        bytes[index] = 0;
}

static void checked_context(const struct ccdigest_info *info, cchmac_ctx_t context)
{
    if (!mido_digest_supported(info) || !context || (uintptr_t)context % 8 ||
        (uintptr_t)context > UINTPTR_MAX - cchmac_di_size(info))
        panic("MIDO HMAC: unsupported digest or invalid context");
}

static void checked_buffer(const struct ccdigest_info *info, cchmac_ctx_t context, const void *buffer, size_t length)
{
    uintptr_t state = (uintptr_t)context;
    uintptr_t address = (uintptr_t)buffer;
    if ((!buffer && length) || length > UINTPTR_MAX - address ||
        (length && address < state + cchmac_di_size(info) && state < address + length))
        panic("MIDO HMAC: invalid or overlapping buffer");
}

void mido_hmac_init(const struct ccdigest_info *info, cchmac_ctx_t context, size_t key_length, const void *key)
{
    checked_context(info, context);
    checked_buffer(info, context, key, key_length);
    unsigned char block[128] = {0};
    if (key_length > info->block_size)
        mido_digest(info, key_length, key, block);
    else
        for (size_t index = 0; index < key_length; index++)
            block[index] = ((const unsigned char *)key)[index];
    ccdigest_ctx_decl(64, 128, outer);
    for (size_t index = 0; index < info->block_size; index++)
        block[index] ^= 0x5c;
    mido_digest_init(info, outer);
    mido_digest_update(info, outer, info->block_size, block);
    erase(context, cchmac_di_size(info));
    for (size_t index = 0; index < info->state_size; index++)
        cchmac_ostate8(info, context)[index] = ccdigest_state_u8(info, outer)[index];
    for (size_t index = 0; index < info->block_size; index++)
        block[index] ^= 0x5c ^ 0x36;
    mido_digest_init(info, cchmac_digest_ctx(info, context));
    mido_digest_update(info, cchmac_digest_ctx(info, context), info->block_size, block);
    erase(block, sizeof(block));
    erase(outer, ccdigest_di_size(info));
}

void mido_hmac_update(const struct ccdigest_info *info, cchmac_ctx_t context, size_t length, const void *input)
{
    checked_context(info, context);
    checked_buffer(info, context, input, length);
    if (cchmac_nbits(info, context) < info->block_size * 8)
        panic("MIDO HMAC: context is not initialized");
    mido_digest_update(info, cchmac_digest_ctx(info, context), length, input);
}

void mido_hmac_final(const struct ccdigest_info *info, cchmac_ctx_t context, unsigned char *output)
{
    checked_context(info, context);
    checked_buffer(info, context, output, info->output_size);
    if (cchmac_nbits(info, context) < info->block_size * 8)
        panic("MIDO HMAC: context is not initialized");
    unsigned char inner[64];
    ccdigest_ctx_decl(64, 128, outer);
    mido_digest_final(info, cchmac_digest_ctx(info, context), inner);
    mido_digest_init(info, outer);
    for (size_t index = 0; index < info->state_size; index++)
        ccdigest_state_u8(info, outer)[index] = cchmac_ostate8(info, context)[index];
    ccdigest_nbits(info, outer) = info->block_size * 8;
    mido_digest_update(info, outer, info->output_size, inner);
    mido_digest_final(info, outer, output);
    erase(inner, sizeof(inner));
    erase(outer, ccdigest_di_size(info));
}

void mido_hmac(const struct ccdigest_info *info, size_t key_length, const void *key,
                      size_t length, const void *input, unsigned char *output)
{
    cchmac_ctx_decl(64, 128, context);
    mido_hmac_init(info, context, key_length, key);
    mido_hmac_update(info, context, length, input);
    mido_hmac_final(info, context, output);
    erase(context, cchmac_di_size(info));
}
