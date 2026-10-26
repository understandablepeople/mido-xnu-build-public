#include "mido_digest.h"
#include "mido_hmac.h"
#ifndef __enum_decl
#define __enum_decl(name, type, ...) typedef type name; enum __VA_ARGS__
#endif
#include <libkern/crypto/register_crypto.h>

_Static_assert(_Generic(&mido_digest_init, ccdigest_init_fn_t: 1, default: 0), "digest init ABI");
_Static_assert(_Generic(&mido_digest_update, ccdigest_update_fn_t: 1, default: 0), "digest update ABI");
_Static_assert(_Generic(&mido_digest_final_callback, ccdigest_final_fn_t: 1, default: 0), "digest final ABI");
_Static_assert(_Generic(&mido_digest, ccdigest_fn_t: 1, default: 0), "digest oneshot ABI");
_Static_assert(_Generic(&mido_hmac_init, cchmac_init_fn_t: 1, default: 0), "generic HMAC init ABI");
_Static_assert(_Generic(&mido_hmac_update, cchmac_update_fn_t: 1, default: 0), "generic HMAC update ABI");
_Static_assert(_Generic(&mido_hmac_final, cchmac_final_fn_t: 1, default: 0), "generic HMAC final ABI");
_Static_assert(_Generic(&mido_hmac, cchmac_fn_t: 1, default: 0), "generic HMAC oneshot ABI");

static const struct ccdigest_info *select_info(unsigned int algorithm)
{
    switch (algorithm) {
    case CRYPTO_DIGEST_ALG_MD5: return &mido_md5_info;
    case CRYPTO_DIGEST_ALG_SHA1: return &mido_sha1_info;
    case CRYPTO_DIGEST_ALG_SHA256: return &mido_sha256_info;
    case CRYPTO_DIGEST_ALG_SHA384: return &mido_sha384_info;
    case CRYPTO_DIGEST_ALG_SHA512: return &mido_sha512_info;
    default: return NULL;
    }
}

void mido_digest_test_init(unsigned int algorithm, ccdigest_ctx_t context)
{
    mido_digest_init(select_info(algorithm), context);
}

void mido_digest_test_update(unsigned int algorithm, ccdigest_ctx_t context, size_t length, const void *input)
{
    mido_digest_update(select_info(algorithm), context, length, input);
}

void mido_digest_test_final(unsigned int algorithm, ccdigest_ctx_t context, void *output)
{
    ccdigest_final(select_info(algorithm), context, output);
}

void mido_digest_test_oneshot(unsigned int algorithm, size_t length, const void *input, void *output)
{
    mido_digest(select_info(algorithm), length, input, output);
}

void mido_hmac_all_test_init(unsigned int algorithm, cchmac_ctx_t context, size_t length, const void *key)
{
    mido_hmac_init(select_info(algorithm), context, length, key);
}

void mido_hmac_all_test_update(unsigned int algorithm, cchmac_ctx_t context, size_t length, const void *input)
{
    mido_hmac_update(select_info(algorithm), context, length, input);
}

void mido_hmac_all_test_final(unsigned int algorithm, cchmac_ctx_t context, unsigned char *output)
{
    mido_hmac_final(select_info(algorithm), context, output);
}

void mido_hmac_all_test_oneshot(unsigned int algorithm, size_t key_length, const void *key,
                             size_t length, const void *input, unsigned char *output)
{
    mido_hmac(select_info(algorithm), key_length, key, length, input, output);
}
