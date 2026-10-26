#include <corecrypto/cckprng.h>
#include "mido_prng_bridge.h"

bool crypto_init;
static struct cckprng_ctx *received_context;
static const struct cckprng_funcs *received_functions;
static unsigned int configured_cpus;
static unsigned int use_legacy;
static int entropy_mode;
static int held;
static int busy;
static unsigned int registration_calls;
static unsigned int service_entries;
static unsigned int random_calls;

static int enter(void *context, int try_only)
{
    service_entries++;
    (void)context;
    (void)try_only;
    if (held || busy)
        return 1;
    held = 1;
    return 0;
}

static void leave(void *context)
{
    (void)context;
    held = 0;
}

static int32_t entropy(size_t *length, void *output, void *context)
{
    (void)context;
    if (entropy_mode <= 0) {
        *length = 0;
        return entropy_mode;
    }
    unsigned char *bytes = output;
    for (size_t index = 0; index < 32; index++)
        bytes[index] = (unsigned char)(0xa0 + index);
    *length = entropy_mode == 2 ? 31 : 32;
    return 256;
}

void panic(const char *format, ...)
{
    (void)format;
    for (;;)
        __asm__ volatile("brk #0x777");
}

void register_and_init_prng(struct cckprng_ctx *context, const struct cckprng_funcs *functions)
{
    unsigned char seed[32];
    unsigned char nonce[8];
    for (size_t index = 0; index < sizeof(seed); index++)
        seed[index] = (unsigned char)index;
    for (size_t index = 0; index < sizeof(nonce); index++)
        nonce[index] = (unsigned char)(index + 32);
    received_context = context;
    received_functions = functions;
    registration_calls++;
    if (use_legacy)
        functions->init(context, sizeof(seed), seed, sizeof(nonce), nonce, entropy, NULL);
    else
        functions->init_with_getentropy(context, configured_cpus, sizeof(seed), seed,
                                        sizeof(nonce), nonce, entropy, NULL);
    functions->initgen(context, 0);
    if (mido_kernel_prng_is_ready()) panic("Fixture: PRNG published before registration returned");
}

unsigned int mido_bridge_test_start(unsigned int ready, unsigned int cpus, unsigned int legacy)
{
    struct mido_prng_services services = {
        .enter = enter,
        .leave = leave,
    };
    crypto_init = ready != 0;
    configured_cpus = cpus;
    use_legacy = legacy;
    mido_kernel_prng_install(&services);
    return registration_calls;
}

void mido_bridge_test_read(size_t length, void *output)
{
    received_functions->generate(received_context, 0, length, output);
}

void read_random(void *output, unsigned int length)
{
    random_calls++;
    received_functions->refresh(received_context);
    received_functions->generate(received_context, 0, length, output);
}

unsigned int mido_bridge_test_service_entries(void)
{
    return service_entries;
}

unsigned int mido_bridge_test_random_calls(void)
{
    return random_calls;
}

void mido_bridge_test_refresh(int mode, int lock_busy)
{
    entropy_mode = mode;
    busy = lock_busy;
    received_functions->refresh(received_context);
    busy = 0;
}

void mido_bridge_test_mix(size_t length, const void *input)
{
    received_functions->reseed(received_context, length, input);
}

void mido_bridge_test_init_cpu(unsigned int cpu)
{
    received_functions->initgen(received_context, cpu);
}

void mido_bridge_test_wrong_context(void *output)
{
    received_functions->generate(NULL, 0, 1, output);
}

void mido_bridge_test_invalid_services(unsigned int mode)
{
    struct mido_prng_services services = {
        .enter = enter,
        .leave = leave,
    };
    crypto_init = true;
    if (mode == 1)
        services.enter = NULL;
    if (mode == 2)
        services.leave = NULL;
    mido_kernel_prng_install(mode == 0 ? NULL : &services);
}
