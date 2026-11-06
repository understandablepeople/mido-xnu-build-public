#ifndef MIDO_GPU_SECURE_H
#define MIDO_GPU_SECURE_H

#include "mido_scm_probe.h"

static inline int
mido_gpu_secure_restore(int rate_result)
{
    unsigned mode = 0;
    PE_parse_boot_argn("midogpusecure", &mode, sizeof(mode));
    if (!mode) {
        return 0;
    }
    if (mode != 1 || rate_result != 1) {
        return -1;
    }
    uint64_t available = 0;
    int64_t transport = mido_scm_available(0x40000000U, 0x82000601U, &available);
    if (transport || available != 1) {
        return -2;
    }
    transport = mido_scm_available(0x40000000U, 0x02000c02U, &available);
    if (transport || available != 1) {
        return -3;
    }
    uint64_t secure = 0;
    transport = mido_scm_call(0x42000c02U, 2, 18, 0, 0, &secure);
    IOLog("MIDO GPU SECURE: restore device=18 context=0 transport=%lld secure=%llu; no SMMU resume or GPU access\n",
        transport, secure);
    if (transport) {
        return -4;
    }
    return secure ? -5 : 1;
}

#endif
