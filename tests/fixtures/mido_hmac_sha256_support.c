#include "mido_hmac_sha256.h"
#include "mido_sha256.h"
#ifndef __enum_decl
#define __enum_decl(name, type, ...) typedef type name; enum __VA_ARGS__
#endif
#include <libkern/crypto/register_crypto.h>

_Static_assert(_Generic(&mido_hmac_sha256_init, cchmac_init_fn_t: 1, default: 0), "HMAC init ABI");
_Static_assert(_Generic(&mido_hmac_sha256_update, cchmac_update_fn_t: 1, default: 0), "HMAC update ABI");
_Static_assert(_Generic(&mido_hmac_sha256_final, cchmac_final_fn_t: 1, default: 0), "HMAC final ABI");
_Static_assert(_Generic(&mido_hmac_sha256, cchmac_fn_t: 1, default: 0), "HMAC oneshot ABI");

void mido_hmac_test_init(cchmac_ctx_t context, size_t length, const void *key)
{
    mido_hmac_sha256_init(&mido_sha256_info, context, length, key);
}

void mido_hmac_test_update(cchmac_ctx_t context, size_t length, const void *input)
{
    mido_hmac_sha256_update(&mido_sha256_info, context, length, input);
}

void mido_hmac_test_final(cchmac_ctx_t context, unsigned char *output)
{
    mido_hmac_sha256_final(&mido_sha256_info, context, output);
}

void mido_hmac_test_oneshot(size_t key_length, const void *key, size_t length, const void *input, unsigned char *output)
{
    mido_hmac_sha256(&mido_sha256_info, key_length, key, length, input, output);
}
