#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
#include "mido_wcnss_bundle.h"
using DTEntry = const void *;
static const int kSuccess = 1;
static unsigned failure, loads, lookups;
static uint8_t arena_base[8] = {0, 0, 0, 0x20}, arena_size[8] = {0, 0, 0, 0x40};
static std::vector<uint8_t> bundle(128);
static void IOLog(const char *, ...) {}
static int SecureDTLookupEntry(DTEntry start, const char *path, DTEntry *chosen)
{
    lookups++;
    assert(!start && !std::strcmp(path, "/chosen"));
    *chosen = &failure;
    return failure == 1 ? -1 : 1;
}
static int SecureDTGetProperty(DTEntry chosen, const char *name, const void **output, unsigned *bytes)
{
    assert(chosen == &failure);
    if (!std::strcmp(name, "mido-pronto-bundle")) {
        if (failure == 2) return -1;
        *output = bundle.data(); *bytes = (unsigned)bundle.size();
    } else if (!std::strcmp(name, "dram-base")) {
        if (failure == 3) return -1;
        *output = arena_base; *bytes = failure == 4 ? 4 : 8;
    } else {
        assert(!std::strcmp(name, "dram-size"));
        if (failure == 5) return -1;
        *output = failure == 7 ? nullptr : arena_size; *bytes = failure == 6 ? 4 : 8;
    }
    return 1;
}
#define MIDO_WCNSS_MEMORY_H
struct mido_pronto_memory { mido_pronto_result result; };
static int mido_pronto_memory_load(mido_pronto_memory *memory, const mido_pronto_image *image,
    uint64_t base, uint64_t bytes)
{
    assert(memory && image && base == 0x20000000 && bytes == 0x40000000);
    assert(image->segment_count == 1 && image->segments[0].physical == MIDO_PRONTO_BASE);
    loads++;
    return -42;
}
#include "mido_wcnss_start.h"
static void put(size_t offset, uint64_t value)
{
    for (unsigned index = 0; index < 8; index++) bundle[offset + index] = uint8_t(value >> (index * 8));
}
int main()
{
    std::memcpy(bundle.data(), "MIDOPRNT", 8);
    put(8, (1ULL << 32) | 1); put(16, 4096); put(24, 0x8edfe000);
    put(32, 88); put(40, 4); put(48, bundle.size());
    put(56, MIDO_PRONTO_BASE); put(64, 96); put(72, 2); put(80, 16);
    mido_pronto_memory memory = {};
    assert(mido_pronto_start_from_adt(nullptr) == -10 && !lookups);
    assert(mido_pronto_start_from_adt(&memory) == -42 && loads == 1);
    for (unsigned missing = 1; missing <= 7; missing++) {
        failure = missing;
        assert(mido_pronto_start_from_adt(&memory) == -20 && loads == 1);
    }
    failure = 0; bundle[0] = 0;
    assert(mido_pronto_start_from_adt(&memory) == -21 && loads == 1);
    return 0;
}
