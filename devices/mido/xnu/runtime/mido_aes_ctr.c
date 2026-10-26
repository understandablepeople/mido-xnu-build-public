#include "mido_aes_ctr.h"
#include "mido_aes_cbc.h"
#include <corecrypto/cc_error.h>
#include <libkern/crypto/aes.h>

#define MIDO_CTR_MAGIC UINT32_C(0x4d435452)

struct mido_ctr_context {
    aes_encrypt_ctx key;
    unsigned char counter[16];
    unsigned char stream[16];
    size_t used;
    uint32_t magic;
    uint32_t exhausted;
};

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

static int state_valid(const struct mido_ctr_context *state)
{
    return range_valid(state, sizeof(*state)) && (uintptr_t)state % 16 == 0 &&
           state->magic == MIDO_CTR_MAGIC && state->used <= 16 && state->exhausted <= 1;
}

static int initialize(const struct ccmode_ctr *mode, ccctr_ctx *context, size_t key_length,
                      const void *key, const void *iv)
{
    struct mido_ctr_context *state = (void *)context;
    if (!range_valid(state, sizeof(*state)) || (uintptr_t)state % 16) return CCERR_PARAMETER;
    if (mode != &mido_aes_ctr_crypt || !range_valid(key, key_length) || !range_valid(iv, 16) ||
        overlap(state, sizeof(*state), key, key_length) || overlap(state, sizeof(*state), iv, 16)) {
        erase(state, sizeof(*state));
        return CCERR_PARAMETER;
    }
    erase(state, sizeof(*state));
    int result = cccbc_init(&mido_aes_cbc_encrypt, state->key.ctx, key_length, key);
    if (result) {
        erase(state, sizeof(*state));
        return result;
    }
    const unsigned char *counter = iv;
    for (size_t index = 0; index < 16; index++) state->counter[index] = counter[index];
    state->used = 16;
    state->magic = MIDO_CTR_MAGIC;
    return CCERR_OK;
}

static int set_counter(const struct ccmode_ctr *mode, ccctr_ctx *context, const void *counter)
{
    struct mido_ctr_context *state = (void *)context;
    if (mode != &mido_aes_ctr_crypt || !state_valid(state) || !range_valid(counter, 16) ||
        overlap(state, sizeof(*state), counter, 16)) return CCERR_PARAMETER;
    const unsigned char *input = counter;
    for (size_t index = 0; index < 16; index++) state->counter[index] = input[index];
    erase(state->stream, sizeof(state->stream));
    state->used = 16;
    state->exhausted = 0;
    return CCERR_OK;
}

static int counter_available(const struct mido_ctr_context *state, size_t blocks)
{
    if (!blocks) return 1;
    if (state->exhausted) return 0;
    size_t addend = blocks - 1;
    unsigned int carry = 0;
    for (size_t index = 16; index > 0; index--) {
        unsigned int sum = state->counter[index - 1] + (addend & 255) + carry;
        addend >>= 8;
        carry = sum >> 8;
    }
    return carry == 0 && addend == 0;
}

static int transform(ccctr_ctx *context, size_t length, const void *input, void *output)
{
    struct mido_ctr_context *state = (void *)context;
    if (!state_valid(state) || !range_valid(input, length) || !range_valid(output, length) ||
        overlap(state, sizeof(*state), input, length) || overlap(state, sizeof(*state), output, length) ||
        (input != output && overlap(input, length, output, length))) return CCERR_PARAMETER;
    size_t buffered = 16 - state->used;
    size_t needed = length > buffered ? length - buffered : 0;
    size_t blocks = needed / 16 + (needed % 16 != 0);
    if (!counter_available(state, blocks)) return CCERR_OVERFLOW;
    const unsigned char *source = input;
    unsigned char *destination = output;
    for (size_t index = 0; index < length; index++) {
        if (state->used == 16) {
            cccbc_iv_decl(16, zero_iv);
            erase(zero_iv, 16);
            int result = cccbc_update(&mido_aes_cbc_encrypt, state->key.ctx, zero_iv, 1,
                                      state->counter, state->stream);
            erase(zero_iv, 16);
            if (result) {
                erase(state, sizeof(*state));
                return result;
            }
            unsigned int carry = 1;
            for (size_t position = 16; position > 0; position--) {
                unsigned int sum = state->counter[position - 1] + carry;
                state->counter[position - 1] = (unsigned char)sum;
                carry = sum >> 8;
            }
            state->exhausted = carry;
            state->used = 0;
        }
        destination[index] = source[index] ^ state->stream[state->used];
        state->stream[state->used++] = 0;
    }
    return CCERR_OK;
}

const struct ccmode_ctr mido_aes_ctr_crypt = {
    .size = sizeof(struct mido_ctr_context), .block_size = 1, .ecb_block_size = 16,
    .init = initialize, .setctr = set_counter, .ctr = transform, .custom = NULL,
};
