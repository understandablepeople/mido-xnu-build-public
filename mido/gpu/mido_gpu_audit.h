#ifndef MIDO_GPU_AUDIT_H
#define MIDO_GPU_AUDIT_H

#include "mido_gpu_power.h"

#ifndef MIDO_GPU_AUDIT_BARRIER
#define MIDO_GPU_AUDIT_BARRIER() __asm__ volatile("dmb oshld" ::: "memory")
#endif

extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);

static int
mido_gpu_audit_read(void *context, uint32_t offset, uint32_t *value)
{
    if (offset < MIDO_GPU_AUDIT_OFFSET ||
        offset > MIDO_GPU_AUDIT_OFFSET + MIDO_GPU_AUDIT_SIZE - sizeof(uint32_t) ||
        (offset & 3U)) {
        return 0;
    }
    uintptr_t base = (uintptr_t)context;
    *value = *(volatile uint32_t *)(base + offset - MIDO_GPU_AUDIT_OFFSET);
    MIDO_GPU_AUDIT_BARRIER();
    return 1;
}

static void
mido_gpu_audit(void)
{
    int mode = 0;
    if (!PE_parse_boot_argn("midogpu", &mode, sizeof(mode)) || mode == 0) {
        return;
    }
    if (mode != 1) {
        IOLog("MIDO GPU: unsupported midogpu=%d; no hardware access\n", mode);
        return;
    }
    vm_offset_t mapped = ml_io_map(MIDO_GPU_GCC_BASE + MIDO_GPU_AUDIT_OFFSET,
        MIDO_GPU_AUDIT_SIZE);
    if (mapped == 0) {
        IOLog("MIDO GPU: audit GCC mapping failed; no GPU access\n");
        return;
    }
    struct mido_gpu_reader reader = {(void *)mapped, mido_gpu_audit_read};
    struct mido_gpu_snapshot state = {0};
    if (!mido_gpu_snapshot_read(&reader, &state)) {
        IOLog("MIDO GPU: audit incomplete; no GPU access\n");
        return;
    }
    const uint32_t *values = state.values;
    IOLog("MIDO GPU: audit-only cmd=%08x cfg=%08x cx=%08x gx=%08x\n",
        values[MIDO_GPU_CMD], values[MIDO_GPU_CFG], values[MIDO_GPU_CX], values[MIDO_GPU_GX]);
    IOLog("MIDO GPU: core=%08x ahb=%08x mem=%08x timer=%08x aon=%08x\n",
        values[MIDO_GPU_CORE], values[MIDO_GPU_AHB], values[MIDO_GPU_MEM],
        values[MIDO_GPU_TIMER], values[MIDO_GPU_AON]);
    IOLog("MIDO GPU: clamp=%08x supply-ctl=%08x supply-status=%08x blockers=%02x\n",
        values[MIDO_GPU_CLAMP], values[MIDO_GPU_SUPPLY_CTL],
        values[MIDO_GPU_SUPPLY_STATUS], mido_gpu_snapshot_blockers(&state));
    IOLog("MIDO GPU: no writes, GPU/SMMU/fuses untouched; acceleration disabled\n");
}

#endif
