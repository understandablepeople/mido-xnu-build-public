#ifndef MIDO_GPU_STATUS_H
#define MIDO_GPU_STATUS_H

static int
mido_gpu_status(int clocks_result)
{
    unsigned mode = 0;
    PE_parse_boot_argn("midogpustatus", &mode, sizeof(mode));
    if (mode == 0) {
        return 0;
    }
    if (mode != 1 || clocks_result != 1) {
        IOLog("MIDO GPU STATUS: skipped mode=%u clocks=%d; GPU not accessed\n", mode, clocks_result);
        return -1;
    }
    vm_offset_t clock_mapping = ml_io_map_unmappable(0x01858000, 0x8000, VM_WIMG_IO);
    if (!clock_mapping) {
        return -2;
    }
    volatile uint32_t *clock = (volatile uint32_t *)clock_mapping;
    bool ready = (MIDO_GPU_GX_LOAD(clock + 0x1000 / 4) & 0x80000003U) == 2U &&
        MIDO_GPU_GX_LOAD(clock + 0x1004 / 4) == 0 &&
        (MIDO_GPU_GX_LOAD(clock + 0x104c / 4) & 0x80000001U) == 0x80000000U &&
        (MIDO_GPU_GX_LOAD(clock + 0x101c / 4) & 0x80000001U) == 0x80000000U &&
        !(MIDO_GPU_GX_LOAD(clock + 0x300c / 4) & 1U) &&
        (MIDO_GPU_GX_LOAD(clock + 0x7028 / 4) & 3U) == 3U;
    static const unsigned branches[] = {0x1028, 0x1030, 0x1034, 0x1040, 0x1044, 0x1020};
    for (unsigned offset : branches) {
        if ((MIDO_GPU_GX_LOAD(clock + offset / 4) & 0x80000003U) != 1U) {
            ready = false;
        }
    }
    ml_io_unmap(clock_mapping, 0x8000);
    if (!ready) {
        IOLog("MIDO GPU STATUS: power/clocks changed; GPU not accessed\n");
        return -3;
    }
    vm_offset_t mapping = ml_io_map_unmappable(0x01c00000, 0x10000, VM_WIMG_IO);
    if (!mapping) {
        return -4;
    }
    volatile uint32_t *gpu = (volatile uint32_t *)mapping;
    IOLog("MIDO GPU STATUS: begin four read-only A5xx registers; no GPU writes\n");
    uint32_t status = MIDO_GPU_GX_LOAD(gpu + 0x4f5);
    uint32_t status3 = MIDO_GPU_GX_LOAD(gpu + 0x530);
    uint32_t ahb_error = MIDO_GPU_GX_LOAD(gpu + 0x4f4);
    uint32_t vbif = MIDO_GPU_GX_LOAD(gpu + 0x3000);
    ml_io_unmap(mapping, 0x10000);
    IOLog("MIDO GPU STATUS: rbbm=%08x status3=%08x ahb-error=%08x vbif-version=%08x; no CP/SMMU/firmware or acceleration\n",
        status, status3, ahb_error, vbif);
    return vbif != 0 && vbif != 0xffffffffU ? 1 : -5;
}

#endif
