#ifndef MIDO_KMEM_RANDOM_H
#define MIDO_KMEM_RANDOM_H

#include <libkern/crypto/rand.h>

size_t mido_kmem_random_size(void);
void mido_kmem_random_init(crypto_random_ctx_t context);
void mido_kmem_random_generate(crypto_random_ctx_t context, void *output, size_t length);
void mido_kmem_random_uniform(crypto_random_ctx_t context, uint64_t bound, uint64_t *output);

#endif
