#include "mido_aes_xts.h"
#include "mido_aes_cbc.h"
#include <corecrypto/cc_error.h>
#include <libkern/crypto/aes.h>
#include <libkern/crypto/aesxts.h>

#if defined(KERNEL) && KERNEL
#include <kern/debug.h>
#else
extern void panic(const char *format, ...) __attribute__((noreturn));
#endif

#define MIDO_XTS_MAGIC UINT32_C(0x4d585453)
#define MIDO_XTS_TWEAK_MAGIC UINT32_C(0x4d585454)
#define MIDO_XTS_MAX_BLOCKS ((size_t)1 << 20)

struct mido_xts_context {
    aes_encrypt_ctx data_key;
    aes_encrypt_ctx tweak_key;
    uint32_t magic;
    uint32_t decrypt;
};

struct mido_xts_tweak {
    unsigned char value[16];
    size_t blocks;
    uint32_t magic;
} __attribute__((aligned(16)));

_Static_assert(sizeof(struct mido_xts_context) <= sizeof(((symmetric_xts *)0)->enc), "XTS encrypt allocation");
_Static_assert(sizeof(struct mido_xts_context) <= sizeof(((symmetric_xts *)0)->dec), "XTS decrypt allocation");

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

static int state_valid(const struct mido_xts_context *state)
{
    return range_valid(state, sizeof(*state)) && (uintptr_t)state % 16 == 0 &&
           state->magic == MIDO_XTS_MAGIC && state->decrypt <= 1;
}

static int initialize(const struct ccmode_xts *mode, ccxts_ctx *context, size_t key_length,
                      const void *data_key, const void *tweak_key)
{
    struct mido_xts_context *state = (void *)context;
    if (!range_valid(state, sizeof(*state)) || (uintptr_t)state % 16) return CCERR_PARAMETER;
    if ((mode != &mido_aes_xts_encrypt && mode != &mido_aes_xts_decrypt) ||
        (key_length != 16 && key_length != 32) || !range_valid(data_key, key_length) ||
        !range_valid(tweak_key, key_length) || overlap(state, sizeof(*state), data_key, key_length) ||
        overlap(state, sizeof(*state), tweak_key, key_length)) {
        erase(state, sizeof(*state));
        return CCERR_PARAMETER;
    }
    const unsigned char *first = data_key;
    const unsigned char *second = tweak_key;
    unsigned int difference = 0;
    for (size_t index = 0; index < key_length; index++) difference |= first[index] ^ second[index];
    erase(state, sizeof(*state));
    if (!difference) return CCERR_PARAMETER;
    state->decrypt = mode == &mido_aes_xts_decrypt;
    const struct ccmode_cbc *data_mode = state->decrypt ? &mido_aes_cbc_decrypt : &mido_aes_cbc_encrypt;
    int result = cccbc_init(data_mode, state->data_key.ctx, key_length, data_key);
    if (!result) result = cccbc_init(&mido_aes_cbc_encrypt, state->tweak_key.ctx, key_length, tweak_key);
    if (result) {
        erase(state, sizeof(*state));
        return result;
    }
    state->magic = MIDO_XTS_MAGIC;
    return CCERR_OK;
}

static void schedule(const struct ccmode_xts *mode, ccxts_ctx *context, size_t key_length,
                      const void *data_key, const void *tweak_key)
{
    if (initialize(mode, context, key_length, data_key, tweak_key)) panic("MIDO XTS: invalid key schedule");
}

static int set_tweak(const ccxts_ctx *context, ccxts_tweak *tweak, const void *iv)
{
    const struct mido_xts_context *state = (const void *)context;
    struct mido_xts_tweak *current = (void *)tweak;
    if (!state_valid(state) || !range_valid(current, sizeof(*current)) || (uintptr_t)current % 16 ||
        !range_valid(iv, 16) || overlap(state, sizeof(*state), current, sizeof(*current)) ||
        overlap(state, sizeof(*state), iv, 16) || overlap(current, sizeof(*current), iv, 16))
        return CCERR_PARAMETER;
    cccbc_iv_decl(16, zero_iv);
    erase(zero_iv, 16);
    erase(current, sizeof(*current));
    int result = mido_aes_cbc_encrypt.cbc(state->tweak_key.ctx, zero_iv, 1, iv, current->value);
    erase(zero_iv, 16);
    if (result) return result;
    current->magic = MIDO_XTS_TWEAK_MAGIC;
    return CCERR_OK;
}

static void *transform(const ccxts_ctx *context, ccxts_tweak *tweak, size_t blocks,
                       const void *input, void *output, uint32_t decrypt)
{
    const struct mido_xts_context *state = (const void *)context;
    struct mido_xts_tweak *current = (void *)tweak;
    if (!state_valid(state) || state->decrypt != decrypt || !range_valid(current, sizeof(*current)) ||
        (uintptr_t)current % 16 || overlap(state, sizeof(*state), current, sizeof(*current)) ||
        current->magic != MIDO_XTS_TWEAK_MAGIC || current->blocks > MIDO_XTS_MAX_BLOCKS ||
        blocks > MIDO_XTS_MAX_BLOCKS - current->blocks) panic("MIDO XTS: invalid state or data-unit length");
    size_t length = blocks * 16;
    if (!range_valid(input, length) || !range_valid(output, length) ||
        overlap(state, sizeof(*state), input, length) || overlap(state, sizeof(*state), output, length) ||
        overlap(current, sizeof(*current), input, length) || overlap(current, sizeof(*current), output, length) ||
        (input != output && overlap(input, length, output, length))) panic("MIDO XTS: invalid buffers");
    const unsigned char *source = input;
    unsigned char *destination = output;
    const struct ccmode_cbc *mode = decrypt ? &mido_aes_cbc_decrypt : &mido_aes_cbc_encrypt;
    for (size_t block = 0; block < blocks; block++) {
        unsigned char value[16];
        cccbc_iv_decl(16, zero_iv);
        erase(zero_iv, 16);
        for (size_t index = 0; index < 16; index++) value[index] = source[block * 16 + index] ^ current->value[index];
        int result = mode->cbc(state->data_key.ctx, zero_iv, 1, value, value);
        erase(zero_iv, 16);
        if (result) {
            erase(value, 16);
            panic("MIDO XTS: invalid AES key state");
        }
        for (size_t index = 0; index < 16; index++) destination[block * 16 + index] = value[index] ^ current->value[index];
        erase(value, 16);
        unsigned int carry = 0;
        for (size_t index = 0; index < 16; index++) {
            unsigned int shifted = ((unsigned int)current->value[index] << 1) | carry;
            current->value[index] = (unsigned char)shifted;
            carry = shifted >> 8;
        }
        current->value[0] ^= (unsigned char)(0x87 & (0 - carry));
    }
    current->blocks += blocks;
    return tweak;
}

static void *encrypt(const ccxts_ctx *context, ccxts_tweak *tweak, size_t blocks, const void *input, void *output)
{
    return transform(context, tweak, blocks, input, output, 0);
}

static void *decrypt(const ccxts_ctx *context, ccxts_tweak *tweak, size_t blocks, const void *input, void *output)
{
    return transform(context, tweak, blocks, input, output, 1);
}

const struct ccmode_xts mido_aes_xts_encrypt = {
    .size = sizeof(struct mido_xts_context), .tweak_size = sizeof(struct mido_xts_tweak), .block_size = 16,
    .init = initialize, .key_sched = schedule, .set_tweak = set_tweak, .xts = encrypt,
    .custom = NULL, .custom1 = NULL, .impl = CC_IMPL_UNKNOWN,
};

const struct ccmode_xts mido_aes_xts_decrypt = {
    .size = sizeof(struct mido_xts_context), .tweak_size = sizeof(struct mido_xts_tweak), .block_size = 16,
    .init = initialize, .key_sched = schedule, .set_tweak = set_tweak, .xts = decrypt,
    .custom = NULL, .custom1 = NULL, .impl = CC_IMPL_UNKNOWN,
};
