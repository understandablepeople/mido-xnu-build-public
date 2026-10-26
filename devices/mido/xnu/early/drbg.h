#ifndef MIDO_DRBG_H
#define MIDO_DRBG_H

#include <stddef.h>
#include <stdint.h>
#include <bearssl_rand.h>

struct mido_drbg {
    br_hmac_drbg_context generator;
    uint64_t generated;
    uint32_t ready;
};

enum {
    MIDO_DRBG_OK = 0,
    MIDO_DRBG_INVALID = -1,
    MIDO_DRBG_RESEED_REQUIRED = -2,
    MIDO_DRBG_RETRY = -3
};

#define MIDO_DRBG_MAX_REQUEST 65536u
#define MIDO_DRBG_RESEED_BYTES 16777216u

int mido_drbg_init(struct mido_drbg *state, const void *seed, size_t length);
int mido_drbg_reseed(struct mido_drbg *state, const void *seed, size_t length);
int mido_drbg_generate(struct mido_drbg *state, void *output, size_t length);
int mido_drbg_uniform(struct mido_drbg *state, uint64_t bound, uint64_t *output);
void mido_drbg_clear(struct mido_drbg *state);

#endif
