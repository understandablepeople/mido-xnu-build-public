#include "mido_kmem_random.h"
#include <bearssl_rand.h>

#if defined(KERNEL) && KERNEL
#include <kern/debug.h>
#include <sys/random.h>
#else
extern void panic(const char *format, ...) __attribute__((noreturn));
extern void read_random(void *output, unsigned int length);
#endif

struct mido_kmem_random {
    br_hmac_drbg_context generator;
    uint64_t ready;
};

#define MIDO_KMEM_READY UINT64_C(0x4d49444f4b4d454d)
#define MIDO_KMEM_CHUNK 256u

_Static_assert(sizeof(struct mido_kmem_random) <= CRYPTO_RANDOM_MAX_CTX_SIZE, "XNU kmem context limit");
_Static_assert(_Alignof(struct mido_kmem_random) <= sizeof(void *), "XNU ZALIGN_PTR alignment");
_Static_assert(_Generic(&mido_kmem_random_size, crypto_random_kmem_ctx_size_fn_t: 1, default: 0), "kmem size ABI");
_Static_assert(_Generic(&mido_kmem_random_init, crypto_random_kmem_init_fn_t: 1, default: 0), "kmem init ABI");
_Static_assert(_Generic(&mido_kmem_random_generate, crypto_random_generate_fn_t: 1, default: 0), "generate ABI");
_Static_assert(_Generic(&mido_kmem_random_uniform, crypto_random_uniform_fn_t: 1, default: 0), "uniform ABI");

static struct mido_kmem_random *checked_context(crypto_random_ctx_t context)
{
    if (!context || (uintptr_t)context % _Alignof(struct mido_kmem_random))
        panic("MIDO kmem RNG: invalid context alignment");
    return context;
}

static void checked_output(struct mido_kmem_random *context, void *output, size_t length)
{
    uintptr_t address = (uintptr_t)output;
    uintptr_t state = (uintptr_t)context;
    if (context->ready != MIDO_KMEM_READY || (!output && length) || length > UINTPTR_MAX - address ||
        sizeof(*context) > UINTPTR_MAX - state ||
        (length && address < state + sizeof(*context) && state < address + length))
        panic("MIDO kmem RNG: invalid state or output");
}

size_t mido_kmem_random_size(void)
{
    return sizeof(struct mido_kmem_random);
}

void mido_kmem_random_init(crypto_random_ctx_t context)
{
    struct mido_kmem_random *state = checked_context(context);
    unsigned char seed[64] = {0};
    const unsigned char domain[16] = "MIDO-kmem-v1";
    state->ready = 0;
    read_random(seed, 48);
    for (size_t index = 0; index < sizeof(domain); index++)
        seed[48 + index] = domain[index];
    br_hmac_drbg_init(&state->generator, &br_sha256_vtable, seed, sizeof(seed));
    volatile unsigned char *bytes = seed;
    for (size_t index = 0; index < sizeof(seed); index++)
        bytes[index] = 0;
    state->ready = MIDO_KMEM_READY;
}

void mido_kmem_random_generate(crypto_random_ctx_t context, void *output, size_t length)
{
    struct mido_kmem_random *state = checked_context(context);
    checked_output(state, output, length);
    unsigned char *bytes = output;
    while (length) {
        size_t chunk = length < MIDO_KMEM_CHUNK ? length : MIDO_KMEM_CHUNK;
        br_hmac_drbg_generate(&state->generator, bytes, chunk);
        bytes += chunk;
        length -= chunk;
    }
}

void mido_kmem_random_uniform(crypto_random_ctx_t context, uint64_t bound, uint64_t *output)
{
    struct mido_kmem_random *state = checked_context(context);
    checked_output(state, output, sizeof(*output));
    if (!bound || (uintptr_t)output % _Alignof(uint64_t))
        panic("MIDO kmem RNG: invalid bound or output alignment");
    uint64_t threshold = (UINT64_C(0) - bound) % bound;
    for (unsigned int attempt = 0; attempt < 128; attempt++) {
        unsigned char bytes[8];
        uint64_t value = 0;
        mido_kmem_random_generate(state, bytes, sizeof(bytes));
        for (size_t index = 0; index < sizeof(bytes); index++)
            value |= (uint64_t)bytes[index] << (index * 8);
        if (value >= threshold) {
            *output = value % bound;
            return;
        }
    }
    panic("MIDO kmem RNG: rejection sampling exhausted");
}
