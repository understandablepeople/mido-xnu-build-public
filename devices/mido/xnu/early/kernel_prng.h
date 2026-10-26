#ifndef MIDO_KERNEL_PRNG_H
#define MIDO_KERNEL_PRNG_H

#include "drbg.h"

typedef int32_t (*mido_entropy_source)(size_t *length, void *output, void *context);

struct mido_prng_services {
    int (*enter)(void *context, int try_only);
    void (*leave)(void *context);
    void *lock_context;
    mido_entropy_source entropy;
    void *entropy_context;
};

struct mido_kernel_prng {
    struct mido_drbg generator;
    struct mido_prng_services services;
    uint32_t initialized;
    uint32_t cpu_initialized;
    uint32_t failed;
};

enum {
    MIDO_PRNG_BUSY = -4,
    MIDO_PRNG_HEALTH_FAILURE = -5,
    MIDO_PRNG_ENTROPY_CONTRACT = -6
};

int mido_prng_init(struct mido_kernel_prng *state, const struct mido_prng_services *services,
                   unsigned int max_cpus, const void *seed, size_t seed_length,
                   const void *nonce, size_t nonce_length);
int mido_prng_init_cpu(struct mido_kernel_prng *state, unsigned int cpu);
int mido_prng_generate(struct mido_kernel_prng *state, unsigned int cpu, void *output, size_t length);
int mido_prng_refresh(struct mido_kernel_prng *state);
int mido_prng_mix_input(struct mido_kernel_prng *state, const void *input, size_t length);

#endif
