#include "mido_aes_cbc.h"
#include <bearssl_block.h>
#include <corecrypto/cc_error.h>
#include <libkern/crypto/aes.h>

struct mido_aes_context {
    uint32_t magic;
    uint32_t decrypt;
    union {
        br_aes_ct_cbcenc_keys encrypt;
        br_aes_ct_cbcdec_keys decrypt;
    } key;
} __attribute__((aligned(16)));

_Static_assert(sizeof(struct mido_aes_context) <= sizeof(aes_encrypt_ctx), "AES encrypt allocation");
_Static_assert(sizeof(struct mido_aes_context) <= sizeof(aes_decrypt_ctx), "AES decrypt allocation");

#define MIDO_AES_MAGIC UINT32_C(0x4d414553)

static void erase(void *pointer, size_t length)
{
    volatile unsigned char *bytes = pointer;
    for (size_t index = 0; index < length; index++) bytes[index] = 0;
}

static int range_valid(const void *pointer, size_t length)
{
    return !length || (pointer && length <= UINTPTR_MAX - (uintptr_t)pointer);
}

static int overlap(const void *first, size_t first_length, const void *second, size_t second_length)
{
    if (!first_length || !second_length) return 0;
    return (uintptr_t)first < (uintptr_t)second + second_length &&
           (uintptr_t)second < (uintptr_t)first + first_length;
}

static int initialize(const struct ccmode_cbc *mode, cccbc_ctx *context, size_t key_length, const void *key)
{
    if (!range_valid(context, sizeof(struct mido_aes_context)) || (uintptr_t)context % 16)
        return CCERR_PARAMETER;
    struct mido_aes_context *state = (void *)context;
    if ((mode != &mido_aes_cbc_encrypt && mode != &mido_aes_cbc_decrypt) ||
        (key_length != 16 && key_length != 24 && key_length != 32) || !range_valid(key, key_length) ||
        overlap(context, sizeof(*state), key, key_length)) {
        erase(state, sizeof(*state));
        return CCERR_PARAMETER;
    }
    erase(state, sizeof(*state));
    state->decrypt = mode == &mido_aes_cbc_decrypt;
    if (state->decrypt) br_aes_ct_cbcdec_init(&state->key.decrypt, key, key_length);
    else br_aes_ct_cbcenc_init(&state->key.encrypt, key, key_length);
    state->magic = MIDO_AES_MAGIC;
    return CCERR_OK;
}

static int transform(const cccbc_ctx *context, cccbc_iv *iv, size_t blocks,
                     const void *input, void *output, uint32_t decrypt)
{
    if (!range_valid(context, sizeof(struct mido_aes_context)) || (uintptr_t)context % 16 ||
        !range_valid(iv, 16) || (uintptr_t)iv % 16 || blocks > SIZE_MAX / 16)
        return CCERR_PARAMETER;
    const struct mido_aes_context *state = (const void *)context;
    if (state->magic != MIDO_AES_MAGIC || state->decrypt != decrypt) return CCERR_PARAMETER;
    size_t length = blocks * 16;
    if (!range_valid(input, length) || !range_valid(output, length) ||
        overlap(context, sizeof(*state), iv, 16) ||
        overlap(context, sizeof(*state), input, length) || overlap(context, sizeof(*state), output, length) ||
        overlap(iv, 16, input, length) || overlap(iv, 16, output, length) ||
        (input != output && overlap(input, length, output, length))) return CCERR_PARAMETER;
    unsigned char *destination = output;
    const unsigned char *source = input;
    for (size_t index = 0; index < length; index++) destination[index] = source[index];
    if (length) {
        if (decrypt) br_aes_ct_cbcdec_run(&state->key.decrypt, iv, output, length);
        else br_aes_ct_cbcenc_run(&state->key.encrypt, iv, output, length);
    }
    return CCERR_OK;
}

static int encrypt(const cccbc_ctx *context, cccbc_iv *iv, size_t blocks, const void *input, void *output)
{
    return transform(context, iv, blocks, input, output, 0);
}

static int decrypt(const cccbc_ctx *context, cccbc_iv *iv, size_t blocks, const void *input, void *output)
{
    return transform(context, iv, blocks, input, output, 1);
}

const struct ccmode_cbc mido_aes_cbc_encrypt = {
    .size = sizeof(struct mido_aes_context), .block_size = 16,
    .init = initialize, .cbc = encrypt, .custom = NULL,
};

const struct ccmode_cbc mido_aes_cbc_decrypt = {
    .size = sizeof(struct mido_aes_context), .block_size = 16,
    .init = initialize, .cbc = decrypt, .custom = NULL,
};
