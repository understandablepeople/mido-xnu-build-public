#ifndef MIDO_GPU_BHS_H
#define MIDO_GPU_BHS_H

#include <stddef.h>
#include <stdint.h>

#define MIDO_GPU_BHS_STEPS 12U

struct mido_gpu_bhs_step {
    uint32_t offset, value;
};

static inline int
mido_gpu_bhs_plan(uint32_t control, int cx_ack, int gx_off,
    struct mido_gpu_bhs_step *steps, size_t capacity)
{
    if (steps == NULL || capacity < MIDO_GPU_BHS_STEPS || !cx_ack || !gx_off) {
        return 0;
    }
    control = (control & ~(1U << 31)) | (1U << 29);
    steps[0] = (struct mido_gpu_bhs_step){0x5f01c, control};
    steps[1] = (struct mido_gpu_bhs_step){0x5f000, 0x203};
    steps[2] = (struct mido_gpu_bhs_step){0x5f004, 0x05008600};
    steps[3] = (struct mido_gpu_bhs_step){0x5f008, 0};
    steps[4] = (struct mido_gpu_bhs_step){0x5f00c, 0xc3fc};
    steps[5] = (struct mido_gpu_bhs_step){0x5f014, 0x004b1102};
    static const uint32_t clear_bits[6] = {0, 1U << 9, 1U << 30,
        1U << 1, 1U << 2, 1U};
    for (unsigned index = 0; index < 6; index++) {
        control = index == 0 ? control | (1U << 4) : control & ~clear_bits[index];
        steps[6 + index] = (struct mido_gpu_bhs_step){0x5f01c, control};
    }
    return 1;
}

#endif
