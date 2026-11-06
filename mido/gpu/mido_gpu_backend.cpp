#if !defined(MIDO_BACKEND_HOST_TEST)
#include <pexpert/arm64/board_config.h>
#endif
#if defined(MIDO) || defined(MIDO_BACKEND_HOST_TEST)
#include "mido_gpu_backend.h"
#include <stddef.h>
#include <sys/errno.h>

static struct mido_gpu_backend gpu_backend;
static unsigned gpu_state;
static uintptr_t fence_address;
static uint64_t fence_physical;
static unsigned fence_state;
static unsigned fence_delivered;

static const struct mido_gpu_backend *
gpu_active(void)
{
    return __atomic_load_n(&gpu_state, __ATOMIC_ACQUIRE) == 2 ? &gpu_backend : NULL;
}

static void
gpu_deliver_fence(void)
{
    if (__atomic_load_n(&gpu_state, __ATOMIC_ACQUIRE) != 2 ||
        __atomic_load_n(&fence_state, __ATOMIC_ACQUIRE) != 2) {
        return;
    }
    unsigned expected = 0;
    if (__atomic_compare_exchange_n(&fence_delivered, &expected, 1, false,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        gpu_backend.fence(fence_address, fence_physical);
    }
}

int
mido_gpu_register_backend(const struct mido_gpu_backend *backend)
{
    if (!backend || !backend->ready || !backend->map || !backend->unmap ||
        !backend->quad || !backend->submit || !backend->wait || !backend->info ||
        !backend->fence || !backend->ready()) {
        return EINVAL;
    }
    struct sweet_gpu_info info = {};
    backend->info(&info);
    if (info.chip_id != 0x05000600U || info.gmem_size != 139264U ||
        !info.gmem_base || !info.max_freq) {
        return EINVAL;
    }
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&gpu_state, &expected, 1, false,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        return EBUSY;
    }
    gpu_backend = *backend;
    __atomic_store_n(&gpu_state, 2, __ATOMIC_RELEASE);
    gpu_deliver_fence();
    return 0;
}

bool
sweet_gpu_ready(void)
{
    const struct mido_gpu_backend *backend = gpu_active();
    return backend && backend->ready();
}

uint64_t
sweet_gpu_vm_map(const uint64_t *pages, uint32_t count, bool readonly)
{
    const struct mido_gpu_backend *backend = gpu_active();
    return backend && backend->ready() && pages && count ?
        backend->map(pages, count, readonly) : 0;
}

void
sweet_gpu_vm_unmap(uint64_t address)
{
    const struct mido_gpu_backend *backend = gpu_active();
    if (backend && address) {
        backend->unmap(address);
    }
}

int
sweet_gpu_quad(const struct sweet_gpu_quad *quad)
{
    const struct mido_gpu_backend *backend = gpu_active();
    return !quad ? EINVAL : backend && backend->ready() ? backend->quad(quad) : ENXIO;
}

int
sweet_gpu_submit(const struct sweet_gpu_ib *buffers, uint32_t count, uint32_t *sequence)
{
    if (!buffers || !count || count > SWEET_GPU_MAX_IBS || !sequence) {
        return EINVAL;
    }
    *sequence = 0;
    const struct mido_gpu_backend *backend = gpu_active();
    return backend && backend->ready() ? backend->submit(buffers, count, sequence) : ENXIO;
}

int
sweet_gpu_wait(uint32_t sequence, uint32_t milliseconds)
{
    const struct mido_gpu_backend *backend = gpu_active();
    return backend && backend->ready() ? backend->wait(sequence, milliseconds) : ENXIO;
}

void
sweet_gpu_get_info(struct sweet_gpu_info *info)
{
    if (!info) {
        return;
    }
    *info = (struct sweet_gpu_info){};
    const struct mido_gpu_backend *backend = gpu_active();
    if (backend && backend->ready()) {
        backend->info(info);
    }
}

void
sweet_gpu_set_fence_page(uintptr_t address, uint64_t physical)
{
    if (!address || !physical) {
        return;
    }
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&fence_state, &expected, 1, false,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        return;
    }
    fence_address = address;
    fence_physical = physical;
    __atomic_store_n(&fence_state, 2, __ATOMIC_RELEASE);
    gpu_deliver_fence();
}
#endif
