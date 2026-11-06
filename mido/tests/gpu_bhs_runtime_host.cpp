#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstring>

typedef uintptr_t vm_offset_t;
typedef size_t vm_size_t;
static uint32_t registers[0x8000 / 4];
static unsigned mode, mappings, writes;
static int failed_mapping, mismatch;

static bool
PE_parse_boot_argn(const char *name, void *output, int size)
{
    assert(!std::strcmp(name, "midogpubhs") && size == sizeof(mode));
    std::memcpy(output, &mode, sizeof(mode));
    return true;
}

static vm_offset_t
ml_io_map(vm_offset_t address, vm_size_t size)
{
    assert(address == 0x01858000 && size == sizeof(registers));
    mappings++;
    return failed_mapping ? 0 : (vm_offset_t)registers;
}

static void IOLog(const char *, ...) {}

static uint32_t
load(volatile uint32_t *target)
{
    return *target ^ ((mismatch >= 0 && writes == (unsigned)mismatch + 1) ? 1U : 0U);
}

static void
store(volatile uint32_t *target, uint32_t value)
{
    size_t offset = (target - registers) * 4 + 0x58000;
    assert(offset >= 0x5f000 && offset <= 0x5f01c && offset != 0x5f010 && offset != 0x5f018);
    *target = value;
    writes++;
}

#define MIDO_GPU_BHS_LOAD(target) load(target)
#define MIDO_GPU_BHS_STORE(target, value) store(target, value)
#include "mido_gpu_bhs_runtime.h"

static void
reset(unsigned selected_mode)
{
    std::memset(registers, 0, sizeof(registers));
    registers[(0x5901c - 0x58000) / 4] = 0x08225801;
    registers[(0x5f01c - 0x58000) / 4] = 0x80000038;
    mode = selected_mode;
    mappings = writes = 0;
    failed_mapping = 0;
    mismatch = -1;
}

int
main()
{
    reset(0);
    assert(mido_gpu_bhs_prepare(0) == 0 && mappings == 0 && writes == 0);
    reset(2);
    assert(mido_gpu_bhs_prepare(0) == -1 && mappings == 0 && writes == 0);
    reset(1);
    assert(mido_gpu_bhs_prepare(-9) == -1 && mappings == 0 && writes == 0);
    failed_mapping = 1;
    assert(mido_gpu_bhs_prepare(0) == -2 && writes == 0);
    reset(1);
    registers[(0x5901c - 0x58000) / 4] |= 1U << 31;
    assert(mido_gpu_bhs_prepare(0) == -3 && writes == 0);
    reset(1);
    assert(mido_gpu_bhs_prepare(0) == 1 && writes == 12);
    assert(registers[(0x5f01c - 0x58000) / 4] == 0x20000038);
    for (int index = 0; index < 12; index++) {
        reset(1);
        mismatch = index;
        assert(mido_gpu_bhs_prepare(0) == -4 && writes == (unsigned)index + 1);
    }
    return 0;
}
