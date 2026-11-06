#ifndef MIDO_GPU_BACKEND_H
#define MIDO_GPU_BACKEND_H

#include "sweet_gpu.h"

__BEGIN_DECLS

struct mido_gpu_backend {
    bool (*ready)(void);
    uint64_t (*map)(const uint64_t *, uint32_t, bool);
    void (*unmap)(uint64_t);
    int (*quad)(const struct sweet_gpu_quad *);
    int (*submit)(const struct sweet_gpu_ib *, uint32_t, uint32_t *);
    int (*wait)(uint32_t, uint32_t);
    void (*info)(struct sweet_gpu_info *);
    void (*fence)(uintptr_t, uint64_t);
};

int mido_gpu_register_backend(const struct mido_gpu_backend *backend);

__END_DECLS

#endif
