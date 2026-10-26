#include "drbg.h"

void *memcpy(void *destination, const void *source, size_t length)
{
    unsigned char *target = destination;
    const unsigned char *origin = source;
    for (size_t index = 0; index < length; index++)
        target[index] = origin[index];
    return destination;
}

void *memset(void *destination, int value, size_t length)
{
    unsigned char *target = destination;
    for (size_t index = 0; index < length; index++)
        target[index] = (unsigned char)value;
    return destination;
}

size_t mido_drbg_test_size(void)
{
    return sizeof(struct mido_drbg);
}

size_t mido_drbg_test_counter_offset(void)
{
    return offsetof(struct mido_drbg, generated);
}
