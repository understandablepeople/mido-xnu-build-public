#include "mido_aes_ctr.h"

size_t mido_ctr_test_size(void)
{
    return mido_aes_ctr_crypt.size;
}

int mido_ctr_test_init(ccctr_ctx *context, size_t key_length, const void *key, const void *iv)
{
    return ccctr_init(&mido_aes_ctr_crypt, context, key_length, key, iv);
}

int mido_ctr_test_update(ccctr_ctx *context, size_t length, const void *input, void *output)
{
    return ccctr_update(&mido_aes_ctr_crypt, context, length, input, output);
}

int mido_ctr_test_set_counter(ccctr_ctx *context, const void *counter)
{
    return mido_aes_ctr_crypt.setctr(&mido_aes_ctr_crypt, context, counter);
}
