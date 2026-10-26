#include "drbg.h"

_Static_assert(sizeof(struct mido_drbg) <= 256, "kmem random context limit");

static int overlaps(const void *first, size_t first_size, const void *second, size_t second_size)
{
    uintptr_t first_address = (uintptr_t)first;
    uintptr_t second_address = (uintptr_t)second;
    if (!first_size || !second_size)
        return 0;
    if (first_size > UINTPTR_MAX - first_address || second_size > UINTPTR_MAX - second_address)
        return 1;
    return first_address < second_address + second_size && second_address < first_address + first_size;
}

void mido_drbg_clear(struct mido_drbg *state)
{
    if (state) {
        volatile unsigned char *bytes = (volatile unsigned char *)state;
        for (size_t index = 0; index < sizeof(*state); index++)
            bytes[index] = 0;
    }
}

int mido_drbg_init(struct mido_drbg *state, const void *seed, size_t length)
{
    if (!state || !seed || length < 48 || length > MIDO_DRBG_MAX_REQUEST ||
        overlaps(state, sizeof(*state), seed, length))
        return MIDO_DRBG_INVALID;
    mido_drbg_clear(state);
    br_hmac_drbg_init(&state->generator, &br_sha256_vtable, seed, length);
    state->ready = 1;
    return MIDO_DRBG_OK;
}

int mido_drbg_reseed(struct mido_drbg *state, const void *seed, size_t length)
{
    if (!state || state->ready != 1 || !seed || length < 32 || length > MIDO_DRBG_MAX_REQUEST ||
        overlaps(state, sizeof(*state), seed, length))
        return MIDO_DRBG_INVALID;
    br_hmac_drbg_update(&state->generator, seed, length);
    state->generated = 0;
    return MIDO_DRBG_OK;
}

int mido_drbg_generate(struct mido_drbg *state, void *output, size_t length)
{
    if (!state || state->ready != 1 || (!output && length) || length > MIDO_DRBG_MAX_REQUEST ||
        overlaps(state, sizeof(*state), output, length))
        return MIDO_DRBG_INVALID;
    if (state->generated > MIDO_DRBG_RESEED_BYTES || length > MIDO_DRBG_RESEED_BYTES - state->generated)
        return MIDO_DRBG_RESEED_REQUIRED;
    if (length) {
        br_hmac_drbg_generate(&state->generator, output, length);
        state->generated += length;
    }
    return MIDO_DRBG_OK;
}

int mido_drbg_uniform(struct mido_drbg *state, uint64_t bound, uint64_t *output)
{
    unsigned char bytes[8];
    if (!state || !output || !bound || overlaps(state, sizeof(*state), output, sizeof(*output)))
        return MIDO_DRBG_INVALID;
    uint64_t threshold = (UINT64_C(0) - bound) % bound;
    for (unsigned int attempt = 0; attempt < 128; attempt++) {
        int status = mido_drbg_generate(state, bytes, sizeof(bytes));
        uint64_t value = 0;
        if (status != MIDO_DRBG_OK)
            return status;
        for (unsigned int index = 0; index < sizeof(bytes); index++)
            value |= (uint64_t)bytes[index] << (index * 8);
        if (value >= threshold) {
            *output = value % bound;
            return MIDO_DRBG_OK;
        }
    }
    return MIDO_DRBG_RETRY;
}
