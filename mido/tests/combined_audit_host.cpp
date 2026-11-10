#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>
#include <initializer_list>

typedef uintptr_t vm_offset_t;
#define VM_WIMG_IO 7U
static uint32_t clocks[0x8000 / 4], gpu[0x40000 / 4], crypto[1024], votes[1024], pll[1024];
static unsigned mode, maps, unmaps, fail_map, gpu_reads, wifi_reads;
static bool gpu_mode;
static bool backend_ready;
extern "C" bool sweet_gpu_ready(void) { return backend_ready; }
static void IOLog(const char *, ...) {}
static unsigned sync_calls, log_ready_after = 0, sync_notes[256], skip_mask;
static void IOSleep(unsigned) {}
extern "C" int mido_log_sync(uint32_t note)
{
    if (sync_calls < 256) sync_notes[sync_calls] = note;
    return sync_calls++ >= log_ready_after;
}
static bool PE_parse_boot_argn(const char *name, void *output, int size)
{
    if (!std::strcmp(name, "midogpuskip")) { assert(size == sizeof(skip_mask)); std::memcpy(output, &skip_mask, sizeof(skip_mask)); return true; }
    assert(!std::strcmp(name, gpu_mode ? "midogpustatus" : "midowificlocks"));
    assert(size == sizeof(mode));
    std::memcpy(output, &mode, sizeof(mode));
    return true;
}
static unsigned abort_after = 99, nofault_calls = 0;
static uint32_t smmu_window[0x4000];
static vm_offset_t ml_io_map_unmappable(vm_offset_t address, size_t bytes, unsigned flags)
{
    assert(flags == VM_WIMG_IO);
    maps++;
    uint32_t *target = nullptr;
    if (gpu_mode) {
        if (address == 0x01858000) { assert(bytes == sizeof(clocks)); target = clocks; }
        else if (address == 0x01c40000) { assert(bytes == 0x10000 && 0x10000 <= sizeof(smmu_window)); target = smmu_window; }
        else { assert(address == 0x01c00000 && bytes == 0x40000 && sizeof(gpu) >= 0x40000); target = gpu; }
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
        (address == (vm_offset_t)gpu && bytes == 0x40000) ||
        (address == (vm_offset_t)smmu_window && bytes == 0x10000));
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
extern "C" int mido_mmio_read32_nofault(uintptr_t address, uint32_t *value)
{
    if (nofault_calls++ >= abort_after) return 14;
    if (address >= (uintptr_t)smmu_window && address < (uintptr_t)smmu_window + sizeof(smmu_window)) { *value = 0; return 0; }
    gpu_reads++;
    *value = *(volatile uint32_t *)address;
    return 0;
}
#include "mido_gpu_status.h"
#include "mido_wcnss_clocks.h"
static void reset(bool selected = true)
{
    gpu_mode = selected; mode = 1;
    backend_ready = true;
    maps = unmaps = fail_map = gpu_reads = wifi_reads = 0; nofault_calls = 0; abort_after = 99; sync_calls = 0; log_ready_after = 0; skip_mask = 0;
    std::memset(clocks, 0, sizeof(clocks));
    clocks[0x1000 / 4] = 2;
    clocks[0x104c / 4] = clocks[0x101c / 4] = 0xa0222800;
    clocks[0x7028 / 4] = 3;
    for (unsigned offset : {0x1028U, 0x1030U, 0x1034U, 0x1040U, 0x1044U, 0x1020U}) clocks[offset / 4] = 1;
    gpu[0xc000 / 4] = 0x1234;
}
int main()
{
    reset(); backend_ready = false;
    assert(mido_gpu_status(1) == -6 && maps == 0 && gpu_reads == 0);
    reset(); mode = 0; assert(mido_gpu_status(1) == 0 && maps == 0);
    reset(); mode = 3; assert(mido_gpu_status(1) == -1 && maps == 0);
    /* mode 2 is the recoverable scan: it must not require a registered backend */
    reset(); mode = 2; backend_ready = false; gpu[0xc000 / 4] = 0x1234;
    assert(mido_gpu_status(1) == 1 && maps == 3 && unmaps == 3);
    reset(); assert(mido_gpu_status(0) == -1 && maps == 0);
    reset(); fail_map = 1; assert(mido_gpu_status(1) == -2 && unmaps == 0);
    reset(); fail_map = 2; assert(mido_gpu_status(1) == -4 && unmaps == 1);
    for (unsigned offset : {0x1000U, 0x1004U, 0x104cU, 0x101cU, 0x300cU, 0x7028U,
        0x1028U, 0x1030U, 0x1034U, 0x1040U, 0x1044U, 0x1020U}) {
        reset(); clocks[offset / 4] ^= 1;
        assert(mido_gpu_status(1) == -3 && maps == 1 && unmaps == 1 && nofault_calls == 0);
    }
    /* recoverable scan: all reads answer -> success, never aborts */
    reset(); gpu[0xc000 / 4] = 0x1234;
    assert(mido_gpu_status(1) == 1 && maps == 3 && unmaps == 3);
    /* the first external abort is counted, scan continues, mappings are always released */
    reset(); abort_after = 0;
    assert(mido_gpu_status(1) == -5 && maps == 3 && unmaps == 3);
    reset(); gpu[0xc000 / 4] = 0; assert(mido_gpu_status(1) == -5 && maps == 3 && unmaps == 3);
    reset(); gpu[0xc000 / 4] = 0xffffffffU; assert(mido_gpu_status(1) == -5 && maps == 3 && unmaps == 3);
    /* durable-log gating: no log means no scan and no register read */
    reset(); log_ready_after = 100000; assert(mido_gpu_status(1) == -7 && nofault_calls == 0 && unmaps == 2);
    /* log comes up late (after a few polls): scan still runs */
    reset(); log_ready_after = 5; gpu[0xc000 / 4] = 0x1234; assert(mido_gpu_status(1) == 1 && nofault_calls == 49);
    /* a full scan reads 49 registers in 9 groups, one durable flush before each group and each register */
    reset(); gpu[0xc000 / 4] = 0x1234;
    assert(mido_gpu_status(1) == 1 && nofault_calls == 49 && sync_calls >= 1 + 9 + 49);
    /* skip mask drops whole groups: skipping the secure group (6) removes exactly its 2 reads */
    reset(); skip_mask = 1U << 6; gpu[0xc000 / 4] = 0x1234;
    assert(mido_gpu_status(1) == 1 && nofault_calls == 47);
    reset(); skip_mask = (1U << 6) | (1U << 2); gpu[0xc000 / 4] = 0x1234;
    assert(mido_gpu_status(1) == 1 && nofault_calls == 38);
    /* skipping group 0 loses the version probe: result must not claim success */
    reset(); skip_mask = 1U; assert(mido_gpu_status(1) == -5);
    reset(false); mode = 0; assert(mido_wcnss_clocks() == 0 && maps == 0);
    reset(false); mode = 2; assert(mido_wcnss_clocks() == -1 && maps == 0);
    for (unsigned failed = 1; failed <= 3; failed++) {
        reset(false); fail_map = failed;
        assert(mido_wcnss_clocks() == -2 && maps == 3 && unmaps == 2 && wifi_reads == 0);
    }
    reset(false); assert(mido_wcnss_clocks() == 1 && wifi_reads == 8 && unmaps == 3);
    return 0;
}
