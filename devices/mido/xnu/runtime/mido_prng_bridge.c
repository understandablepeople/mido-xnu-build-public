#include <corecrypto/cckprng.h>
#include "mido_prng_bridge.h"

#if defined(KERNEL) && KERNEL
#include <kern/debug.h>
#else
extern void panic(const char *format, ...) __attribute__((noreturn));
#endif

extern void register_and_init_prng(struct cckprng_ctx *context, const struct cckprng_funcs *functions);
extern bool crypto_init;

static struct cckprng_ctx context_token;
static struct mido_kernel_prng backend;
static struct mido_prng_services configured_services;
static int installation_started;
static int installation_complete;

_Static_assert(sizeof(void *) == 8, "MIDO requires ARM64 callback ABI");
_Static_assert(CCKPRNG_GENERATE_MAX_NBYTES == 256, "XNU PRNG request contract changed");
_Static_assert(sizeof(struct cckprng_funcs) == 48, "XNU PRNG callback table changed");
_Static_assert(offsetof(struct cckprng_funcs, generate) == 32, "XNU generate callback offset changed");
_Static_assert(offsetof(struct cckprng_funcs, init_with_getentropy) == 40, "XNU init callback offset changed");

static void require_context(struct cckprng_ctx *context)
{
    if (context != &context_token)
        panic("MIDO PRNG: unexpected context");
}

static void require_status(int status)
{
    if (status != MIDO_DRBG_OK)
        panic("MIDO PRNG: runtime failure %d", status);
}

static void initialize(struct cckprng_ctx *context, unsigned int max_cpus,
                       size_t seed_length, const void *seed, size_t nonce_length,
                       const void *nonce, cckprng_getentropy entropy, void *entropy_context)
{
    require_context(context);
    struct mido_prng_services services = configured_services;
    services.entropy = entropy;
    services.entropy_context = entropy_context;
    require_status(mido_prng_init(&backend, &services, max_cpus, seed, seed_length, nonce, nonce_length));
}

static void initialize_legacy(struct cckprng_ctx *context, size_t seed_length, const void *seed,
                              size_t nonce_length, const void *nonce, cckprng_getentropy entropy,
                              void *entropy_context)
{
    initialize(context, 1, seed_length, seed, nonce_length, nonce, entropy, entropy_context);
}

static void initialize_cpu(struct cckprng_ctx *context, unsigned int cpu)
{
    require_context(context);
    require_status(mido_prng_init_cpu(&backend, cpu));
}

static void refresh(struct cckprng_ctx *context)
{
    require_context(context);
    int status = mido_prng_refresh(&backend);
    if (status != MIDO_PRNG_BUSY)
        require_status(status);
}

static void generate(struct cckprng_ctx *context, unsigned int cpu, size_t length, void *output)
{
    require_context(context);
    require_status(mido_prng_generate(&backend, cpu, output, length));
}

static void mix_input(struct cckprng_ctx *context, size_t length, const void *input)
{
    br_sha256_context hash;
    unsigned char digest[32];
    require_context(context);
    if (!input && length)
        panic("MIDO PRNG: invalid reseed input");
    br_sha256_init(&hash);
    br_sha256_update(&hash, input, length);
    br_sha256_out(&hash, digest);
    int status = mido_prng_mix_input(&backend, digest, sizeof(digest));
    volatile unsigned char *bytes = (volatile unsigned char *)&hash;
    for (size_t index = 0; index < sizeof(hash); index++)
        bytes[index] = 0;
    bytes = digest;
    for (size_t index = 0; index < sizeof(digest); index++)
        bytes[index] = 0;
    require_status(status);
}

static const struct cckprng_funcs functions = {
    .init = initialize_legacy,
    .initgen = initialize_cpu,
    .reseed = mix_input,
    .refresh = refresh,
    .generate = generate,
    .init_with_getentropy = initialize,
};

void mido_kernel_prng_install(const struct mido_prng_services *services)
{
    if (installation_started || !crypto_init || !services || !services->enter || !services->leave)
        panic("MIDO PRNG: invalid installation order or lock backend");
    installation_started = 1;
    configured_services = *services;
    register_and_init_prng(&context_token, &functions);
    __atomic_store_n(&installation_complete, 1, __ATOMIC_RELEASE);
}

int mido_kernel_prng_is_ready(void)
{
    return __atomic_load_n(&installation_complete, __ATOMIC_ACQUIRE);
}
