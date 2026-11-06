#ifndef MIDO_GPU_CLOCKS_H
#define MIDO_GPU_CLOCKS_H

#include "mido_cbcr.h"

static int
mido_gpu_clocks_run(volatile uint32_t *registers)
{
    static const unsigned offsets[] = {0x59028, 0x59030, 0x59034, 0x59040, 0x59044, 0x59020};
    uint32_t before[6];
    uint32_t root = MIDO_GPU_GX_LOAD(registers + 0x1000 / 4);
    uint32_t config = MIDO_GPU_GX_LOAD(registers + 0x1004 / 4);
    uint32_t cx = MIDO_GPU_GX_LOAD(registers + 0x104c / 4);
    uint32_t gx = MIDO_GPU_GX_LOAD(registers + 0x101c / 4);
    uint32_t clamp = MIDO_GPU_GX_LOAD(registers + 0x300c / 4);
    uint32_t supply = MIDO_GPU_GX_LOAD(registers + 0x7028 / 4);
    if ((root & 0x80000003U) != 2U || config != 0 ||
        (cx & 0x80000001U) != 0x80000000U ||
        (gx & 0x80000001U) != 0x80000000U || (clamp & 1U) ||
        (supply & 3U) != 3U) {
        IOLog("MIDO GPU CLOCKS: unsafe power/root state; no writes\n");
        return -3;
    }
    for (unsigned index = 0; index < 6; index++) {
        before[index] = MIDO_GPU_GX_LOAD(registers + (offsets[index] - 0x58000) / 4);
        if ((before[index] & 0xf0000003U) != 0x80000000U) {
            IOLog("MIDO GPU CLOCKS: branch=%05x unexpected=%08x; no writes\n",
                offsets[index], before[index]);
            return -4;
        }
    }
    for (unsigned index = 0; index < 6; index++) {
        volatile uint32_t *branch = registers + (offsets[index] - 0x58000) / 4;
        uint32_t requested = before[index] | 1U;
        MIDO_GPU_GX_STORE(branch, requested);
        bool ready = false;
        for (unsigned attempt = 0; attempt < 1000; attempt++) {
            uint32_t actual = MIDO_GPU_GX_LOAD(branch);
            if ((actual & 0x0fffffffU) != (requested & 0x0fffffffU)) {
                IOLog("MIDO GPU CLOCKS: branch=%05x mismatch=%08x; stopped\n", offsets[index], actual);
                return -5;
            }
            if (mido_cbcr_status_on(actual)) {
                IOLog("MIDO GPU CLOCKS: branch=%05x on=%08x polls=%u\n", offsets[index], actual, attempt + 1);
                ready = true;
                break;
            }
            IODelay(1);
        }
        if (!ready) {
            IOLog("MIDO GPU CLOCKS: branch=%05x timeout; no later requests\n", offsets[index]);
            return -6;
        }
    }
    IOLog("MIDO GPU CLOCKS: six branches on, XO only; GPU/SMMU/CP untouched, no acceleration\n");
    return 1;
}

static int
mido_gpu_clocks(int gx_result)
{
    unsigned mode = 0;
    PE_parse_boot_argn("midogpuclocks", &mode, sizeof(mode));
    if (mode == 0) {
        return 0;
    }
    if (mode != 1 || gx_result != 1) {
        IOLog("MIDO GPU CLOCKS: skipped mode=%u gx=%d\n", mode, gx_result);
        return -1;
    }
    vm_offset_t mapped = ml_io_map_unmappable(0x01858000, 0x8000, VM_WIMG_IO);
    if (!mapped) {
        return -2;
    }
    int result = mido_gpu_clocks_run((volatile uint32_t *)mapped);
    ml_io_unmap(mapped, 0x8000);
    return result;
}

#endif
