#ifndef MIDO_SHA256_H
#define MIDO_SHA256_H

#include <corecrypto/ccdigest.h>

extern const struct ccdigest_info mido_sha256_info;
void mido_sha256_init(const struct ccdigest_info *info, ccdigest_ctx_t context);
void mido_sha256_update(const struct ccdigest_info *info, ccdigest_ctx_t context, size_t length, const void *input);
void mido_sha256_final(const struct ccdigest_info *info, ccdigest_ctx_t context, unsigned char *output);
void mido_sha256_final_callback(const struct ccdigest_info *info, ccdigest_ctx_t context, void *output);
void mido_sha256_digest(const struct ccdigest_info *info, size_t length, const void *input, void *output);

#endif
