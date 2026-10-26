#include "mido_aes_xts.h"

static const struct ccmode_xts *select_mode(unsigned int decrypt)
{
    return decrypt ? &mido_aes_xts_decrypt : &mido_aes_xts_encrypt;
}

size_t mido_xts_test_size(void)
{
    return mido_aes_xts_encrypt.size;
}

int mido_xts_test_init(unsigned int decrypt, ccxts_ctx *context, size_t key_length, const void *data_key, const void *tweak_key)
{
    return ccxts_init(select_mode(decrypt), context, key_length, data_key, tweak_key);
}

int mido_xts_test_set_tweak(unsigned int decrypt, ccxts_ctx *context, ccxts_tweak *tweak, const void *iv)
{
    return ccxts_set_tweak(select_mode(decrypt), context, tweak, iv);
}

void *mido_xts_test_update(unsigned int decrypt, ccxts_ctx *context, ccxts_tweak *tweak,
                          size_t blocks, const void *input, void *output)
{
    return ccxts_update(select_mode(decrypt), context, tweak, blocks, input, output);
}

void mido_xts_test_schedule(unsigned int decrypt, ccxts_ctx *context, size_t key_length,
                            const void *data_key, const void *tweak_key)
{
    const struct ccmode_xts *mode = select_mode(decrypt);
    mode->key_sched(mode, context, key_length, data_key, tweak_key);
}
