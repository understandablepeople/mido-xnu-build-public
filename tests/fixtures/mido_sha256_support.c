#include "mido_sha256.h"
#include <libkern/crypto/sha2.h>
#ifndef __enum_decl
#define __enum_decl(name, type, ...) typedef type name; enum __VA_ARGS__
#endif
#include <libkern/crypto/register_crypto.h>

_Static_assert(sizeof(SHA256_CTX) >= ccdigest_ctx_size(32, 64), "XNU entropy context is too small");
_Static_assert(_Generic(&mido_sha256_init, ccdigest_init_fn_t: 1, default: 0), "digest init table ABI");
_Static_assert(_Generic(&mido_sha256_update, ccdigest_update_fn_t: 1, default: 0), "digest update table ABI");
_Static_assert(_Generic(&mido_sha256_final_callback, ccdigest_final_fn_t: 1, default: 0), "digest final table ABI");
_Static_assert(_Generic(&mido_sha256_digest, ccdigest_fn_t: 1, default: 0), "digest oneshot table ABI");

size_t mido_sha256_test_size(void)
{
    return sizeof(SHA256_CTX);
}

void mido_sha256_test_init(ccdigest_ctx_t context)
{
    mido_sha256_init(&mido_sha256_info, context);
}

void mido_sha256_test_update(ccdigest_ctx_t context, size_t length, const void *input)
{
    mido_sha256_update(&mido_sha256_info, context, length, input);
}

void mido_sha256_test_final(ccdigest_ctx_t context, unsigned char *output)
{
    ccdigest_final(&mido_sha256_info, context, output);
}

void mido_sha256_test_digest(size_t length, const void *input, void *output)
{
    mido_sha256_digest(&mido_sha256_info, length, input, output);
}

void mido_sha256_test_wrong_info(ccdigest_ctx_t context)
{
    mido_sha256_init(NULL, context);
}

void mido_sha256_test_callback_final(ccdigest_ctx_t context, void *output)
{
    mido_sha256_final_callback(&mido_sha256_info, context, output);
}
