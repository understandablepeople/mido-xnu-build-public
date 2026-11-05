#ifndef MIDO_SCANOUT_H
#define MIDO_SCANOUT_H

#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define MIDO_PANEL_WIDTH 1080U
#define MIDO_PANEL_HEIGHT 1920U
#define MIDO_CANVAS_WIDTH 1242U
#define MIDO_CANVAS_HEIGHT 2208U
#define MIDO_PIXEL_BGRA 0x42475241U
#define MIDO_PIXEL_BGRX 0x42475258U

struct mido_pixel_buffer {
    uint8_t *pixels;
    uint64_t length;
    uint32_t width, height, row_bytes, pixel_bytes;
};

struct mido_blit_rect {
    int32_t source_x, source_y, source_width, source_height;
    int32_t target_x, target_y, target_width, target_height;
};

static inline int
mido_buffer_valid(const struct mido_pixel_buffer *buffer)
{
    return buffer != NULL && buffer->pixels != NULL &&
        buffer->width > 0 && buffer->height > 0 &&
        buffer->width <= 16384 && buffer->height <= 16384 &&
        (buffer->pixel_bytes == 3 || buffer->pixel_bytes == 4) &&
        (uint64_t)buffer->width * buffer->pixel_bytes <= buffer->row_bytes &&
        (uint64_t)(buffer->height - 1) * buffer->row_bytes +
        (uint64_t)buffer->width * buffer->pixel_bytes <= buffer->length;
}

static inline uint32_t
mido_touch_coordinate(int32_t position, uint32_t extent)
{
    if (extent == 0) {
        return 0;
    }
    uint32_t clamped = position < 0 ? 0 : (uint32_t)position;
    if (clamped >= extent) {
        clamped = extent - 1;
    }
    return (uint32_t)(((uint64_t)clamped << 16) / extent);
}

static inline uint64_t
mido_scanout_blit(const struct mido_pixel_buffer *source,
    struct mido_pixel_buffer *target, uint32_t canvas_width,
    uint32_t canvas_height, const struct mido_blit_rect *rect)
{
    if (!mido_buffer_valid(source) || !mido_buffer_valid(target) ||
        source->pixel_bytes != 4 || rect == NULL || canvas_width == 0 ||
        canvas_height == 0 || canvas_width > 16384 || canvas_height > 16384 ||
        rect->source_width <= 0 || rect->source_height <= 0 ||
        rect->target_width <= 0 || rect->target_height <= 0) {
        return 0;
    }
    int64_t left = rect->target_x > 0 ? rect->target_x : 0;
    int64_t top = rect->target_y > 0 ? rect->target_y : 0;
    int64_t right = (int64_t)rect->target_x + rect->target_width;
    int64_t bottom = (int64_t)rect->target_y + rect->target_height;
    if (right > canvas_width) {
        right = canvas_width;
    }
    if (bottom > canvas_height) {
        bottom = canvas_height;
    }
    if (left >= right || top >= bottom) {
        return 0;
    }
    uint32_t first_x = (uint32_t)((left * target->width + canvas_width - 1) / canvas_width);
    uint32_t first_y = (uint32_t)((top * target->height + canvas_height - 1) / canvas_height);
    uint32_t last_x = (uint32_t)((right * target->width + canvas_width - 1) / canvas_width);
    uint32_t last_y = (uint32_t)((bottom * target->height + canvas_height - 1) / canvas_height);
    uint64_t copied = 0;
    uint32_t offsets[128];
    for (uint32_t block_x = first_x; block_x < last_x; block_x += 128) {
        uint32_t count = last_x - block_x;
        if (count > 128) {
            count = 128;
        }
        for (uint32_t column = 0; column < count; column++) {
            uint32_t panel_x = block_x + column;
            int64_t logical_x = (uint64_t)panel_x * canvas_width / target->width;
            int64_t source_x = rect->source_x +
                (logical_x - rect->target_x) * rect->source_width / rect->target_width;
            offsets[column] = source_x < 0 || source_x >= source->width ?
                UINT32_MAX : (uint32_t)source_x * 4;
        }
        for (uint32_t panel_y = first_y; panel_y < last_y; panel_y++) {
            int64_t logical_y = (uint64_t)panel_y * canvas_height / target->height;
            int64_t source_y = rect->source_y +
                (logical_y - rect->target_y) * rect->source_height / rect->target_height;
            if (source_y < 0 || source_y >= source->height) {
                continue;
            }
            uint8_t *target_row = target->pixels + (uint64_t)panel_y * target->row_bytes;
            const uint8_t *source_row = source->pixels + (uint64_t)source_y * source->row_bytes;
            uint32_t column = 0;
            /* Panel memory is write-combined: four BGR24 pixels leave as three aligned words. */
            if (target->pixel_bytes == 3 && ((uint64_t)(uintptr_t)target_row & 3) == 0 &&
                (target->row_bytes & 3) == 0) {
                for (; column + 4 <= count && ((block_x + column) & 3) == 0; column += 4) {
                    if ((offsets[column] | offsets[column + 1] | offsets[column + 2] |
                        offsets[column + 3]) == UINT32_MAX) {
                        break;
                    }
                    uint32_t p0, p1, p2, p3;
                    memcpy(&p0, source_row + offsets[column], 4);
                    memcpy(&p1, source_row + offsets[column + 1], 4);
                    memcpy(&p2, source_row + offsets[column + 2], 4);
                    memcpy(&p3, source_row + offsets[column + 3], 4);
                    uint32_t w0 = (p0 & 0xffffffU) | (p1 << 24);
                    uint32_t w1 = ((p1 >> 8) & 0xffffU) | (p2 << 16);
                    uint32_t w2 = ((p2 >> 16) & 0xffU) | ((p3 & 0xffffffU) << 8);
                    uint8_t *destination = target_row + (uint64_t)(block_x + column) * 3;
                    memcpy(destination, &w0, 4);
                    memcpy(destination + 4, &w1, 4);
                    memcpy(destination + 8, &w2, 4);
                    copied += 4;
                }
            }
            for (; column < count; column++) {
                if (offsets[column] == UINT32_MAX) {
                    continue;
                }
                const uint8_t *pixel = source_row + offsets[column];
                uint8_t *destination = target_row +
                    (uint64_t)(block_x + column) * target->pixel_bytes;
                destination[0] = pixel[0];
                destination[1] = pixel[1];
                destination[2] = pixel[2];
                if (target->pixel_bytes == 4) {
                    destination[3] = pixel[3];
                }
                copied++;
            }
        }
    }
    return copied;
}

#endif
