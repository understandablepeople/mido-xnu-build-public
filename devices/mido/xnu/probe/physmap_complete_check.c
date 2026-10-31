#include <stdint.h>
#include "early_entry_config.h"

struct mido_physmap_geometry {
    uint64_t first;
    uint64_t rest;
    uint64_t l2_count;
};

static int mido_physmap_readable(uint64_t address, uint64_t size, uint64_t alignment)
{
    return address >= 0x11200000ULL && address <= 0x13200000ULL - size
        && !(address & (alignment - 1));
}

static int mido_physmap_alias_word(const struct mido_physmap_geometry *geometry,
                                   uint64_t virtual_address, uint64_t *word)
{
    uint64_t root_slot = (virtual_address >> 30) & 255;
    if (root_slot < 192)
        return 0;
    uint64_t root_index = root_slot - 192;
    if (root_index >= 48)
        return 0;
    uint64_t page = root_index < geometry->l2_count ? 2 + root_index : 8 + root_index;
    uint64_t index = page * 512 + ((virtual_address >> 21) & 511);
    if (index >= MIDO_PHYSMAP_TABLE_PAGES * 512ULL)
        return 0;
    *word = index;
    return 1;
}

static int mido_physmap_geometry(struct mido_physmap_geometry *geometry)
{
    if (MIDO_PHYSMAP_TOP != 0x12401000ULL
        || MIDO_PHYSMAP_PHYSICAL != 0x11200000ULL
        || MIDO_PHYSMAP_VIRTUAL != 0xfffffff007000000ULL
        || MIDO_PHYSMAP_TABLE_PAGES != 59
        || !mido_physmap_readable(MIDO_VM_PHYSMAP_PA, 8, 8)
        || !mido_physmap_readable(MIDO_VM_STATIC_END_PA, 8, 8)
        || !mido_physmap_readable(MIDO_VM_MEMORY_SIZE_PA, 8, 8))
        return 0;
    uint64_t physmap = *(const volatile uint64_t *)MIDO_VM_PHYSMAP_PA;
    uint64_t static_end = *(const volatile uint64_t *)MIDO_VM_STATIC_END_PA;
    uint64_t memory_size = *(const volatile uint64_t *)MIDO_VM_MEMORY_SIZE_PA;
    uint64_t base = MIDO_PHYSMAP_VIRTUAL + MIDO_PHYSMAP_TOP - MIDO_PHYSMAP_PHYSICAL;
    if (memory_size != 0x2000000ULL || physmap < base
        || physmap - base >= 0x40000000ULL || (physmap & 4095)
        || physmap > UINT64_MAX - 0x3000000ULL
        || static_end != physmap + 0x3000000ULL
        || static_end < MIDO_PHYSMAP_VIRTUAL
        || static_end - MIDO_PHYSMAP_VIRTUAL > UINT64_MAX - 0x3fffffffULL)
        return 0;
    geometry->l2_count = (static_end - MIDO_PHYSMAP_VIRTUAL + 0x3fffffffULL) >> 30;
    if (geometry->l2_count != 1 && geometry->l2_count != 2)
        return 0;
    geometry->first = (physmap + 0x1fffffULL) & ~0x1fffffULL;
    geometry->rest = geometry->first + 0x201000ULL;
    if (geometry->first < UINT64_MAX - ((1ULL << 38) - 1)
        || geometry->first > UINT64_MAX - 0x1000000ULL
        || geometry->first + 0x1000000ULL > static_end)
        return 0;
    uint64_t word;
    if (!mido_physmap_alias_word(geometry, geometry->first, &word)
        || !mido_physmap_alias_word(geometry, geometry->rest, &word))
        return 0;
    for (unsigned int index = 0; index < 6; ++index)
        if (!mido_physmap_alias_word(geometry, geometry->first + 0x400000ULL
                                    + (uint64_t)index * 0x200000ULL, &word))
            return 0;
    return 1;
}

unsigned long long mido_physmap_expected_word(unsigned long long word_index,
                                             unsigned long long template_word)
{
    struct mido_physmap_geometry geometry;
    if (word_index >= MIDO_PHYSMAP_TABLE_PAGES * 512ULL || !mido_physmap_geometry(&geometry))
        return template_word;
    uint64_t alias_word;
    if (!mido_physmap_alias_word(&geometry, geometry.first, &alias_word))
        return template_word;
    if (word_index == alias_word)
        return (MIDO_PHYSMAP_TOP + 56 * 4096ULL) | 3;
    if (!mido_physmap_alias_word(&geometry, geometry.rest, &alias_word))
        return template_word;
    if (word_index == alias_word)
        return (MIDO_PHYSMAP_TOP + 58 * 4096ULL) | 3;
    for (unsigned int index = 0; index < 6; ++index) {
        if (!mido_physmap_alias_word(&geometry, geometry.first + 0x400000ULL
                                    + (uint64_t)index * 0x200000ULL, &alias_word))
            return template_word;
        if (word_index == alias_word)
            return (0x12600000ULL + (uint64_t)index * 0x200000ULL) | 0x0060000000000601ULL;
    }
    return template_word;
}

unsigned long long mido_physmap_alias_pairs(uint64_t *pairs)
{
    struct mido_physmap_geometry geometry;
    if (!mido_physmap_geometry(&geometry))
        return 1ULL << 19;
    if (!mido_physmap_alias_word(&geometry, geometry.first, &pairs[0])
        || !mido_physmap_alias_word(&geometry, geometry.rest, &pairs[2]))
        return 1ULL << 19;
    pairs[1] = (MIDO_PHYSMAP_TOP + 56 * 4096ULL) | 3;
    pairs[3] = (MIDO_PHYSMAP_TOP + 58 * 4096ULL) | 3;
    for (unsigned int index = 0; index < 6; ++index) {
        if (!mido_physmap_alias_word(&geometry, geometry.first + 0x400000ULL
                                    + (uint64_t)index * 0x200000ULL, &pairs[4 + index * 2]))
            return 1ULL << 19;
        pairs[5 + index * 2] = (0x12600000ULL + (uint64_t)index * 0x200000ULL) | 0x0060000000000601ULL;
    }
    return 0;
}

unsigned long long mido_physmap_complete_status(void)
{
    struct mido_physmap_geometry geometry;
    if (!mido_physmap_geometry(&geometry))
        return 1ULL << 19;
    if (!mido_physmap_readable(MIDO_PHYSMAP_PTOV_PA, 192, 8)
        || !mido_physmap_readable(MIDO_PHYSMAP_INDEX_PA, 4, 4))
        return 1ULL << 18;
    uint64_t failures = 0;
    if (*(const volatile uint32_t *)MIDO_PHYSMAP_INDEX_PA != 2)
        failures |= 1ULL << 18;
    for (unsigned int index = 0; index < 24; ++index) {
        uint64_t expected = 0;
        switch (index) {
        case 0:
            expected = MIDO_PHYSMAP_TOP;
            break;
        case 1:
            expected = geometry.rest;
            break;
        case 2:
            expected = 0x13200000ULL - MIDO_PHYSMAP_TOP;
            break;
        case 3:
            expected = MIDO_PHYSMAP_PHYSICAL;
            break;
        case 4:
            expected = geometry.first;
            break;
        case 5:
            expected = 0x4000;
            break;
        default:
            break;
        }
        uint64_t observed = *(const volatile uint64_t *)(MIDO_PHYSMAP_PTOV_PA + index * 8ULL);
        if (observed != expected)
            failures |= 1ULL << 18;
    }
    return failures;
}
