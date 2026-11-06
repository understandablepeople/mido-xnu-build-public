#ifndef MIDO_WCNSS_START_H
#define MIDO_WCNSS_START_H

#include "mido_wcnss_bundle.h"
#include "mido_wcnss_memory.h"

extern "C" int mido_pronto_boot(int (*dependencies_ready)(void *), void *dependencies);

static inline int
mido_pronto_start_from_adt(struct mido_pronto_memory *memory)
{
    if (!memory) {
        return -10;
    }
    DTEntry chosen = NULL;
    const void *bundle = NULL;
    const void *arena_base = NULL;
    const void *arena_bytes = NULL;
    unsigned bundle_bytes = 0, base_bytes = 0, size_bytes = 0;
    if (SecureDTLookupEntry(NULL, "/chosen", &chosen) != kSuccess ||
        SecureDTGetProperty(chosen, "mido-pronto-bundle", &bundle, &bundle_bytes) != kSuccess ||
        SecureDTGetProperty(chosen, "dram-base", &arena_base, &base_bytes) != kSuccess ||
        SecureDTGetProperty(chosen, "dram-size", &arena_bytes, &size_bytes) != kSuccess ||
        !arena_base || !arena_bytes || base_bytes != 8 || size_bytes != 8) {
        return -20;
    }
    struct mido_pronto_segment segments[MIDO_PRONTO_MAX_SEGMENTS];
    struct mido_pronto_image image = {};
    if (mido_pronto_bundle_parse((const uint8_t *)bundle, bundle_bytes, &image,
        segments, MIDO_PRONTO_MAX_SEGMENTS)) {
        return -21;
    }
    int result = mido_pronto_memory_load(memory, &image,
        mido_pronto_get64((const uint8_t *)arena_base),
        mido_pronto_get64((const uint8_t *)arena_bytes));
    IOLog("MIDO WIFI FIRMWARE: result=%d stage=%u copied=%u transport=%lld secure=%llu; not SMD/DXE/network proof\n",
        result, (unsigned)memory->result.stage, memory->result.copied_segments,
        memory->result.transport, memory->result.secure);
    return result;
}

#endif
