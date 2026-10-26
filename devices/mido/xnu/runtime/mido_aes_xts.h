#ifndef MIDO_AES_XTS_H
#define MIDO_AES_XTS_H

#include <corecrypto/ccmode.h>

extern const struct ccmode_xts mido_aes_xts_encrypt;
extern const struct ccmode_xts mido_aes_xts_decrypt;

#endif
