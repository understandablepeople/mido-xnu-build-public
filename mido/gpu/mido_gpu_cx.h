#ifndef MIDO_GPU_CX_H
#define MIDO_GPU_CX_H

#include "mido_rpm_smd.h"

#define MIDO_GPU_CX_RESOURCE 0x61706d73U
#define MIDO_GPU_CX_LEVEL_KEY 0x6c766c76U
#define MIDO_GPU_CX_INITIAL_LEVEL 192U

static inline int
mido_gpu_cx_vote(struct mido_rpm_io *rpm)
{
    const uint32_t kvp[6] = {MIDO_RPM_KEY_ENABLE, 4, 1,
        MIDO_GPU_CX_LEVEL_KEY, 4, MIDO_GPU_CX_INITIAL_LEVEL};
    return mido_rpm_request(rpm, MIDO_GPU_CX_RESOURCE, 2, kvp, 6, 0x475001);
}

#endif
