#include "mido_aes_cbc.h"

size_t mido_aes_test_size(void)
{
    return mido_aes_cbc_encrypt.size;
}

static const struct ccmode_cbc *select_mode(unsigned int decrypt)
{
    return decrypt ? &mido_aes_cbc_decrypt : &mido_aes_cbc_encrypt;
}

int mido_aes_test_init(unsigned int decrypt, cccbc_ctx *context, size_t key_length, const void *key)
{
    const struct ccmode_cbc *mode = select_mode(decrypt);
    return cccbc_init(mode, context, key_length, key);
}

int mido_aes_test_update(unsigned int decrypt, cccbc_ctx *context, cccbc_iv *iv,
                         size_t blocks, const void *input, void *output)
{
    return cccbc_update(select_mode(decrypt), context, iv, blocks, input, output);
}
