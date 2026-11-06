#if !defined(MIDO_BACKEND_HOST_TEST)
#include <pexpert/arm64/board_config.h>
#endif
#if defined(MIDO) || defined(MIDO_BACKEND_HOST_TEST)
#include "mido_wlan_backend.h"
#include <stddef.h>
#include <sys/errno.h>
#if defined(MIDO_BACKEND_HOST_TEST)
extern "C" void mbuf_freem(mbuf_t);
#endif

static struct mido_wlan_backend wlan_backend;
static unsigned wlan_state;

static const struct mido_wlan_backend *
wlan_active(void)
{
    return __atomic_load_n(&wlan_state, __ATOMIC_ACQUIRE) == 2 ? &wlan_backend : NULL;
}

int
mido_wlan_register_backend(const struct mido_wlan_backend *backend)
{
    if (!backend || !backend->ready || !backend->output || !backend->a80211 ||
        !backend->ready()) {
        return EINVAL;
    }
    unsigned expected = 0;
    if (!__atomic_compare_exchange_n(&wlan_state, &expected, 1, false,
        __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) {
        return EBUSY;
    }
    wlan_backend = *backend;
    __atomic_store_n(&wlan_state, 2, __ATOMIC_RELEASE);
    return 0;
}

bool
mido_wlan_backend_ready(void)
{
    const struct mido_wlan_backend *backend = wlan_active();
    return backend && backend->ready();
}

void
mido_wlan_output(mbuf_t packet)
{
    if (!packet) {
        return;
    }
    const struct mido_wlan_backend *backend = wlan_active();
    if (backend && backend->ready()) {
        backend->output(packet);
    } else {
        mbuf_freem(packet);
    }
}

int
mido_wlan_a80211(int set, uint32_t type, int32_t *value, user_addr_t data, uint32_t *length)
{
    if ((set != 0 && set != 1) || !value || !length) {
        return EINVAL;
    }
    const struct mido_wlan_backend *backend = wlan_active();
    return backend && backend->ready() ?
        backend->a80211(set, type, value, data, length) : ENXIO;
}
#endif
