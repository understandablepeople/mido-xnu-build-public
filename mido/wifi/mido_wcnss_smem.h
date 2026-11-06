#ifndef MIDO_WCNSS_SMEM_H
#define MIDO_WCNSS_SMEM_H

#include <stdint.h>
#include <stddef.h>

struct mido_wcnss_channel {
    uint32_t cid, type, references;
};

static inline int
mido_wcnss_find_channel(const volatile uint32_t *table, size_t bytes,
    struct mido_wcnss_channel *output)
{
    if (table == NULL || output == NULL || bytes == 0 || bytes % 32 || bytes > 64 * 32) {
        return -1;
    }
    static const char expected[] = "WCNSS_CTRL";
    int found = 0;
    struct mido_wcnss_channel candidate = {0, 0, 0};
    for (size_t entry = 0; entry < bytes / 4; entry += 8) {
        int match = 1;
        for (size_t index = 0; index < sizeof(expected); index++) {
            uint32_t word = table[entry + index / 4];
            unsigned character = (word >> (8 * (index % 4))) & 255U;
            if (character != (unsigned char)expected[index]) {
                match = 0;
                break;
            }
        }
        if (!match || (table[entry + 6] & 255U) != 6U || table[entry + 7] == 0) {
            continue;
        }
        if (table[entry + 5] >= 64 || found) {
            return -1;
        }
        candidate.cid = table[entry + 5];
        candidate.type = table[entry + 6];
        candidate.references = table[entry + 7];
        found = 1;
    }
    if (found) {
        *output = candidate;
    }
    return found;
}

#endif
