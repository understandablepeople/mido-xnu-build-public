#ifndef MIDO_WCNSS_BUNDLE_H
#define MIDO_WCNSS_BUNDLE_H

#include "mido_wcnss_loader.h"

static inline uint64_t
mido_pronto_get64(const uint8_t *source)
{
    uint64_t value = 0;
    for (unsigned index = 0; index < 8; index++) {
        value |= (uint64_t)source[index] << (index * 8);
    }
    return value;
}

static inline int
mido_pronto_bundle_extent(uint64_t offset, uint64_t bytes, size_t length, size_t table_end)
{
    return offset >= table_end && bytes && offset <= length && bytes <= length - offset;
}

static inline int
mido_pronto_bundle_parse(const uint8_t *blob, size_t length, struct mido_pronto_image *image,
    struct mido_pronto_segment *segments, unsigned capacity)
{
    static const uint8_t magic[] = {'M', 'I', 'D', 'O', 'P', 'R', 'N', 'T'};
    if (!blob || !image || !segments || length < 56 || length > 0x1000000) {
        return -1;
    }
    for (unsigned index = 0; index < sizeof(magic); index++) {
        if (blob[index] != magic[index]) {
            return -1;
        }
    }
    uint64_t version_count = mido_pronto_get64(blob + 8);
    unsigned count = (unsigned)(version_count >> 32);
    size_t table_end = 56 + (size_t)count * 32;
    uint64_t metadata_offset = mido_pronto_get64(blob + 32);
    uint64_t metadata_bytes = mido_pronto_get64(blob + 40);
    if ((uint32_t)version_count != 1 || !count || count > capacity ||
        count > MIDO_PRONTO_MAX_SEGMENTS || table_end > length ||
        mido_pronto_get64(blob + 48) != length ||
        !mido_pronto_bundle_extent(metadata_offset, metadata_bytes, length, table_end)) {
        return -1;
    }
    struct mido_pronto_image candidate = {blob + metadata_offset, (size_t)metadata_bytes,
        mido_pronto_get64(blob + 24), mido_pronto_get64(blob + 16), segments, count};
    for (unsigned index = 0; index < count; index++) {
        const uint8_t *entry = blob + 56 + index * 32;
        uint64_t offset = mido_pronto_get64(entry + 8);
        uint64_t bytes = mido_pronto_get64(entry + 16);
        uint64_t memory_bytes = mido_pronto_get64(entry + 24);
        if (memory_bytes > MIDO_PRONTO_BYTES ||
            (bytes && !mido_pronto_bundle_extent(offset, bytes, length, table_end)) ||
            (!bytes && offset) || (bytes && offset < metadata_offset + metadata_bytes &&
                metadata_offset < offset + bytes)) {
            return -1;
        }
        for (unsigned previous = 0; bytes && previous < index; previous++) {
            const uint8_t *other = blob + 56 + previous * 32;
            uint64_t other_offset = mido_pronto_get64(other + 8);
            uint64_t other_bytes = mido_pronto_get64(other + 16);
            if (other_bytes && offset < other_offset + other_bytes && other_offset < offset + bytes) {
                return -1;
            }
        }
        segments[index].physical = mido_pronto_get64(entry);
        segments[index].data = bytes ? blob + offset : NULL;
        segments[index].file_bytes = (size_t)bytes;
        segments[index].memory_bytes = (size_t)memory_bytes;
    }
    if (mido_pronto_validate(&candidate)) {
        return -1;
    }
    *image = candidate;
    return 0;
}

#endif
