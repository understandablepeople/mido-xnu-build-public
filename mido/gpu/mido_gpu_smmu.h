#ifndef MIDO_GPU_SMMU_H
#define MIDO_GPU_SMMU_H

#include "mido_scm_probe.h"

static inline int64_t
mido_gpu_smmu_atomic(uint32_t function, uint32_t info, uint64_t physical,
    uint64_t value, uint64_t *returned)
{
    if (!returned ||
        (function == 0xc2000501U ? (info != 1 || value ||
            (physical != 0x01c40024 && physical != 0x01c46000)) :
            (function != 0xc2000502U || info != 2 || physical != 0x01c46000 || value > UINT32_MAX))) {
        return -101;
    }
    *returned = 0;
    struct mido_scm_registers state = {{function, info, physical, value, 0, 0, 0}};
    for (unsigned interrupted = 0; interrupted < 8; interrupted++) {
        MIDO_SCM_INVOKE(&state);
        int64_t result = (int32_t)state.values[0];
        if (result == 1) {
            state.values[0] = 1;
            continue;
        }
        if (!result) {
            *returned = state.values[1];
        }
        return result;
    }
    return -100;
}

static inline int
mido_gpu_smmu_resume(int secure_result)
{
    unsigned mode = 0;
    PE_parse_boot_argn("midogpusmmu", &mode, sizeof(mode));
    if (!mode) {
        return 0;
    }
    if (mode != 1 || secure_result != 1) {
        return -1;
    }
    uint64_t available = 0;
    static const uint32_t functions[] = {0x02000501U, 0x02000502U};
    for (unsigned index = 0; index < sizeof(functions) / sizeof(functions[0]); index++) {
        if (mido_scm_available(0x40000000U, functions[index], &available) || available != 1) {
            return -2;
        }
    }
    uint64_t id = 0;
    int64_t transport = mido_gpu_smmu_atomic(0xc2000501U, 1, 0x01c40024, 0, &id);
    if (transport || id > UINT32_MAX || !id || id == UINT32_MAX) {
        return -3;
    }
    unsigned page_shift = (id & (1U << 31)) ? 16 : 12;
    uint64_t size = 1ULL << (((id >> 28) & 7U) + page_shift + 2);
    unsigned banks = id & 0xffU, stage2 = (id >> 16) & 0xffU;
    if (page_shift != 12 || size != 0x10000 || !banks ||
        banks > (size >> (page_shift + 1)) || stage2 > banks) {
        return -4;
    }
    uint64_t physical = 0x01c40000ULL + (6ULL << page_shift);
    uint64_t control = 0;
    transport = mido_gpu_smmu_atomic(0xc2000501U, 1, physical, 0, &control);
    if (transport || control > UINT32_MAX || control == UINT32_MAX) {
        return -5;
    }
    uint64_t ignored = 0;
    transport = mido_gpu_smmu_atomic(0xc2000502U, 2, physical, control & ~4ULL, &ignored);
    if (transport) {
        return -6;
    }
    uint64_t after = 0;
    transport = mido_gpu_smmu_atomic(0xc2000501U, 1, physical, 0, &after);
    if (transport || after > UINT32_MAX || (after & 4U)) {
        return -7;
    }
    IOLog("MIDO GPU SMMU: static-CB secure resume id1=%08x control=%08x->%08x; no context/page-table/GPU access\n",
        (unsigned)id, (unsigned)control, (unsigned)after);
    return 1;
}

#endif
