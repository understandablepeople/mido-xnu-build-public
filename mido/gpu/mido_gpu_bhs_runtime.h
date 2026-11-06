#ifndef MIDO_GPU_BHS_RUNTIME_H
#define MIDO_GPU_BHS_RUNTIME_H

#include "mido_gpu_bhs.h"

#ifndef MIDO_GPU_BHS_LOAD
static uint32_t
mido_gpu_bhs_load(volatile uint32_t *target)
{
    uint32_t value = *target;
    __asm__ volatile("dmb oshld" ::: "memory");
    return value;
}
#define MIDO_GPU_BHS_LOAD(target) mido_gpu_bhs_load(target)
#endif

#ifndef MIDO_GPU_BHS_STORE
static void
mido_gpu_bhs_store(volatile uint32_t *target, uint32_t value)
{
    __asm__ volatile("dmb oshst" ::: "memory");
    *target = value;
    __asm__ volatile("dsb osh" ::: "memory");
}
#define MIDO_GPU_BHS_STORE(target, value) mido_gpu_bhs_store(target, value)
#endif

static int
mido_gpu_bhs_prepare(int cx_result)
{
    unsigned mode = 0;
    PE_parse_boot_argn("midogpubhs", &mode, sizeof(mode));
    if (mode == 0) {
        return 0;
    }
    if (mode != 1 || cx_result != 0) {
        IOLog("MIDO GPU BHS: skipped mode=%u cx-result=%d\n", mode, cx_result);
        return -1;
    }
    vm_offset_t mapped = ml_io_map(0x01858000, 0x8000);
    if (!mapped) {
        IOLog("MIDO GPU BHS: mapping failed; no writes\n");
        return -2;
    }
    volatile uint32_t *registers = (volatile uint32_t *)mapped;
    uint32_t gx = MIDO_GPU_BHS_LOAD(registers + (0x5901c - 0x58000) / 4);
    uint32_t control = MIDO_GPU_BHS_LOAD(registers + (0x5f01c - 0x58000) / 4);
    struct mido_gpu_bhs_step steps[MIDO_GPU_BHS_STEPS];
    if (!mido_gpu_bhs_plan(control, cx_result == 0,
        (gx & 0x80000003U) == 1U, steps, MIDO_GPU_BHS_STEPS)) {
        IOLog("MIDO GPU BHS: preflight rejected gx=%08x ctl=%08x; no writes\n", gx, control);
        return -3;
    }
    IOLog("MIDO GPU BHS: begin gx=%08x ctl=%08x steps=%u\n", gx, control, MIDO_GPU_BHS_STEPS);
    for (unsigned index = 0; index < MIDO_GPU_BHS_STEPS; index++) {
        volatile uint32_t *target = registers + (steps[index].offset - 0x58000) / 4;
        MIDO_GPU_BHS_STORE(target, steps[index].value);
        uint32_t actual = MIDO_GPU_BHS_LOAD(target);
        IOLog("MIDO GPU BHS: step=%u offset=%x want=%08x got=%08x\n",
            index, steps[index].offset, steps[index].value, actual);
        if (actual != steps[index].value) {
            IOLog("MIDO GPU BHS: stopped on readback mismatch; GX remains unrequested\n");
            return -4;
        }
    }
    IOLog("MIDO GPU BHS: prepared only; no GDSC/clock/mem-acc/GPU/SMMU/SCM writes\n");
    return 1;
}

#endif
