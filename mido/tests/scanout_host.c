#include "../display/mido_scanout.h"

uint64_t host_blit(const struct mido_pixel_buffer *source,
    struct mido_pixel_buffer *target, uint32_t width, uint32_t height,
    const struct mido_blit_rect *rect)
{
    return mido_scanout_blit(source, target, width, height, rect);
}

uint32_t host_touch(int32_t position, uint32_t extent)
{
    return mido_touch_coordinate(position, extent);
}

#ifdef MIDO_SCANOUT_SELF_TEST
#include <assert.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

int main(void)
{
    uint8_t source_bytes[16 * 16 * 4];
    uint8_t target_bytes[16 * 16 * 3 + 32];
    struct mido_pixel_buffer source = {source_bytes, sizeof(source_bytes), 16, 16, 64, 4};
    struct mido_pixel_buffer target = {target_bytes + 16, sizeof(target_bytes) - 32, 16, 16, 48, 3};
    uint32_t random_state = 42;
    memset(source_bytes, 0x81, sizeof(source_bytes));
    for (unsigned int iteration = 0; iteration < 10000; iteration++) {
        struct mido_blit_rect rect;
        int32_t values[8];
        for (unsigned int field = 0; field < 8; field++) {
            random_state = random_state * 1664525U + 1013904223U;
            values[field] = (int32_t)random_state;
        }
        memcpy(&rect, values, sizeof(rect));
        memset(target_bytes, 0x42, sizeof(target_bytes));
        host_blit(&source, &target, 16, 16, &rect);
        for (unsigned int guard = 0; guard < 16; guard++) {
            assert(target_bytes[guard] == 0x42);
            assert(target_bytes[sizeof(target_bytes) - 1 - guard] == 0x42);
        }
    }
    assert(host_touch(INT_MIN, 1920) == 0);
    assert(host_touch(INT_MAX, 1920) < 65536);
    puts("scanout sanitizer checks passed");
    return 0;
}
#endif
