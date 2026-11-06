#ifndef MIDO_GPU_RATE_H
#define MIDO_GPU_RATE_H

#include "mido_cbcr.h"

static int
mido_gpu_rate_run(volatile uint32_t *registers, volatile uint32_t *pll,
    volatile uint32_t *vote)
{
    uint32_t command = MIDO_GPU_GX_LOAD(registers + 0x1000 / 4);
    uint32_t config = MIDO_GPU_GX_LOAD(registers + 0x1004 / 4);
    uint32_t cx = MIDO_GPU_GX_LOAD(registers + 0x104c / 4);
    uint32_t gx = MIDO_GPU_GX_LOAD(registers + 0x101c / 4);
    uint32_t clamp = MIDO_GPU_GX_LOAD(registers + 0x300c / 4);
    uint32_t supply = MIDO_GPU_GX_LOAD(registers + 0x7028 / 4);
    uint32_t pll_state = MIDO_GPU_GX_LOAD(pll);
    uint32_t voted = MIDO_GPU_GX_LOAD(vote);
    if (command != 2 || config != 0 || !(pll_state & (1U << 30)) ||
        (cx & 0x80000001U) != 0x80000000U || (gx & 0x80000001U) != 0x80000000U ||
        (clamp & 1U) || (supply & 3U) != 3U) {
        return -3;
    }
    static const unsigned offsets[] = {0x1020, 0x1028, 0x1030, 0x1034, 0x1040, 0x1044};
    for (unsigned index = 0; index < sizeof(offsets) / sizeof(offsets[0]); index++) {
        uint32_t value = MIDO_GPU_GX_LOAD(registers + offsets[index] / 4);
        if ((value & 3U) != 1 || !mido_cbcr_status_on(value)) {
            return -3;
        }
        if (offsets[index] == 0x1020 && (value & 0x6000U) != 0x6000U) {
            return -3;
        }
    }
    MIDO_GPU_GX_STORE(vote, voted | 1U);
    if (MIDO_GPU_GX_LOAD(vote) != (voted | 1U)) {
        return -4;
    }
    MIDO_GPU_GX_STORE(registers + 0x1004 / 4, 0x505U);
    if (MIDO_GPU_GX_LOAD(registers + 0x1004 / 4) != 0x505U) {
        return -5;
    }
    MIDO_GPU_GX_STORE(registers + 0x1000 / 4, command | 1U);
    for (unsigned attempt = 0; attempt < 1000; attempt++) {
        uint32_t actual = MIDO_GPU_GX_LOAD(registers + 0x1000 / 4);
        if (!(actual & 1U)) {
            if (actual != 2 || MIDO_GPU_GX_LOAD(registers + 0x1004 / 4) != 0x505U ||
                !(MIDO_GPU_GX_LOAD(pll) & (1U << 30))) {
                return -6;
            }
            IOLog("MIDO GPU RATE: GPLL0/2 HID=5 nominal=133330000 polls=%u; no GPU/SMMU access\n", attempt + 1);
            return 1;
        }
        IODelay(1);
    }
    return -7;
}

static int
mido_gpu_rate(int clocks_result)
{
    unsigned mode = 0;
    PE_parse_boot_argn("midogpurate", &mode, sizeof(mode));
    if (mode == 0) {
        return 0;
    }
    if (mode != 1 || clocks_result != 1) {
        return -1;
    }
    vm_offset_t registers = ml_io_map_unmappable(0x01858000, 0x8000, VM_WIMG_IO);
    vm_offset_t pll = ml_io_map_unmappable(0x01821000, 0x1000, VM_WIMG_IO);
    vm_offset_t vote = ml_io_map_unmappable(0x01845000, 0x1000, VM_WIMG_IO);
    int result = -2;
    if (registers && pll && vote) {
        result = mido_gpu_rate_run((volatile uint32_t *)registers,
            (volatile uint32_t *)pll, (volatile uint32_t *)vote);
    }
    if (vote) ml_io_unmap(vote, 0x1000);
    if (pll) ml_io_unmap(pll, 0x1000);
    if (registers) ml_io_unmap(registers, 0x8000);
    return result;
}

#endif
