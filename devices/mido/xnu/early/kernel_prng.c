#include "kernel_prng.h"

static void erase(void *pointer, size_t length)
{
    volatile unsigned char *bytes = pointer;
    for (size_t index = 0; index < length; index++)
        bytes[index] = 0;
}

static int invalid_overlap(const struct mido_kernel_prng *state, const void *pointer, size_t length)
{
    uintptr_t address = (uintptr_t)pointer;
    uintptr_t base = (uintptr_t)state;
    if (!length)
        return 0;
    if (!pointer || length > UINTPTR_MAX - address)
        return 1;
    return address < base + sizeof(*state) && base < address + length;
}

static int acquire(struct mido_kernel_prng *state, int try_only)
{
    if (!state || state->initialized != 1)
        return MIDO_DRBG_INVALID;
    if (state->services.enter(state->services.lock_context, try_only))
        return MIDO_PRNG_BUSY;
    if (state->failed) {
        state->services.leave(state->services.lock_context);
        return MIDO_PRNG_HEALTH_FAILURE;
    }
    return MIDO_DRBG_OK;
}

int mido_prng_init(struct mido_kernel_prng *state, const struct mido_prng_services *services,
                   unsigned int max_cpus, const void *seed, size_t seed_length,
                   const void *nonce, size_t nonce_length)
{
    unsigned char material[64];
    static const unsigned char domain[24] = "MIDO-XNU-kernel-PRNG-v1";
    if (!state || state->initialized || !services || !services->enter || !services->leave ||
        !services->entropy || max_cpus != 1 || !seed || seed_length != 32 || !nonce || nonce_length != 8 ||
        invalid_overlap(state, seed, seed_length) || invalid_overlap(state, nonce, nonce_length) ||
        invalid_overlap(state, services, sizeof(*services)))
        return MIDO_DRBG_INVALID;
    for (size_t index = 0; index < seed_length; index++)
        material[index] = ((const unsigned char *)seed)[index];
    for (size_t index = 0; index < nonce_length; index++)
        material[32 + index] = ((const unsigned char *)nonce)[index];
    for (size_t index = 0; index < sizeof(domain); index++)
        material[40 + index] = domain[index];
    int status = mido_drbg_init(&state->generator, material, sizeof(material));
    erase(material, sizeof(material));
    if (status != MIDO_DRBG_OK)
        return status;
    state->services = *services;
    state->cpu_initialized = 0;
    state->failed = 0;
    state->initialized = 1;
    return MIDO_DRBG_OK;
}

int mido_prng_init_cpu(struct mido_kernel_prng *state, unsigned int cpu)
{
    if (cpu != 0)
        return MIDO_DRBG_INVALID;
    int status = acquire(state, 0);
    if (status != MIDO_DRBG_OK)
        return status;
    status = state->cpu_initialized ? MIDO_DRBG_INVALID : MIDO_DRBG_OK;
    state->cpu_initialized = 1;
    state->services.leave(state->services.lock_context);
    return status;
}

int mido_prng_generate(struct mido_kernel_prng *state, unsigned int cpu, void *output, size_t length)
{
    if (!state || cpu != 0 || length > 256 || invalid_overlap(state, output, length))
        return MIDO_DRBG_INVALID;
    int status = acquire(state, 0);
    if (status != MIDO_DRBG_OK)
        return status;
    status = state->cpu_initialized ? mido_drbg_generate(&state->generator, output, length) : MIDO_DRBG_INVALID;
    state->services.leave(state->services.lock_context);
    return status;
}

int mido_prng_refresh(struct mido_kernel_prng *state)
{
    unsigned char entropy[32] = {0};
    size_t length = sizeof(entropy);
    int status = acquire(state, 1);
    if (status != MIDO_DRBG_OK)
        return status;
    int32_t samples = state->services.entropy(&length, entropy, state->services.entropy_context);
    if (samples < 0 || (samples == 0 && length != 0) ||
        (samples > 0 && (samples < 256 || length != sizeof(entropy)))) {
        state->failed = 1;
        mido_drbg_clear(&state->generator);
        status = samples < 0 ? MIDO_PRNG_HEALTH_FAILURE : MIDO_PRNG_ENTROPY_CONTRACT;
    } else if (samples > 0) {
        status = mido_drbg_reseed(&state->generator, entropy, sizeof(entropy));
    }
    erase(entropy, sizeof(entropy));
    state->services.leave(state->services.lock_context);
    return status;
}

int mido_prng_mix_input(struct mido_kernel_prng *state, const void *input, size_t length)
{
    if (!state || !input || length != 32 || invalid_overlap(state, input, length))
        return MIDO_DRBG_INVALID;
    int status = acquire(state, 0);
    if (status != MIDO_DRBG_OK)
        return status;
    uint64_t used = state->generator.generated;
    status = mido_drbg_reseed(&state->generator, input, length);
    state->generator.generated = used;
    state->services.leave(state->services.lock_context);
    return status;
}
