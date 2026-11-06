#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <initializer_list>

typedef uintptr_t vm_offset_t;
#define VM_WIMG_IO 7U
static uint32_t clocks[0x8000 / 4], gpu[0x10000 / 4], crypto[1024], votes[1024], pll[1024];
static unsigned mode, maps, unmaps, fail_map, gpu_reads, wifi_reads;
static bool gpu_mode;
static bool backend_ready;
extern "C" bool sweet_gpu_ready(void) { return backend_ready; }
static void IOLog(const char *, ...) {}
static bool PE_parse_boot_argn(const char *name, void *output, int size)
{
    assert(!std::strcmp(name, gpu_mode ? "midogpustatus" : "midowificlocks"));
    assert(size == sizeof(mode));
    std::memcpy(output, &mode, sizeof(mode));
    return true;
}
static vm_offset_t ml_io_map_unmappable(vm_offset_t address, size_t bytes, unsigned flags)
{
    assert(flags == VM_WIMG_IO);
    maps++;
    uint32_t *target = nullptr;
    if (gpu_mode) {
        if (address == 0x01858000) { assert(bytes == sizeof(clocks)); target = clocks; }
        else { assert(address == 0x01c00000 && bytes == sizeof(gpu)); target = gpu; }
    } else {
        assert(bytes == 4096);
        if (address == 0x01816000) target = crypto;
        else if (address == 0x01845000) target = votes;
        else { assert(address == 0x01821000); target = pll; }
    }
    return maps == fail_map ? 0 : (vm_offset_t)target;
}
static void ml_io_unmap(vm_offset_t address, size_t bytes)
{
    if (gpu_mode) assert((address == (vm_offset_t)clocks && bytes == sizeof(clocks)) ||
        (address == (vm_offset_t)gpu && bytes == sizeof(gpu)));
    else assert(bytes == 4096 && (address == (vm_offset_t)crypto || address == (vm_offset_t)votes || address == (vm_offset_t)pll));
    unmaps++;
}
static uint32_t load(volatile uint32_t *target)
{
    uintptr_t address = (uintptr_t)target;
    if (address >= (uintptr_t)gpu && address < (uintptr_t)gpu + sizeof(gpu)) {
        unsigned offsets[] = {0x4f5, 0x530, 0x4f4, 0x3000};
        assert(gpu_mode && gpu_reads < 4 && target == gpu + offsets[gpu_reads]);
        gpu_reads++;
    } else if (address >= (uintptr_t)clocks && address < (uintptr_t)clocks + sizeof(clocks)) {
        assert(gpu_mode);
    } else {
        volatile uint32_t *expected[] = {crypto + 1, crypto + 2, crypto + 7, crypto + 8,
            crypto + 9, votes, votes + 1, pll};
        assert(!gpu_mode && wifi_reads < 8 && target == expected[wifi_reads]);
        wifi_reads++;
    }
    return *target;
}
#define MIDO_GPU_GX_LOAD(target) load(target)
#include "mido_gpu_status.h"
#include "mido_wcnss_clocks.h"
static void reset(bool selected = true)
{
    gpu_mode = selected; mode = 1;
    backend_ready = true;
    maps = unmaps = fail_map = gpu_reads = wifi_reads = 0;
    std::memset(clocks, 0, sizeof(clocks));
    clocks[0x1000 / 4] = 2;
    clocks[0x104c / 4] = clocks[0x101c / 4] = 0xa0222800;
    clocks[0x7028 / 4] = 3;
    for (unsigned offset : {0x1028U, 0x1030U, 0x1034U, 0x1040U, 0x1044U, 0x1020U}) clocks[offset / 4] = 1;
    gpu[0x3000] = 0x1234;
}
int main()
{
    reset(); backend_ready = false;
    assert(mido_gpu_status(1) == -6 && maps == 0 && gpu_reads == 0);
    reset(); mode = 0; assert(mido_gpu_status(1) == 0 && maps == 0);
    reset(); mode = 2; assert(mido_gpu_status(1) == -1 && maps == 0);
    reset(); assert(mido_gpu_status(0) == -1 && maps == 0);
    reset(); fail_map = 1; assert(mido_gpu_status(1) == -2 && unmaps == 0);
    reset(); fail_map = 2; assert(mido_gpu_status(1) == -4 && unmaps == 1);
    for (unsigned offset : {0x1000U, 0x1004U, 0x104cU, 0x101cU, 0x300cU, 0x7028U,
        0x1028U, 0x1030U, 0x1034U, 0x1040U, 0x1044U, 0x1020U}) {
        reset(); clocks[offset / 4] ^= 1;
        assert(mido_gpu_status(1) == -3 && maps == 1 && unmaps == 1 && gpu_reads == 0);
    }
    reset(); assert(mido_gpu_status(1) == 1 && gpu_reads == 4 && unmaps == 2);
    reset(); clocks[0x1028 / 4] = 0x20008001;
    assert(mido_gpu_status(1) == 1 && gpu_reads == 4 && unmaps == 2);
    for (unsigned nibble = 1; nibble < 16; nibble++) {
        if (nibble == 2) continue;
        reset(); clocks[0x1028 / 4] = (nibble << 28) | 1;
        assert(mido_gpu_status(1) == -3 && gpu_reads == 0 && unmaps == 1);
    }
    for (uint32_t value : {0U, 0xffffffffU}) {
        reset(); gpu[0x3000] = value;
        assert(mido_gpu_status(1) == -5 && gpu_reads == 4 && unmaps == 2);
    }
    reset(false); mode = 0; assert(mido_wcnss_clocks() == 0 && maps == 0);
    reset(false); mode = 2; assert(mido_wcnss_clocks() == -1 && maps == 0);
    for (unsigned failed = 1; failed <= 3; failed++) {
        reset(false); fail_map = failed;
        assert(mido_wcnss_clocks() == -2 && maps == 3 && unmaps == 2 && wifi_reads == 0);
    }
    reset(false); assert(mido_wcnss_clocks() == 1 && wifi_reads == 8 && unmaps == 3);
    return 0;
}
