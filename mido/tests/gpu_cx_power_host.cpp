#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <initializer_list>

typedef uintptr_t vm_offset_t;
static uint32_t registers[0x8000 / 4];
static unsigned mode, mappings, writes, delays, reads, ready_after;
static uint32_t status_bits, mismatch_bits;
static int mismatch, failed_mapping;
static bool PE_parse_boot_argn(const char *name, void *output, int size)
{
    assert(!std::strcmp(name, "midogpucxpower") && size == sizeof(mode));
    std::memcpy(output, &mode, sizeof(mode));
    return true;
}
static vm_offset_t ml_io_map(vm_offset_t address, size_t bytes)
{
    assert(address == 0x01858000 && bytes == sizeof(registers));
    mappings++;
    return failed_mapping ? 0 : (vm_offset_t)registers;
}
static void IOLog(const char *, ...) {}
static void IODelay(unsigned value) { assert(value == 1); delays++; }
static uint32_t load(volatile uint32_t *target)
{
    assert(target >= registers && target < registers + sizeof(registers) / 4);
    if (target == registers + (0x5904c - 0x58000) / 4 && writes) {
        reads++;
        return (*target | status_bits | (reads >= ready_after ? 0x80000000U : 0U)) ^
            (mismatch ? mismatch_bits : 0U);
    }
    return *target;
}
static void store(volatile uint32_t *target, uint32_t value)
{
    assert(target == registers + (0x5904c - 0x58000) / 4);
    assert(value == 0x00222800);
    *target = value;
    writes++;
}
#define MIDO_GPU_CX_LOAD(target) load(target)
#define MIDO_GPU_CX_STORE(target, value) store(target, value)
#include "mido_gpu_cx_power.h"
static void reset(unsigned selected)
{
    std::memset(registers, 0, sizeof(registers));
    registers[(0x5904c - 0x58000) / 4] = 0x00222801;
    registers[(0x5901c - 0x58000) / 4] = 0x08225801;
    registers[(0x5f01c - 0x58000) / 4] = 0x20000038;
    mode = selected;
    mappings = writes = delays = reads = 0;
    ready_after = 1;
    mismatch = failed_mapping = 0;
    status_bits = 0;
    mismatch_bits = 2U;
}
int main()
{
    reset(0);
    assert(mido_gpu_cx_power(0, 1) == 0 && mappings == 0);
    for (unsigned selected : {2U, 3U}) {
        reset(selected);
        assert(mido_gpu_cx_power(0, 1) == -1 && mappings == 0);
    }
    reset(1);
    assert(mido_gpu_cx_power(-9, 1) == -1 && mappings == 0);
    assert(mido_gpu_cx_power(0, -4) == -1 && mappings == 0);
    failed_mapping = 1;
    assert(mido_gpu_cx_power(0, 1) == -2 && writes == 0);
    for (unsigned offset : {0x5901cU, 0x5904cU, 0x5f01cU}) {
        reset(1);
        registers[(offset - 0x58000) / 4] = 0;
        assert(mido_gpu_cx_power(0, 1) == -3 && writes == 0);
    }
    reset(1);
    ready_after = 1000;
    assert(mido_gpu_cx_power(0, 1) == 1 && writes == 1 && reads == 1000 && delays == 1000);
    reset(1);
    ready_after = 1001;
    assert(mido_gpu_cx_power(0, 1) == -5 && writes == 1 && delays == 1001);
    reset(1);
    status_bits = 0x20000000U;
    assert(mido_gpu_cx_power(0, 1) == 1 && writes == 1 && reads == 1);
    reset(1);
    status_bits = 0x20000000U;
    ready_after = 1001;
    assert(mido_gpu_cx_power(0, 1) == -5 && writes == 1 && delays == 1001);
    for (uint32_t changed : {1U, 2U, 4U, 0x1000U, 0x10000U, 0x100000U}) {
        reset(1);
        status_bits = 0x20000000U;
        mismatch = 1;
        mismatch_bits = changed;
        assert(mido_gpu_cx_power(0, 1) == -4 && writes == 1 && reads == 1);
    }
    return 0;
}
