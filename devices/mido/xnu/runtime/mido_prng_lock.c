#include "mido_prng_bridge.h"
#include <kern/debug.h>
#include <kern/locks.h>
#include <kern/startup.h>

LCK_GRP_DECLARE(mido_prng_group, "mido-prng");
LCK_MTX_DECLARE(mido_prng_mutex, &mido_prng_group);

static int enter(void *context, int try_only)
{
    if (context != &mido_prng_mutex || startup_phase < STARTUP_SUB_LOCKS)
        panic("MIDO PRNG: mutex backend unavailable");
    if (try_only)
        return lck_mtx_try_lock(&mido_prng_mutex) ? 0 : 1;
    lck_mtx_lock(&mido_prng_mutex);
    return 0;
}

static void leave(void *context)
{
    if (context != &mido_prng_mutex)
        panic("MIDO PRNG: unexpected mutex context");
    lck_mtx_unlock(&mido_prng_mutex);
}

void mido_kernel_prng_install_native(void)
{
    static const struct mido_prng_services services = {
        .enter = enter,
        .leave = leave,
        .lock_context = &mido_prng_mutex,
    };
    if (startup_phase < STARTUP_SUB_LOCKS)
        panic("MIDO PRNG: installation before mutex startup");
    mido_kernel_prng_install(&services);
}
