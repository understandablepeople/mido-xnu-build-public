#ifndef MIDO_AES_GCM_H
#define MIDO_AES_GCM_H

#include <corecrypto/ccmode.h>

extern const struct ccmode_gcm mido_aes_gcm_encrypt;
extern const struct ccmode_gcm mido_aes_gcm_decrypt;
int mido_gcm_init_with_iv(const struct ccmode_gcm *mode, ccgcm_ctx *context, size_t key_length,
                          const void *key, const void *iv);
int mido_gcm_inc_iv(const struct ccmode_gcm *mode, ccgcm_ctx *context, void *iv);

#endif
