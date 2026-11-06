#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <initializer_list>

typedef uintptr_t vm_offset_t;
#define VM_WIMG_IO 7U
static uint32_t registers[0x8000 / 4], pll[0x1000 / 4], votes[0x1000 / 4];
static unsigned mode, maps, unmaps, writes, fail_map, fail_write, polls, ready;
static bool bad_command, lost_lock;
static void IOLog(const char *, ...) {}
static void IODelay(unsigned value) { assert(value == 1); }
static bool PE_parse_boot_argn(const char *name, void *output, int bytes)
{
    assert(!std::strcmp(name, "midogpurate") && bytes == sizeof(mode));
    std::memcpy(output, &mode, sizeof(mode)); return true;
}
static vm_offset_t ml_io_map_unmappable(vm_offset_t address, size_t bytes, unsigned flags)
{
    assert(flags == VM_WIMG_IO);
    maps++;
    if (address == 0x01858000) { assert(bytes == sizeof(registers)); return maps == fail_map ? 0 : (vm_offset_t)registers; }
    assert(bytes == sizeof(pll));
    if (address == 0x01821000) return maps == fail_map ? 0 : (vm_offset_t)pll;
    assert(address == 0x01845000); return maps == fail_map ? 0 : (vm_offset_t)votes;
}
static void ml_io_unmap(vm_offset_t address, size_t bytes)
{
    assert((address == (vm_offset_t)registers && bytes == sizeof(registers)) ||
        ((address == (vm_offset_t)pll || address == (vm_offset_t)votes) && bytes == sizeof(pll)));
    unmaps++;
}
static uint32_t load(volatile uint32_t *target)
{
    if (writes == 3 && target == registers + 0x1000 / 4) {
        polls++;
        if (polls >= ready) return bad_command ? 0x80000002U : 2U;
    }
    if (writes == 3 && lost_lock && target == pll) return *target & ~(1U << 30);
    return *target;
}
static void store(volatile uint32_t *target, uint32_t value)
{
    assert(writes < 3);
    if (writes == 0) assert(target == votes && value == 0xa5U);
    if (writes == 1) assert(target == registers + 0x1004 / 4 && value == 0x505U);
    if (writes == 2) assert(target == registers + 0x1000 / 4 && value == 3U);
    writes++; *target = writes == fail_write ? value ^ 1U : value;
}
#define MIDO_GPU_GX_LOAD(target) load(target)
#define MIDO_GPU_GX_STORE(target, value) store(target, value)
#include "mido_gpu_rate.h"

static void reset()
{
    std::memset(registers, 0, sizeof(registers));
    std::memset(pll, 0, sizeof(pll)); std::memset(votes, 0, sizeof(votes));
    mode = ready = 1; maps = unmaps = writes = fail_map = fail_write = polls = 0;
    bad_command = lost_lock = false;
    registers[0x1000 / 4] = 2;
    registers[0x104c / 4] = 0xa0222800; registers[0x101c / 4] = 0xa0225800;
    registers[0x7028 / 4] = 3;
    for (unsigned offset : {0x1020U, 0x1028U, 0x1030U, 0x1034U, 0x1040U, 0x1044U}) {
        registers[offset / 4] = 1;
    }
    registers[0x1020 / 4] |= 0x6000U;
    pll[0] = 0xc0118000; votes[0] = 0xa4;
}
int main()
{
    reset(); mode = 0; assert(mido_gpu_rate(1) == 0 && maps == 0);
    reset(); mode = 2; assert(mido_gpu_rate(1) == -1 && maps == 0);
    reset(); assert(mido_gpu_rate(0) == -1 && maps == 0);
    for (unsigned failure = 1; failure <= 3; failure++) {
        reset(); fail_map = failure;
        assert(mido_gpu_rate(1) == -2 && maps == 3 && unmaps == 2 && writes == 0);
    }
    for (unsigned offset : {0x1000U, 0x1004U, 0x104cU, 0x101cU, 0x300cU, 0x7028U,
        0x1020U, 0x1028U, 0x1030U, 0x1034U, 0x1040U, 0x1044U}) {
        reset(); registers[offset / 4] ^= 1;
        assert(mido_gpu_rate(1) == -3 && writes == 0 && unmaps == 3);
    }
    reset(); pll[0] &= ~(1U << 30);
    assert(mido_gpu_rate(1) == -3 && writes == 0 && unmaps == 3);
    for (uint32_t bit : {0x2000U, 0x4000U, 0x6000U}) {
        reset(); registers[0x1020 / 4] &= ~bit;
        assert(mido_gpu_rate(1) == -3 && writes == 0 && unmaps == 3);
    }
    reset(); fail_write = 1; assert(mido_gpu_rate(1) == -4 && writes == 1 && unmaps == 3);
    reset(); fail_write = 2; assert(mido_gpu_rate(1) == -5 && writes == 2 && unmaps == 3);
    reset(); bad_command = true; assert(mido_gpu_rate(1) == -6 && writes == 3 && unmaps == 3);
    reset(); lost_lock = true; assert(mido_gpu_rate(1) == -6 && unmaps == 3);
    reset(); ready = 1001; assert(mido_gpu_rate(1) == -7 && polls == 1000 && unmaps == 3);
    reset(); ready = 1000; assert(mido_gpu_rate(1) == 1 && polls == 1000 && unmaps == 3);
    reset(); assert(mido_gpu_rate(1) == 1 && writes == 3 && unmaps == 3);
    assert(votes[0] == 0xa5 && registers[0x1004 / 4] == 0x505);
    return 0;
}
