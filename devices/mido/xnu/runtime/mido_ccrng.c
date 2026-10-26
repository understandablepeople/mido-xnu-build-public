#include "mido_ccrng.h"
#include "mido_prng_bridge.h"
#include <corecrypto/cc_error.h>

#if defined(KERNEL) && KERNEL
#include <sys/random.h>
#else
extern void read_random(void *output, unsigned int length);
#endif

static int generate(struct ccrng_state *state, size_t length, void *output);
static struct ccrng_state system_rng = { .generate = generate };

static int range_valid(const void *pointer, size_t length)
{
    return !length || (pointer && length <= UINTPTR_MAX - (uintptr_t)pointer);
}

static int overlaps_rng(const void *pointer, size_t length)
{
    return length && (uintptr_t)pointer < (uintptr_t)&system_rng + sizeof(system_rng) &&
           (uintptr_t)&system_rng < (uintptr_t)pointer + length;
}

static int generate(struct ccrng_state *state, size_t length, void *output)
{
    if (state != &system_rng || !range_valid(output, length) || overlaps_rng(output, length)) return CCERR_PARAMETER;
    if (!mido_kernel_prng_is_ready()) return CCERR_CRYPTO_CONFIG;
    unsigned char *bytes = output;
    while (length) {
        unsigned int chunk = length > 256 ? 256 : (unsigned int)length;
        read_random(bytes, chunk);
        bytes += chunk;
        length -= chunk;
    }
    return CCERR_OK;
}

struct ccrng_state *mido_ccrng(int *error)
{
    if (error && (!range_valid(error, sizeof(*error)) || (uintptr_t)error % _Alignof(int) || overlaps_rng(error, sizeof(*error))))
        return NULL;
    int ready = mido_kernel_prng_is_ready();
    if (error) *error = ready ? CCERR_OK : CCERR_CRYPTO_CONFIG;
    return ready ? &system_rng : NULL;
}
