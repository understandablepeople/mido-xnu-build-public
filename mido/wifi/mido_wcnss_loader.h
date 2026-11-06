#ifndef MIDO_WCNSS_LOADER_H
#define MIDO_WCNSS_LOADER_H

#include <stddef.h>
#include <stdint.h>

#define MIDO_PRONTO_BASE 0x8e700000ULL
#define MIDO_PRONTO_BYTES 0x700000ULL
#define MIDO_PRONTO_MAX_SEGMENTS 32U

struct mido_pronto_segment {
    uint64_t physical;
    const uint8_t *data;
    size_t file_bytes;
    size_t memory_bytes;
};

struct mido_pronto_image {
    const uint8_t *metadata;
    size_t metadata_bytes;
    uint64_t metadata_physical;
    uint64_t allocation_bytes;
    const struct mido_pronto_segment *segments;
    unsigned segment_count;
};

struct mido_pronto_ops {
    void *context;
    int (*ready)(void *);
    int (*write)(void *, uint64_t, const uint8_t *, size_t);
    int (*zero)(void *, uint64_t, size_t);
    int (*clean)(void *, uint64_t, size_t);
    int64_t (*call)(void *, uint32_t, uint32_t, const uint64_t *, uint64_t *);
};

enum mido_pronto_stage {
    MIDO_PRONTO_IDLE,
    MIDO_PRONTO_STARTED,
    MIDO_PRONTO_METADATA,
    MIDO_PRONTO_INITIALIZED,
    MIDO_PRONTO_MEMORY,
    MIDO_PRONTO_SEGMENTS,
    MIDO_PRONTO_AUTHENTICATED
};

struct mido_pronto_result {
    enum mido_pronto_stage stage;
    int error;
    int64_t transport;
    uint64_t secure;
    unsigned copied_segments;
};

static inline int
mido_pronto_inside(uint64_t start, uint64_t bytes)
{
    return start >= MIDO_PRONTO_BASE && bytes && bytes <= MIDO_PRONTO_BYTES &&
        start - MIDO_PRONTO_BASE <= MIDO_PRONTO_BYTES - bytes;
}

static inline int
mido_pronto_validate(const struct mido_pronto_image *image)
{
    if (!image || !image->metadata || !image->metadata_bytes ||
        image->metadata_bytes > 65536 || !image->segments ||
        !image->segment_count || image->segment_count > MIDO_PRONTO_MAX_SEGMENTS ||
        !image->allocation_bytes || image->allocation_bytes > MIDO_PRONTO_BYTES ||
        (image->allocation_bytes & 4095) || (image->metadata_physical & 4095) ||
        !mido_pronto_inside(image->metadata_physical, image->metadata_bytes) ||
        image->metadata_physical < MIDO_PRONTO_BASE + image->allocation_bytes) {
        return -1;
    }
    for (unsigned index = 0; index < image->segment_count; index++) {
        const struct mido_pronto_segment *segment = &image->segments[index];
        if (!mido_pronto_inside(segment->physical, segment->memory_bytes) ||
            segment->physical - MIDO_PRONTO_BASE >= image->allocation_bytes ||
            segment->memory_bytes > image->allocation_bytes - (segment->physical - MIDO_PRONTO_BASE) ||
            segment->file_bytes > segment->memory_bytes ||
            (segment->file_bytes && !segment->data)) {
            return -1;
        }
        for (unsigned previous = 0; previous < index; previous++) {
            const struct mido_pronto_segment *other = &image->segments[previous];
            if (segment->physical < other->physical + other->memory_bytes &&
                other->physical < segment->physical + segment->memory_bytes) {
                return -1;
            }
        }
    }
    return 0;
}

static inline int
mido_pronto_pas(const struct mido_pronto_ops *ops, struct mido_pronto_result *result,
    uint32_t command, uint32_t info, uint64_t second, uint64_t third)
{
    uint64_t arguments[3] = {6, second, third};
    result->secure = 0;
    result->transport = ops->call(ops->context, 0x02000200U | command,
        info, arguments, &result->secure);
    if (result->transport || result->secure) {
        result->error = -5;
        return -5;
    }
    return 0;
}

static inline int
mido_pronto_load(const struct mido_pronto_image *image, const struct mido_pronto_ops *ops,
    struct mido_pronto_result *result)
{
    if (!result || result->stage != MIDO_PRONTO_IDLE) {
        return -1;
    }
    result->error = 0;
    result->transport = 0;
    result->secure = 0;
    result->copied_segments = 0;
    if (mido_pronto_validate(image) || !ops || !ops->ready || !ops->write ||
        !ops->zero || !ops->clean || !ops->call) {
        result->error = -1;
        return -1;
    }
    if (ops->ready(ops->context) != 1) {
        result->error = -2;
        return -2;
    }
    result->stage = MIDO_PRONTO_STARTED;
    if (ops->write(ops->context, image->metadata_physical, image->metadata,
            image->metadata_bytes) ||
        ops->clean(ops->context, image->metadata_physical, image->metadata_bytes)) {
        result->error = -3;
        return -3;
    }
    result->stage = MIDO_PRONTO_METADATA;
    if (mido_pronto_pas(ops, result, 1, 0x82, image->metadata_physical, 0)) {
        return result->error;
    }
    result->stage = MIDO_PRONTO_INITIALIZED;
    if (mido_pronto_pas(ops, result, 2, 3, MIDO_PRONTO_BASE, image->allocation_bytes)) {
        return result->error;
    }
    result->stage = MIDO_PRONTO_MEMORY;
    for (unsigned index = 0; index < image->segment_count; index++) {
        const struct mido_pronto_segment *segment = &image->segments[index];
        if ((segment->file_bytes && ops->write(ops->context, segment->physical,
                segment->data, segment->file_bytes)) ||
            (segment->memory_bytes > segment->file_bytes &&
                ops->zero(ops->context, segment->physical + segment->file_bytes,
                    segment->memory_bytes - segment->file_bytes)) ||
            ops->clean(ops->context, segment->physical, segment->memory_bytes)) {
            result->error = -4;
            return -4;
        }
        result->copied_segments++;
    }
    result->stage = MIDO_PRONTO_SEGMENTS;
    if (ops->ready(ops->context) != 1) {
        result->error = -2;
        return -2;
    }
    if (mido_pronto_pas(ops, result, 5, 1, 0, 0)) {
        return result->error;
    }
    result->stage = MIDO_PRONTO_AUTHENTICATED;
    return 0;
}

#endif
