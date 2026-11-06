#include <cassert>
#include <cstdint>
#include <cstring>
#include <vector>
#include <string>
using vm_offset_t = uintptr_t;
#define VM_WIMG_WCOMB 9U
static unsigned maps, unmaps, calls, barriers, ready_calls, unavailable, error_call, fail_ready;
static unsigned mutation_calls;
static bool map_failure, secure_failure;
static std::vector<uint8_t> ram(0x700000, 0xa5);
static std::string events;
static void IOLog(const char *, ...) {}
static void IODelay(unsigned value) { assert(value == 10); }
static bool PE_parse_boot_argn(const char *, void *, int) { return false; }
static vm_offset_t ml_io_map_unmappable(vm_offset_t physical, size_t bytes, unsigned flags)
{
    assert(physical == 0x8e700000 && bytes == ram.size() && flags == VM_WIMG_WCOMB);
    events += 'm'; maps++;
    return map_failure ? 0 : (vm_offset_t)ram.data();
}
static void ml_io_unmap(vm_offset_t address, size_t bytes)
{
    assert(address == (vm_offset_t)ram.data() && bytes == ram.size());
    events += 'u'; unmaps++;
}
static void sync() { barriers++; events += 'b'; }
#define MIDO_PRONTO_SYNC() sync()
struct mido_scm_registers;
static void invoke(mido_scm_registers *state);
#define MIDO_SCM_INVOKE(state) invoke(state)
#include "mido_wcnss_memory.h"
static void invoke(mido_scm_registers *state)
{
    calls++;
    uint32_t function = (uint32_t)state->values[0];
    if (function == 0xc2000601U) {
        assert(state->values[1] == 1 && !maps && !mutation_calls);
        static const uint64_t queries[] = {0x82000601, 0x02000201, 0x02000202, 0x02000205, 0x02000207};
        assert(calls <= 5 && state->values[2] == queries[calls - 1]);
        events += 'q';
    } else if (function == 0x42000207U) {
        assert(calls == 6 && state->values[1] == 1 && state->values[2] == 6 && !maps);
        events += 'q';
    } else {
        const uint32_t functions[] = {0x42000201U, 0x42000202U, 0x42000205U};
        const uint32_t infos[] = {0x82, 3, 1};
        assert(mutation_calls < 3 && function == functions[mutation_calls]);
        assert(state->values[1] == infos[mutation_calls] && state->values[2] == 6);
        assert(maps == 1 && !unmaps && events.back() == 'b');
        if (!mutation_calls) {
            assert(state->values[3] == 0x8edfe000 && !state->values[4]);
            assert(ram[0x6fe000] == 0x7f && ram[0] == 0xa5);
        } else if (mutation_calls == 1) {
            assert(state->values[3] == 0x8e700000 && state->values[4] == 4096);
        } else {
            assert(!state->values[3] && !state->values[4]);
            assert(ram[0] == 0x11 && ram[1] == 0x22 && ram[2] == 0 && ram[15] == 0);
        }
        mutation_calls++;
        events += 'p';
    }
    state->values[0] = calls == error_call && !secure_failure ? 0xfffffffeU : 0;
    state->values[1] = calls == error_call && secure_failure ? 9 :
        (function == 0xc2000601U || function == 0x42000207U ? calls != unavailable : 0);
}
static int ready(void *) { return ++ready_calls == fail_ready ? 0 : 1; }
static void reset()
{
    maps = unmaps = calls = barriers = ready_calls = unavailable = error_call = fail_ready = mutation_calls = 0;
    map_failure = secure_failure = false;
    events.clear();
    std::fill(ram.begin(), ram.end(), 0xa5);
}
int main()
{
    uint8_t metadata[] = {0x7f, 0x45, 0x4c, 0x46}, payload[] = {0x11, 0x22};
    mido_pronto_segment segment = {0x8e700000, payload, sizeof(payload), 16};
    mido_pronto_image image = {metadata, sizeof(metadata), 0x8edfe000, 4096, &segment, 1};
    mido_pronto_memory memory = {};
    memory.dependencies_ready = ready;
    reset();
    assert(!mido_pronto_memory_load(&memory, &image, 0x20000000, 0x40000000));
    assert(memory.result.stage == MIDO_PRONTO_AUTHENTICATED && !memory.mapping);
    assert(maps == 1 && unmaps == 1 && mutation_calls == 3);
    assert(events.substr(0, 7) == "qqqqqqm" && events.back() == 'u');
    unsigned total_ready = ready_calls;
    unsigned total_calls = calls;
    assert(mido_pronto_memory_load(&memory, &image, 0x20000000, 0x40000000) == -11);
    assert(calls == total_calls && maps == 1);
    for (unsigned failure = 1; failure <= total_ready; failure++) {
        reset(); memory = {}; memory.dependencies_ready = ready; fail_ready = failure;
        assert(mido_pronto_memory_load(&memory, &image, 0x20000000, 0x40000000) < 0);
        assert(mutation_calls < 3 && !memory.mapping && unmaps == maps);
        assert(ready_calls == failure);
    }
    for (unsigned failure = 1; failure <= 9; failure++) {
        reset(); memory = {}; memory.dependencies_ready = ready; error_call = failure;
        assert(mido_pronto_memory_load(&memory, &image, 0x20000000, 0x40000000) < 0);
        assert(calls == failure && !memory.mapping && maps == unmaps);
        if (failure <= 6) assert(!maps && !mutation_calls);
    }
    for (unsigned failure = 7; failure <= 9; failure++) {
        reset(); memory = {}; memory.dependencies_ready = ready; error_call = failure; secure_failure = true;
        assert(mido_pronto_memory_load(&memory, &image, 0x20000000, 0x40000000) == -5);
        assert(memory.result.transport == 0 && memory.result.secure == 9 && unmaps == 1);
    }
    for (unsigned absent = 1; absent <= 6; absent++) {
        reset(); memory = {}; memory.dependencies_ready = ready; unavailable = absent;
        assert(mido_pronto_memory_load(&memory, &image, 0x20000000, 0x40000000) == -13);
        assert(!maps && calls == absent);
    }
    reset(); memory = {}; memory.dependencies_ready = ready; map_failure = true;
    assert(mido_pronto_memory_load(&memory, &image, 0x20000000, 0x40000000) == -14);
    assert(maps == 1 && !unmaps && !mutation_calls);
    for (unsigned bad = 0; bad < 4; bad++) {
        reset(); memory = {}; memory.dependencies_ready = ready;
        uint64_t base = bad == 0 ? MIDO_PRONTO_BASE : bad == 1 ? UINT64_MAX : 0x20000000;
        uint64_t bytes = bad == 2 ? 0 : 0x40000000;
        if (bad == 3) memory.dependencies_ready = nullptr;
        assert(mido_pronto_memory_load(&memory, &image, base, bytes) == -10);
        assert(!maps && !calls && !ready_calls);
    }
    reset(); memory = {}; memory.dependencies_ready = ready;
    uint64_t arguments[] = {6, 0, 0}, secure = 0;
    memory.mapping = (vm_offset_t)ram.data();
    for (uint32_t function : {0x02000206U, 0x02000207U, 0x02000201U}) {
        assert(mido_pronto_memory_call(&memory, function, 1, arguments, &secure) == -1 && !calls);
    }
    assert(mido_pronto_memory_write(&memory, MIDO_PRONTO_BASE - 1, payload, 1) == -1);
    assert(mido_pronto_memory_zero(&memory, MIDO_PRONTO_BASE + MIDO_PRONTO_BYTES, 1) == -1);
    assert(mido_pronto_memory_clean(&memory, UINT64_MAX, 4096) == -1);
    return 0;
}
