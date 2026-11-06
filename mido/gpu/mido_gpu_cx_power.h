#ifndef MIDO_GPU_CX_POWER_H
#define MIDO_GPU_CX_POWER_H

#ifndef MIDO_GPU_CX_LOAD
#define MIDO_GPU_CX_LOAD(target) mido_gpu_bhs_load(target)
#endif
#ifndef MIDO_GPU_CX_STORE
#define MIDO_GPU_CX_STORE(target, value) mido_gpu_bhs_store(target, value)
#endif

static int
mido_gpu_cx_power(int cx_result, int bhs_result)
{
    unsigned mode = 0;
    PE_parse_boot_argn("midogpucxpower", &mode, sizeof(mode));
    if (mode == 0) {
        return 0;
    }
    if (mode != 1 || cx_result != 0 || bhs_result != 1) {
        IOLog("MIDO GPU CX POWER: skipped mode=%u cx=%d bhs=%d\n", mode, cx_result, bhs_result);
        return -1;
    }
    vm_offset_t mapped = ml_io_map(0x01858000, 0x8000);
    if (!mapped) {
        return -2;
    }
    volatile uint32_t *registers = (volatile uint32_t *)mapped;
    volatile uint32_t *cx = registers + (0x5904c - 0x58000) / 4;
    uint32_t gx = MIDO_GPU_CX_LOAD(registers + (0x5901c - 0x58000) / 4);
    uint32_t before = MIDO_GPU_CX_LOAD(cx);
    uint32_t control = MIDO_GPU_CX_LOAD(registers + (0x5f01c - 0x58000) / 4);
    if ((gx & 0x80000003U) != 1U || (before & 0x80000003U) != 1U ||
        (control & 0xe0000217U) != 0x20000010U) {
        IOLog("MIDO GPU CX POWER: rejected cx=%08x gx=%08x ctl=%08x; no writes\n", before, gx, control);
        return -3;
    }
    uint32_t requested = before & ~1U;
    MIDO_GPU_CX_STORE(cx, requested);
    IODelay(1);
    for (unsigned attempt = 0; attempt < 1000; attempt++) {
        uint32_t actual = MIDO_GPU_CX_LOAD(cx);
        if ((actual & 0x7fffffffU) != requested) {
            IOLog("MIDO GPU CX POWER: readback mismatch before=%08x want=%08x got=%08x\n", before, requested, actual);
            return -4;
        }
        if (actual & 0x80000000U) {
            IOLog("MIDO GPU CX POWER: on cx=%08x polls=%u; GX/clocks/GPU untouched\n", actual, attempt + 1);
            return 1;
        }
        IODelay(1);
    }
    IOLog("MIDO GPU CX POWER: timeout cx=%08x; no GX/clock/GPU requests or rollback\n", MIDO_GPU_CX_LOAD(cx));
    return -5;
}

#endif
