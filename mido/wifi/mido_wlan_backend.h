#ifndef MIDO_WLAN_BACKEND_H
#define MIDO_WLAN_BACKEND_H

#include <stdint.h>
#include <stdbool.h>
#include <sys/cdefs.h>
#if defined(MIDO_BACKEND_HOST_TEST)
typedef struct __mbuf *mbuf_t;
typedef uint64_t user_addr_t;
#else
#include <sys/kpi_mbuf.h>
#include <sys/types.h>
#endif

__BEGIN_DECLS

struct mido_wlan_backend {
    bool (*ready)(void);
    void (*output)(mbuf_t);
    int (*a80211)(int, uint32_t, int32_t *, user_addr_t, uint32_t *);
};

int mido_wlan_register_backend(const struct mido_wlan_backend *backend);
bool mido_wlan_backend_ready(void);
void mido_wlan_output(mbuf_t packet);
int mido_wlan_a80211(int set, uint32_t type, int32_t *value, user_addr_t data, uint32_t *length);
bool mido_wlan_iokit_attach(const uint8_t *mac);
void mido_wlan_iokit_input(mbuf_t packet);
void mido_wlan_iokit_link(bool up);
void mido_wlan_iokit_event(uint32_t code, const void *data, uint32_t length);

__END_DECLS

#endif
