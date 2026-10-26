#include "mido_aes_gcm.h"
#include <bearssl_aead.h>
#include <corecrypto/cc_error.h>

#define MIDO_GCM_MAGIC UINT32_C(0x4d47434d)
#define MIDO_GCM_MAX_DATA ((UINT64_C(1) << 36) - 32)

enum mido_gcm_phase { NEED_IV = 1, AAD = 2, DATA = 3, FINAL = 4 };

struct mido_gcm_context {
    br_aes_ct_ctr_keys key;
    br_gcm_context gcm;
    uintptr_t owner;
    uint64_t aad_length;
    uint64_t data_length;
    unsigned char nonce[12];
    uint32_t magic;
    uint32_t phase;
    uint32_t decrypt;
    uint32_t managed;
} __attribute__((aligned(16)));

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

static int state_valid(const struct mido_gcm_context *state)
{
    return range_valid(state, sizeof(*state)) && (uintptr_t)state % 16 == 0 &&
           state->magic == MIDO_GCM_MAGIC && state->owner == (uintptr_t)state &&
           state->phase >= NEED_IV && state->phase <= FINAL && state->decrypt <= 1 && state->managed <= 1 &&
           state->aad_length <= UINT64_MAX / 8 && state->data_length <= MIDO_GCM_MAX_DATA;
}

static int external(const struct mido_gcm_context *state, const void *pointer, size_t length)
{
    return range_valid(pointer, length) && !overlap(state, sizeof(*state), pointer, length);
}

static int initialize(const struct ccmode_gcm *mode, ccgcm_ctx *context, size_t key_length, const void *key)
{
    struct mido_gcm_context *state = (void *)context;
    if (!range_valid(state, sizeof(*state)) || (uintptr_t)state % 16) return CCERR_PARAMETER;
    if ((mode != &mido_aes_gcm_encrypt && mode != &mido_aes_gcm_decrypt) ||
        (key_length != 16 && key_length != 24 && key_length != 32) || !external(state, key, key_length)) {
        erase(state, sizeof(*state));
        return CCERR_PARAMETER;
    }
    erase(state, sizeof(*state));
    br_aes_ct_ctr_init(&state->key, key, key_length);
    br_gcm_init(&state->gcm, &state->key.vtable, br_ghash_ctmul32);
    state->owner = (uintptr_t)state;
    state->magic = MIDO_GCM_MAGIC;
    state->phase = NEED_IV;
    state->decrypt = mode == &mido_aes_gcm_decrypt;
    return CCERR_OK;
}

static int set_iv(ccgcm_ctx *context, size_t length, const void *iv)
{
    struct mido_gcm_context *state = (void *)context;
    if (!state_valid(state) || state->managed || state->phase != NEED_IV || !length ||
        length > UINT64_MAX / 8 || !external(state, iv, length)) return CCERR_PARAMETER;
    br_gcm_reset(&state->gcm, iv, length);
    state->phase = AAD;
    return CCERR_OK;
}

static int authenticate(ccgcm_ctx *context, size_t length, const void *input)
{
    struct mido_gcm_context *state = (void *)context;
    if (!state_valid(state) || state->phase != AAD || !external(state, input, length)) return CCERR_PARAMETER;
    if (length > UINT64_MAX / 8 - state->aad_length) return CCERR_OVERFLOW;
    if (length) br_gcm_aad_inject(&state->gcm, input, length);
    state->aad_length += length;
    return CCERR_OK;
}

static int transform(ccgcm_ctx *context, size_t length, const void *input, void *output)
{
    struct mido_gcm_context *state = (void *)context;
    if (!state_valid(state) || (state->phase != AAD && state->phase != DATA) ||
        !external(state, input, length) || !external(state, output, length) ||
        (input != output && overlap(input, length, output, length))) return CCERR_PARAMETER;
    if (length > MIDO_GCM_MAX_DATA - state->data_length) return CCERR_OVERFLOW;
    if (state->phase == AAD) br_gcm_flip(&state->gcm);
    state->phase = DATA;
    const unsigned char *source = input;
    unsigned char *destination = output;
    for (size_t index = 0; index < length; index++) destination[index] = source[index];
    if (length) br_gcm_run(&state->gcm, !state->decrypt, output, length);
    state->data_length += length;
    return CCERR_OK;
}

static int finalize(ccgcm_ctx *context, size_t length, void *tag)
{
    struct mido_gcm_context *state = (void *)context;
    if (!state_valid(state) || (state->phase != AAD && state->phase != DATA) ||
        (length != 4 && length != 8 && (length < 12 || length > 16)) ||
        !external(state, tag, length)) return CCERR_PARAMETER;
    unsigned char actual[16];
    if (state->phase == AAD) br_gcm_flip(&state->gcm);
    br_gcm_get_tag(&state->gcm, actual);
    unsigned char *provided = tag;
    unsigned int difference = 0;
    if (state->decrypt) {
        for (size_t index = 0; index < length; index++) difference |= provided[index] ^ actual[index];
    }
    for (size_t index = 0; index < length; index++) provided[index] = actual[index];
    erase(actual, sizeof(actual));
    state->phase = FINAL;
    return difference ? CCERR_INTEGRITY : CCERR_OK;
}

static int reset(ccgcm_ctx *context)
{
    struct mido_gcm_context *state = (void *)context;
    if (!state_valid(state)) return CCERR_PARAMETER;
    erase(&state->gcm, sizeof(state->gcm));
    br_gcm_init(&state->gcm, &state->key.vtable, br_ghash_ctmul32);
    state->aad_length = 0;
    state->data_length = 0;
    state->phase = NEED_IV;
    return CCERR_OK;
}

int mido_gcm_init_with_iv(const struct ccmode_gcm *mode, ccgcm_ctx *context, size_t key_length,
                          const void *key, const void *iv)
{
    struct mido_gcm_context *state = (void *)context;
    if (!range_valid(state, sizeof(*state)) || (uintptr_t)state % 16) return CCERR_PARAMETER;
    if (!external(state, iv, 12)) {
        erase(state, sizeof(*state));
        return CCERR_PARAMETER;
    }
    int result = initialize(mode, context, key_length, key);
    if (result) return result;
    const unsigned char *input = iv;
    for (size_t index = 0; index < 12; index++) state->nonce[index] = input[index];
    br_gcm_reset(&state->gcm, state->nonce, 12);
    state->phase = AAD;
    state->managed = 1;
    return CCERR_OK;
}

int mido_gcm_inc_iv(const struct ccmode_gcm *mode, ccgcm_ctx *context, void *iv)
{
    struct mido_gcm_context *state = (void *)context;
    if (!state_valid(state) || !state->managed || state->phase != NEED_IV ||
        mode != (state->decrypt ? &mido_aes_gcm_decrypt : &mido_aes_gcm_encrypt) ||
        !external(state, iv, 12)) return CCERR_PARAMETER;
    unsigned int nonmax = 0;
    for (size_t index = 4; index < 12; index++) nonmax |= state->nonce[index] ^ 255;
    if (!nonmax) return CCERR_OVERFLOW;
    unsigned int carry = 1;
    for (size_t index = 12; index > 4; index--) {
        unsigned int sum = state->nonce[index - 1] + carry;
        state->nonce[index - 1] = (unsigned char)sum;
        carry = sum >> 8;
    }
    unsigned char *output = iv;
    for (size_t index = 0; index < 12; index++) output[index] = state->nonce[index];
    br_gcm_reset(&state->gcm, state->nonce, 12);
    state->phase = AAD;
    return CCERR_OK;
}

const struct ccmode_gcm mido_aes_gcm_encrypt = {
    .size = sizeof(struct mido_gcm_context), .encdec = CCMODE_GCM_ENCRYPTOR, .block_size = 1,
    .init = initialize, .set_iv = set_iv, .gmac = authenticate, .gcm = transform,
    .finalize = finalize, .reset = reset, .custom = NULL,
};

const struct ccmode_gcm mido_aes_gcm_decrypt = {
    .size = sizeof(struct mido_gcm_context), .encdec = CCMODE_GCM_DECRYPTOR, .block_size = 1,
    .init = initialize, .set_iv = set_iv, .gmac = authenticate, .gcm = transform,
    .finalize = finalize, .reset = reset, .custom = NULL,
};
