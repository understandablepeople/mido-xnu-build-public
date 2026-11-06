#ifndef MIDO_GPU_GX_POWER_H
#define MIDO_GPU_GX_POWER_H

#ifndef MIDO_GPU_GX_LOAD
#define MIDO_GPU_GX_LOAD(target) mido_gpu_bhs_load(target)
#endif
#ifndef MIDO_GPU_GX_STORE
#define MIDO_GPU_GX_STORE(target, value) mido_gpu_bhs_store(target, value)
#endif

static int
mido_gpu_gx_power(int cx_result, int bhs_result)
{
    unsigned mode = 0;
    PE_parse_boot_argn("midogpugx", &mode, sizeof(mode));
    if (mode == 0) {
        return 0;
    }
    if (mode != 1 || cx_result != 1 || bhs_result != 1) {
        IOLog("MIDO GPU GX: skipped mode=%u cx=%d bhs=%d\n", mode, cx_result, bhs_result);
        return -1;
    }
    vm_offset_t mapped = ml_io_map(0x01858000, 0x8000);
    vm_offset_t acc_mapping = ml_io_map(0x01944000, 0x1000);
    if (!mapped || !acc_mapping) {
        return -2;
    }
    volatile uint32_t *registers = (volatile uint32_t *)mapped;
    volatile uint32_t *acc = (volatile uint32_t *)(acc_mapping + 0x15c);
    volatile uint32_t *command = registers + (0x59000 - 0x58000) / 4;
    volatile uint32_t *gx = registers + (0x5901c - 0x58000) / 4;
    volatile uint32_t *clamp = registers + (0x5b00c - 0x58000) / 4;
    uint32_t cx = MIDO_GPU_GX_LOAD(registers + (0x5904c - 0x58000) / 4);
    uint32_t before = MIDO_GPU_GX_LOAD(gx);
    uint32_t control = MIDO_GPU_GX_LOAD(registers + (0x5f01c - 0x58000) / 4);
    uint32_t cmd = MIDO_GPU_GX_LOAD(command);
    uint32_t config = MIDO_GPU_GX_LOAD(registers + (0x59004 - 0x58000) / 4);
    if ((cx & 0x80000007U) != 0x80000000U ||
        (before & 0x80000007U) != 1U ||
        (control & 0xe0000217U) != 0x20000010U ||
        (cmd & 0x80000003U) != 0x80000000U || (config & 0x371fU) != 0) {
        IOLog("MIDO GPU GX: rejected cx=%08x gx=%08x ctl=%08x cmd=%08x cfg=%08x; no writes\n",
            cx, before, control, cmd, config);
        return -3;
    }
    static const uint32_t branches[] = {0x59020, 0x59028, 0x59030, 0x59040, 0x59044};
    for (unsigned index = 0; index < sizeof(branches) / sizeof(branches[0]); index++) {
        uint32_t value = MIDO_GPU_GX_LOAD(registers + (branches[index] - 0x58000) / 4);
        if ((value & 0x80000003U) != 0x80000000U) {
            IOLog("MIDO GPU GX: branch already active offset=%x value=%08x; no writes\n", branches[index], value);
            return -3;
        }
    }
    uint32_t acc_before = MIDO_GPU_GX_LOAD(acc);
    uint32_t acc_want = acc_before & ~1U;
    MIDO_GPU_GX_STORE(acc, acc_want);
    uint32_t actual = MIDO_GPU_GX_LOAD(acc);
    if (actual != acc_want) {
        IOLog("MIDO GPU GX: mem-acc mismatch want=%08x got=%08x; GX unrequested\n", acc_want, actual);
        return -4;
    }
    uint32_t clamp_before = MIDO_GPU_GX_LOAD(clamp);
    uint32_t clamp_want = clamp_before & ~1U;
    MIDO_GPU_GX_STORE(clamp, clamp_want);
    actual = MIDO_GPU_GX_LOAD(clamp);
    if (actual != clamp_want) {
        IOLog("MIDO GPU GX: clamp mismatch want=%08x got=%08x; GX unrequested\n", clamp_want, actual);
        return -5;
    }
    MIDO_GPU_GX_STORE(command, cmd | 2U);
    bool root_on = false;
    for (unsigned attempt = 0; attempt < 1000; attempt++) {
        actual = MIDO_GPU_GX_LOAD(command);
        if ((actual & 3U) != 2U) {
            IOLog("MIDO GPU GX: root control mismatch got=%08x; GX unrequested\n", actual);
            return -6;
        }
        if (!(actual & 0x80000000U)) {
            root_on = true;
            break;
        }
        IODelay(1);
    }
    if (!root_on) {
        IOLog("MIDO GPU GX: XO root timeout got=%08x; GX unrequested\n", actual);
        return -7;
    }
    uint32_t requested = before & ~1U;
    MIDO_GPU_GX_STORE(gx, requested);
    IODelay(1);
    for (unsigned attempt = 0; attempt < 1000; attempt++) {
        actual = MIDO_GPU_GX_LOAD(gx);
        if ((actual & 0x00fff007U) != (requested & 0x00fff007U)) {
            IOLog("MIDO GPU GX: control mismatch want=%08x got=%08x\n", requested, actual);
            return -8;
        }
        if (actual & 0x80000000U) {
            uint32_t status = MIDO_GPU_GX_LOAD(registers + (0x5f028 - 0x58000) / 4);
            IOLog("MIDO GPU GX: POWER_ON gx=%08x root=%08x mem-acc=%08x->%08x clamp=%08x->%08x supply=%08x polls=%u\n",
                actual, MIDO_GPU_GX_LOAD(command), acc_before, acc_want,
                clamp_before, clamp_want, status, attempt + 1);
            if (!(status & 2U)) {
                IOLog("MIDO GPU GX: BHS ack missing; no further requests\n");
                return -9;
            }
            IOLog("MIDO GPU GX: XO 19.2MHz only; no branch/GPU/SMMU/SCM writes or acceleration\n");
            return 1;
        }
        IODelay(1);
    }
    IOLog("MIDO GPU GX: power timeout gx=%08x; no rollback or further requests\n", actual);
    return -10;
}

#endif
