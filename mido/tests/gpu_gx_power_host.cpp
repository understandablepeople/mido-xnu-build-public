#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <initializer_list>

typedef uintptr_t vm_offset_t;
static uint32_t registers[0x8000 / 4], acc_page[0x1000 / 4];
static unsigned mode, mappings, writes, delays, root_reads, gx_reads;
static unsigned root_ready, gx_ready, fail_map, fail_write;
static bool PE_parse_boot_argn(const char *name, void *output, int size)
{
    assert(!std::strcmp(name, "midogpugx") && size == sizeof(mode));
    std::memcpy(output, &mode, sizeof(mode));
    return true;
}
static vm_offset_t ml_io_map(vm_offset_t address, size_t bytes)
{
    mappings++;
    if (mappings == fail_map) return 0;
    if (address == 0x01858000 && bytes == sizeof(registers)) return (vm_offset_t)registers;
    assert(address == 0x01944000 && bytes == sizeof(acc_page));
    return (vm_offset_t)acc_page;
}
static void IOLog(const char *, ...) {}
static void IODelay(unsigned value) { assert(value == 1); delays++; }
static uint32_t load(volatile uint32_t *target)
{
    if (target == registers + 0x1000 / 4 && writes >= 3) {
        root_reads++;
        return *target & (root_reads >= root_ready ? ~0x80000000U : ~0U);
    }
    if (target == registers + 0x101c / 4 && writes >= 4) {
        gx_reads++;
        return *target | (gx_reads >= gx_ready ? 0xa0000000U : 0U);
    }
    assert((target >= registers && target < registers + sizeof(registers) / 4) || target == acc_page + 0x15c / 4);
    return *target;
}
static void store(volatile uint32_t *target, uint32_t value)
{
    volatile uint32_t *expected[] = {acc_page + 0x15c / 4, registers + 0x300c / 4,
        registers + 0x1000 / 4, registers + 0x101c / 4};
    assert(writes < 4 && target == expected[writes]);
    if (writes == 0) assert(value == 0xa5a50000);
    if (writes == 1) assert(value == 0x1100);
    if (writes == 2) assert(value == 0x80000002);
    if (writes == 3) assert(value == 0x08225800);
    writes++;
    *target = writes == fail_write ? value ^ 1U : value;
}
#define MIDO_GPU_GX_LOAD(target) load(target)
#define MIDO_GPU_GX_STORE(target, value) store(target, value)
#include "mido_gpu_gx_power.h"
static void reset()
{
    std::memset(registers, 0, sizeof(registers));
    std::memset(acc_page, 0, sizeof(acc_page));
    registers[0x1000 / 4] = 0x80000000;
    registers[0x101c / 4] = 0x08225801;
    registers[0x104c / 4] = 0xa0222800;
    registers[0x300c / 4] = 0x1101;
    registers[0x701c / 4] = 0x20000038;
    registers[0x7028 / 4] = 2;
    for (unsigned offset : {0x1020U, 0x1028U, 0x1030U, 0x1040U, 0x1044U}) registers[offset / 4] = 0x80000000;
    acc_page[0x15c / 4] = 0xa5a50001;
    mode = root_ready = gx_ready = 1;
    mappings = writes = delays = root_reads = gx_reads = fail_map = fail_write = 0;
}
int main()
{
    reset(); mode = 0; assert(mido_gpu_gx_power(-1, -1) == 0 && mappings == 0);
    reset(); mode = 2; assert(mido_gpu_gx_power(1, 1) == -1 && mappings == 0);
    reset(); assert(mido_gpu_gx_power(0, 1) == -1 && mappings == 0);
    reset(); assert(mido_gpu_gx_power(1, 0) == -1 && mappings == 0);
    for (unsigned failed : {1U, 2U}) { reset(); fail_map = failed; assert(mido_gpu_gx_power(1, 1) == -2 && writes == 0); }
    for (unsigned offset : {0x1000U, 0x1004U, 0x101cU, 0x104cU, 0x701cU}) {
        reset(); registers[offset / 4] ^= 1U;
        assert(mido_gpu_gx_power(1, 1) == -3 && writes == 0);
    }
    for (unsigned offset : {0x1020U, 0x1028U, 0x1030U, 0x1040U, 0x1044U}) {
        reset(); registers[offset / 4] |= 1U;
        assert(mido_gpu_gx_power(1, 1) == -3 && writes == 0);
    }
    for (unsigned failed : {1U, 2U, 3U, 4U}) {
        reset(); fail_write = failed;
        int result = mido_gpu_gx_power(1, 1);
        assert(result == (failed == 1 ? -4 : failed == 2 ? -5 : failed == 3 ? -6 : -8));
        assert(writes == failed);
    }
    reset(); root_ready = 1000; gx_ready = 1000;
    assert(mido_gpu_gx_power(1, 1) == 1 && writes == 4 && root_reads == 1001 && gx_reads == 1000);
    reset(); root_ready = 1001;
    assert(mido_gpu_gx_power(1, 1) == -7 && writes == 3 && delays == 1000);
    reset(); gx_ready = 1001;
    assert(mido_gpu_gx_power(1, 1) == -10 && writes == 4 && gx_reads == 1000);
    reset(); registers[0x7028 / 4] = 0;
    assert(mido_gpu_gx_power(1, 1) == -9 && writes == 4);
    reset(); assert(mido_gpu_gx_power(1, 1) == 1 && writes == 4);
    return 0;
}
