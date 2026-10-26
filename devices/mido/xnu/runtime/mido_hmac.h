#ifndef MIDO_HMAC_H
#define MIDO_HMAC_H

#include <corecrypto/cchmac.h>

void mido_hmac_init(const struct ccdigest_info *info, cchmac_ctx_t context, size_t key_length, const void *key);
void mido_hmac_update(const struct ccdigest_info *info, cchmac_ctx_t context, size_t length, const void *input);
void mido_hmac_final(const struct ccdigest_info *info, cchmac_ctx_t context, unsigned char *output);
void mido_hmac(const struct ccdigest_info *info, size_t key_length, const void *key,
                      size_t length, const void *input, unsigned char *output);

#endif
