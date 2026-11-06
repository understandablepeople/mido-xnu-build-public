#ifndef MIDO_WCNSS_CONTROL_H
#define MIDO_WCNSS_CONTROL_H

#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define MIDO_WCNSS_NV_FRAGMENT 3072U
#define MIDO_WCNSS_NV_MAX 65536U

static inline void
mido_wcnss_put32(uint8_t *destination, uint32_t value)
{
    for (unsigned index = 0; index < 4; index++) {
        destination[index] = (uint8_t)(value >> (8 * index));
    }
}

static inline size_t
mido_wcnss_version_request(uint8_t *output, size_t capacity)
{
    if (output == NULL || capacity < 8) {
        return 0;
    }
    mido_wcnss_put32(output, 0x01000000);
    mido_wcnss_put32(output + 4, 8);
    return 8;
}

static inline size_t
mido_wcnss_nv_request(const uint8_t *nv, size_t nv_size, unsigned fragment,
    int receive_calibration, uint8_t *output, size_t capacity)
{
    if (nv == NULL || output == NULL || nv_size <= 4 || nv_size > MIDO_WCNSS_NV_MAX + 4U) {
        return 0;
    }
    size_t payload = nv_size - 4;
    size_t count = (payload + MIDO_WCNSS_NV_FRAGMENT - 1) / MIDO_WCNSS_NV_FRAGMENT;
    if (fragment >= count) {
        return 0;
    }
    size_t offset = (size_t)fragment * MIDO_WCNSS_NV_FRAGMENT;
    size_t length = payload - offset;
    if (length > MIDO_WCNSS_NV_FRAGMENT) {
        length = MIDO_WCNSS_NV_FRAGMENT;
    }
    if (capacity < 16 + length) {
        return 0;
    }
    unsigned last = fragment + 1 == count;
    unsigned flags = last ? 1U | (receive_calibration ? 0x8000U : 0U) : 0U;
    mido_wcnss_put32(output, 0x01000002);
    mido_wcnss_put32(output + 4, (uint32_t)(16 + length));
    output[8] = (uint8_t)fragment;
    output[9] = (uint8_t)(fragment >> 8);
    output[10] = (uint8_t)flags;
    output[11] = (uint8_t)(flags >> 8);
    mido_wcnss_put32(output + 12, (uint32_t)length);
    memcpy(output + 16, nv + 4 + offset, length);
    return 16 + length;
}

#endif
