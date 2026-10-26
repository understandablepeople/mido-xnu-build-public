#include "kernel_prng.h"

struct test_environment {
    uint32_t attempts;
    uint32_t entries;
    uint32_t exits;
    uint32_t busy;
    uint32_t held;
    uint32_t entropy_mode;
    uint32_t entropy_calls;
    uint32_t lock_errors;
};

_Static_assert(sizeof(struct test_environment) == 32, "test environment layout");

static int enter(void *context, int try_only)
{
    struct test_environment *environment = context;
    (void)try_only;
    environment->attempts++;
    if (environment->held || environment->busy)
        return 1;
    environment->held = 1;
    environment->entries++;
    return 0;
}

static void leave(void *context)
{
    struct test_environment *environment = context;
    if (environment->held != 1)
        environment->lock_errors++;
    environment->held = 0;
    environment->exits++;
}

static int32_t entropy(size_t *length, void *output, void *context)
{
    struct test_environment *environment = context;
    environment->entropy_calls++;
    if (!environment->held)
        environment->lock_errors++;
    if (!environment->entropy_mode) {
        *length = 0;
        return 0;
    }
    if (environment->entropy_mode == 2) {
        *length = 0;
        return -1;
    }
    unsigned char *bytes = output;
    for (size_t index = 0; index < 32; index++)
        bytes[index] = (unsigned char)(0xa0 + index);
    *length = environment->entropy_mode == 3 ? 31 : 32;
    if (environment->entropy_mode == 4)
        return 255;
    if (environment->entropy_mode == 5)
        return 0;
    return 256;
}

int mido_prng_test_init(struct mido_kernel_prng *state, struct test_environment *environment,
                        const unsigned char *seed_and_nonce, unsigned int max_cpus)
{
    struct mido_prng_services services = {
        .enter = enter,
        .leave = leave,
        .lock_context = environment,
        .entropy = entropy,
        .entropy_context = environment,
    };
    return mido_prng_init(state, &services, max_cpus, seed_and_nonce, 32, seed_and_nonce + 32, 8);
}

size_t mido_prng_test_size(void)
{
    return sizeof(struct mido_kernel_prng);
}

size_t mido_prng_test_counter_offset(void)
{
    return offsetof(struct mido_kernel_prng, generator) + offsetof(struct mido_drbg, generated);
}
