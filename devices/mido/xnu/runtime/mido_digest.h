#ifndef MIDO_DIGEST_H
#define MIDO_DIGEST_H

#include "mido_sha256.h"

extern const struct ccdigest_info mido_md5_info;
extern const struct ccdigest_info mido_sha1_info;
extern const struct ccdigest_info mido_sha384_info;
extern const struct ccdigest_info mido_sha512_info;

int mido_digest_supported(const struct ccdigest_info *info);
void mido_digest_init(const struct ccdigest_info *info, ccdigest_ctx_t context);
void mido_digest_update(const struct ccdigest_info *info, ccdigest_ctx_t context, size_t length, const void *input);
void mido_digest_final(const struct ccdigest_info *info, ccdigest_ctx_t context, unsigned char *output);
void mido_digest_final_callback(const struct ccdigest_info *info, ccdigest_ctx_t context, void *output);
void mido_digest(const struct ccdigest_info *info, size_t length, const void *input, void *output);

#endif
