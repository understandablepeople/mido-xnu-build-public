#ifndef MIDO_GPU_STATUS_H
#define MIDO_GPU_STATUS_H

#include "mido_cbcr.h"
#include "mido_gpu_backend.h"

extern "C" int mido_mmio_read32_nofault(uintptr_t address, uint32_t *value);

static int
mido_gpu_status(int clocks_result)
{
    unsigned mode = 0;
    PE_parse_boot_argn("midogpustatus", &mode, sizeof(mode));
    if (mode == 0) {
        return 0;
    }
    /* mode 2 is read-only and abort-recovering and re-verifies GCC power/clocks below, so a failed SMMU/secure stage still gets scanned */
    if ((mode != 1 && mode != 2) || (mode == 1 && clocks_result != 1)) {
        IOLog("MIDO GPU STATUS: skipped mode=%u clocks=%d; GPU not accessed\n", mode, clocks_result);
        return -1;
    }
    if (mode != 2 && !sweet_gpu_ready()) {
        IOLog("MIDO GPU STATUS: no initialized backend; GPU not accessed\n");
        return -6;
    }
    vm_offset_t clock_mapping = ml_io_map_unmappable(0x01858000, 0x8000, VM_WIMG_IO);
    if (!clock_mapping) {
        return -2;
    }
    volatile uint32_t *clock = (volatile uint32_t *)clock_mapping;
    uint32_t config = MIDO_GPU_GX_LOAD(clock + 0x1004 / 4);
    bool ready = (MIDO_GPU_GX_LOAD(clock + 0x1000 / 4) & 0x80000003U) == 2U &&
        (config == 0 || config == 0x505U) &&
        (MIDO_GPU_GX_LOAD(clock + 0x104c / 4) & 0x80000001U) == 0x80000000U &&
        (MIDO_GPU_GX_LOAD(clock + 0x101c / 4) & 0x80000001U) == 0x80000000U &&
        !(MIDO_GPU_GX_LOAD(clock + 0x300c / 4) & 1U) &&
        (MIDO_GPU_GX_LOAD(clock + 0x7028 / 4) & 3U) == 3U;
    static const unsigned branches[] = {0x1028, 0x1030, 0x1034, 0x1040, 0x1044, 0x1020};
    for (unsigned offset : branches) {
        if (!mido_cbcr_branch_on(MIDO_GPU_GX_LOAD(clock + offset / 4))) {
            ready = false;
        }
    }
    ml_io_unmap(clock_mapping, 0x8000);
    if (!ready) {
        IOLog("MIDO GPU STATUS: power/clocks changed; GPU not accessed\n");
        return -3;
    }
    vm_offset_t mapping = ml_io_map_unmappable(0x01c00000, 0x40000, VM_WIMG_IO);
    if (!mapping) {
        return -4;
    }
    IOLog("MIDO GPU STATUS: begin recoverable scan (mode %u); reads only, no GPU writes\n", mode);
    /* byte offsets inside 0x01c00000 (GPU) and 0x01c40000 (SMMU); one abort is recovered per read */
    static const struct { const char *name; uint32_t base; uint32_t offset; } probes[] = {
        {"gpu+0x0000", 0, 0x0000}, {"gpu rbbm-alwayson-lo", 0, 0x1348}, {"gpu rbbm-int0", 0, 0x1384},
        {"gpu rbbm-status", 0, 0x13d4}, {"gpu rbbm-status3", 0, 0x14c0}, {"gpu rbbm-ahb-err", 0, 0x13d0},
        {"gpu vbif-version", 0, 0xc000}, {"gpu rbbm-clock-cntl", 0, 0x019c}, {"gpu rbbm-int0-mask", 0, 0x00e0},
        {"gpu secvid-trust-cntl", 0, 0x3d000}, {"gpu secvid-tsb-cntl", 0, 0x3e00c},
        {"gpu cp-cntl", 0, 0x20c4}, {"gpu cp-me-cntl", 0, 0x20c8}, {"gpu cp-addr-mode", 0, 0x2180},
        {"gpu cp-rb-base", 0, 0x2000}, {"gpu cp-rb-rptr", 0, 0x2018}, {"gpu cp-rb-wptr", 0, 0x201c},
        {"gpu cp-pfp-base", 0, 0x20d4}, {"gpu cp-pm4-base", 0, 0x20e0}, {"gpu cp-int-status", 0, 0x2c60},
        {"smmu sCR0", 1, 0x00}, {"smmu sCR1", 1, 0x04}, {"smmu sCR2", 1, 0x08}, {"smmu sACR", 1, 0x10},
        {"smmu idr0", 1, 0x20}, {"smmu idr1", 1, 0x24}, {"smmu idr2", 1, 0x28},
        {"smmu sGFSR", 1, 0x48}, {"smmu sGFSYNR0", 1, 0x50},
        {"smmu smr0", 1, 0x800}, {"smmu smr1", 1, 0x804}, {"smmu smr2", 1, 0x808}, {"smmu smr3", 1, 0x80c},
        {"smmu s2cr0", 1, 0xc00}, {"smmu s2cr1", 1, 0xc04}, {"smmu s2cr2", 1, 0xc08}, {"smmu s2cr3", 1, 0xc0c},
    };
    vm_offset_t smmu_mapping = ml_io_map_unmappable(0x01c40000, 0x1000, VM_WIMG_IO);
    uint32_t vbif = 0xffffffffU;
    int faults = 0, answered = 0;
    for (unsigned index = 0; index < sizeof(probes) / sizeof(probes[0]) && faults < 12; index++) {
        vm_offset_t base = probes[index].base ? smmu_mapping : mapping;
        if (base == 0 || (!probes[index].base && probes[index].offset >= 0x40000)) {
            continue;
        }
        uint32_t value = 0;
        int fault = mido_mmio_read32_nofault(base + probes[index].offset, &value);
        IOLog("MIDO GPU STATUS: %s +0x%x %s %08x\n", probes[index].name, probes[index].offset,
            fault ? "ABORT(recovered)" : "value", fault ? 0 : value);
        if (fault) {
            faults++;
        } else {
            answered++;
            if (probes[index].offset == 0xc000 && !probes[index].base) {
                vbif = value;
            }
        }
    }
    if (smmu_mapping) {
        ml_io_unmap(smmu_mapping, 0x1000);
    }
    ml_io_unmap(mapping, 0x40000);
    IOLog("MIDO GPU STATUS: scan done answered=%d aborted=%d\n", answered, faults);
    if (faults) {
        return -5;
    }
    return vbif != 0 && vbif != 0xffffffffU ? 1 : -5;
}

#endif
