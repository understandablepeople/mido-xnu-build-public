#include <cassert>
#include <cstdint>
#include <cstring>
#include <string>
#include <vector>
#include "mido_wcnss_loader.h"

static std::vector<uint8_t> memory(MIDO_PRONTO_BYTES, 0xa5);
static unsigned steps, fail_at, secure_calls;
static bool secure_error;
static std::string events;
static int step() { return ++steps == fail_at ? -1 : 0; }
static int ready(void *) { events += 'r'; return step() ? 0 : 1; }
static int write(void *, uint64_t physical, const uint8_t *data, size_t bytes)
{
    events += 'w';
    assert(mido_pronto_inside(physical, bytes));
    if (step()) return -1;
    std::memcpy(memory.data() + physical - MIDO_PRONTO_BASE, data, bytes);
    return 0;
}
static int zero(void *, uint64_t physical, size_t bytes)
{
    events += 'z';
    assert(mido_pronto_inside(physical, bytes));
    if (step()) return -1;
    std::memset(memory.data() + physical - MIDO_PRONTO_BASE, 0, bytes);
    return 0;
}
static int clean(void *, uint64_t physical, size_t bytes)
{
    events += 'c';
    assert(mido_pronto_inside(physical, bytes));
    return step();
}
static int64_t call(void *, uint32_t function, uint32_t info,
    const uint64_t *arguments, uint64_t *returned)
{
    events += 'p';
    static const uint32_t functions[] = {0x02000201, 0x02000202, 0x02000205};
    static const uint32_t infos[] = {0x82, 3, 1};
    assert(secure_calls < 3 && function == functions[secure_calls]);
    assert(info == infos[secure_calls] && arguments[0] == 6);
    if (secure_calls == 0) {
        assert(arguments[1] == MIDO_PRONTO_BASE + 0x6f0000 && !arguments[2]);
    } else if (secure_calls == 1) {
        assert(arguments[1] == MIDO_PRONTO_BASE && arguments[2] == 0x3000);
    } else {
        assert(!arguments[1] && !arguments[2]);
    }
    secure_calls++;
    if (step()) {
        *returned = secure_error ? 0x1234 : 0;
        return secure_error ? 0 : -12;
    }
    *returned = 0;
    return 0;
}
static void reset(unsigned failure = 0)
{
    steps = secure_calls = 0;
    events.clear();
    fail_at = failure;
    secure_error = false;
    std::fill(memory.begin(), memory.end(), 0xa5);
}
int main()
{
    uint8_t metadata[64] = {0x7f, 0x45, 0x4c, 0x46};
    uint8_t payload[8] = {1, 2, 3, 4, 5, 6, 7, 8};
    mido_pronto_segment segments[] = {
        {MIDO_PRONTO_BASE, payload, sizeof(payload), 16},
        {MIDO_PRONTO_BASE + 0x2000, nullptr, 0, 0x1000}
    };
    mido_pronto_image image = {metadata, sizeof(metadata), MIDO_PRONTO_BASE + 0x6f0000,
        0x3000, segments, 2};
    mido_pronto_ops ops = {nullptr, ready, write, zero, clean, call};
    mido_pronto_result result = {};
    reset();
    assert(mido_pronto_load(&image, &ops, &result) == 0);
    assert(result.stage == MIDO_PRONTO_AUTHENTICATED && result.copied_segments == 2);
    assert(secure_calls == 3 && !result.error);
    assert(!std::memcmp(memory.data(), payload, sizeof(payload)));
    for (unsigned index = 8; index < 16; index++) assert(memory[index] == 0);
    for (unsigned index = 0x2000; index < 0x3000; index++) assert(memory[index] == 0);
    assert(memory[16] == 0xa5 && memory[0x3000] == 0xa5);
    assert(!std::memcmp(memory.data() + 0x6f0000, metadata, sizeof(metadata)));
    unsigned successful_steps = steps;
    const std::string expected = "rwcppwzczcrp";
    assert(events == expected);
    assert(mido_pronto_load(&image, &ops, &result) == -1 && steps == successful_steps);
    for (unsigned failure = 1; failure <= successful_steps; failure++) {
        reset(failure); result = {};
        assert(mido_pronto_load(&image, &ops, &result) < 0);
        assert(result.error < 0 && result.stage != MIDO_PRONTO_AUTHENTICATED);
        assert(steps == failure);
        assert(events == expected.substr(0, failure));
        if (result.stage != MIDO_PRONTO_IDLE) {
            assert(mido_pronto_load(&image, &ops, &result) == -1 && steps == failure);
        }
    }
    for (unsigned failure : {4U, 5U, successful_steps}) {
        reset(failure); secure_error = true; result = {};
        assert(mido_pronto_load(&image, &ops, &result) == -5);
        assert(result.transport == 0 && result.secure == 0x1234 && steps == failure);
    }
    for (unsigned invalid = 0; invalid < 12; invalid++) {
        auto candidate = image;
        mido_pronto_segment changed[] = {segments[0], segments[1]};
        candidate.segments = changed;
        switch (invalid) {
        case 0: candidate.segment_count = 33; break;
        case 1: candidate.metadata_physical = MIDO_PRONTO_BASE; break;
        case 2: candidate.allocation_bytes = MIDO_PRONTO_BYTES + 4096; break;
        case 3: candidate.metadata_bytes = 65537; break;
        case 4: changed[0].physical = UINT64_MAX - 7; break;
        case 5: changed[0].file_bytes = 17; break;
        case 6: changed[1].physical = MIDO_PRONTO_BASE + 8; break;
        case 7: changed[0].data = nullptr; break;
        case 8: changed[1].memory_bytes = 0x2000; break;
        case 9: candidate.allocation_bytes--; break;
        case 10: candidate.metadata_physical++; break;
        case 11: candidate.metadata = nullptr; break;
        }
        reset(); result = {};
        assert(mido_pronto_load(&candidate, &ops, &result) == -1 && !steps);
    }
    reset(); result = {};
    auto missing = ops; missing.clean = nullptr;
    assert(mido_pronto_load(&image, &missing, &result) == -1 && !steps);
    assert(mido_pronto_load(&image, &ops, nullptr) == -1 && !steps);
    return 0;
}
