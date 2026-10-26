#include "mido_aes_gcm.h"
#ifndef __enum_decl
#define __enum_decl(name, type, ...) typedef type name; enum __VA_ARGS__
#endif
#include <libkern/crypto/register_crypto.h>

_Static_assert(_Generic(&mido_gcm_init_with_iv, ccgcm_init_with_iv_fn_t: 1, default: 0), "GCM managed IV init ABI");
_Static_assert(_Generic(&mido_gcm_inc_iv, ccgcm_inc_iv_fn_t: 1, default: 0), "GCM IV increment ABI");

static const struct ccmode_gcm *select_mode(unsigned int decrypt)
{
    return decrypt ? &mido_aes_gcm_decrypt : &mido_aes_gcm_encrypt;
}

size_t mido_gcm_test_size(void)
{
    return mido_aes_gcm_encrypt.size;
}

int mido_gcm_test_init(unsigned int decrypt, ccgcm_ctx *context, size_t length, const void *key)
{
    return ccgcm_init(select_mode(decrypt), context, length, key);
}

int mido_gcm_test_init_managed(unsigned int decrypt, ccgcm_ctx *context, size_t length, const void *key, const void *iv)
{
    return mido_gcm_init_with_iv(select_mode(decrypt), context, length, key, iv);
}

int mido_gcm_test_iv(ccgcm_ctx *context, size_t length, const void *iv)
{
    return ccgcm_set_iv(&mido_aes_gcm_encrypt, context, length, iv);
}

int mido_gcm_test_aad(ccgcm_ctx *context, size_t length, const void *input)
{
    return ccgcm_aad(&mido_aes_gcm_encrypt, context, length, input);
}

int mido_gcm_test_update(ccgcm_ctx *context, size_t length, const void *input, void *output)
{
    return ccgcm_update(&mido_aes_gcm_encrypt, context, length, input, output);
}

int mido_gcm_test_final(ccgcm_ctx *context, size_t length, void *tag)
{
    return ccgcm_finalize(&mido_aes_gcm_encrypt, context, length, tag);
}

int mido_gcm_test_reset(ccgcm_ctx *context)
{
    return ccgcm_reset(&mido_aes_gcm_encrypt, context);
}

int mido_gcm_test_inc(unsigned int decrypt, ccgcm_ctx *context, void *iv)
{
    return mido_gcm_inc_iv(select_mode(decrypt), context, iv);
}
