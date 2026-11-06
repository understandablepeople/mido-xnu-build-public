#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <initializer_list>

typedef uintptr_t vm_offset_t;
#define VM_WIMG_IO 7U
static uint32_t registers[0x8000 / 4];
static unsigned mode, writes, maps, unmaps, reads, ready, failed, timeout_branch, mismatch_branch, on_status;
static bool map_failure;
static const unsigned offsets[] = {0x1028, 0x1030, 0x1034, 0x1040, 0x1044, 0x1020};
static void IOLog(const char *, ...) {}
static void IODelay(unsigned value) { assert(value == 1); }
static bool PE_parse_boot_argn(const char *name, void *output, int size)
{
    assert(!std::strcmp(name, "midogpuclocks") && size == sizeof(mode));
    std::memcpy(output, &mode, sizeof(mode));
    return true;
}
static vm_offset_t ml_io_map_unmappable(vm_offset_t address, size_t size, unsigned flags)
{
    assert(flags == VM_WIMG_IO);
    assert(address == 0x01858000 && size == sizeof(registers));
    maps++;
    return map_failure ? 0 : (vm_offset_t)registers;
}
static void ml_io_unmap(vm_offset_t address, size_t size)
{
    assert(address == (vm_offset_t)registers && size == sizeof(registers));
    unmaps++;
}
static uint32_t load(volatile uint32_t *target)
{
    assert(target >= registers && target < registers + sizeof(registers) / 4);
    if (writes && target == registers + offsets[writes - 1] / 4) {
        reads++;
        if (writes == mismatch_branch) return *target ^ 2U;
        if (writes != timeout_branch && reads >= ready) return (*target & ~0xf0000000U) | on_status;
    }
    return *target;
}
static void store(volatile uint32_t *target, uint32_t value)
{
    assert(writes < 6 && target == registers + offsets[writes] / 4);
    assert(value == 0x80004f01U);
    writes++; reads = 0;
    *target = writes == failed ? value ^ 1U : value;
}
#define MIDO_GPU_GX_LOAD(target) load(target)
#define MIDO_GPU_GX_STORE(target, value) store(target, value)
#include "mido_gpu_clocks.h"
static void reset()
{
    std::memset(registers, 0, sizeof(registers));
    mode = ready = 1;
    maps = unmaps = writes = reads = failed = timeout_branch = mismatch_branch = 0;
    map_failure = false; on_status = 0;
    registers[0x1000 / 4] = 2;
    registers[0x104c / 4] = 0xa0222800;
    registers[0x101c / 4] = 0xa0225800;
    registers[0x300c / 4] = 0x1100;
    registers[0x7028 / 4] = 3;
    for (unsigned offset : offsets) registers[offset / 4] = 0x80004f00;
}
int main()
{
    reset(); mode = 0; assert(mido_gpu_clocks(1) == 0 && maps == 0);
    reset(); mode = 2; assert(mido_gpu_clocks(1) == -1 && maps == 0);
    reset(); assert(mido_gpu_clocks(0) == -1 && maps == 0);
    reset(); map_failure = true; assert(mido_gpu_clocks(1) == -2 && unmaps == 0);
    for (unsigned offset : {0x1000U, 0x1004U, 0x104cU, 0x101cU, 0x300cU, 0x7028U}) {
        reset(); registers[offset / 4] ^= 1;
        assert(mido_gpu_clocks(1) == -3 && writes == 0 && unmaps == 1);
    }
    for (unsigned offset : offsets) {
        for (unsigned bit : {1U, 2U, 0x80000000U}) {
            reset(); registers[offset / 4] ^= bit;
            assert(mido_gpu_clocks(1) == -4 && writes == 0 && unmaps == 1);
        }
    }
    for (unsigned index = 1; index <= 6; index++) {
        reset(); failed = index;
        assert(mido_gpu_clocks(1) == -5 && writes == index && unmaps == 1);
        reset(); mismatch_branch = index;
        assert(mido_gpu_clocks(1) == -5 && writes == index && unmaps == 1);
        reset(); timeout_branch = index;
        assert(mido_gpu_clocks(1) == -6 && writes == index && reads == 1000 && unmaps == 1);
    }
    reset(); ready = 1000;
    assert(mido_gpu_clocks(1) == 1 && writes == 6 && reads == 1000 && unmaps == 1);
    reset(); assert(mido_gpu_clocks(1) == 1 && writes == 6 && unmaps == 1);
    reset(); on_status = 0x20000000U;
    assert(mido_gpu_clocks(1) == 1 && writes == 6 && unmaps == 1);
    for (unsigned nibble = 1; nibble < 16; nibble++) {
        if (nibble == 2) continue;
        reset(); on_status = nibble << 28;
        assert(mido_gpu_clocks(1) == -6 && writes == 1 && reads == 1000 && unmaps == 1);
    }
    reset(); registers[0x1028 / 4] = 0xa0004f00U;
    assert(mido_gpu_clocks(1) == -4 && writes == 0 && unmaps == 1);
    return 0;
}
