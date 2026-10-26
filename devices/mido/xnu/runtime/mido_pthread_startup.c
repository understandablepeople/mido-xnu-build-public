#include <kern/debug.h>
#include <kern/startup.h>
#include <kern/thread.h>
#include <mach/kmod.h>
#include <pexpert/arm64/board_config.h>

#if !defined(ARM64_BOARD_CONFIG_MIDO) || !defined(MIDO_PTHREAD_DIAGNOSTIC)
#error MIDO pthread registration requires an explicit diagnostic build
#endif

extern kern_return_t pthread_start(kmod_info_t *info, void *data);

thread_t mido_pthread_port_name_to_thread(mach_port_name_t name)
{
    return port_name_to_thread(name, PORT_INTRANS_THREAD_IN_CURRENT_TASK);
}

static void mido_pthread_startup(void)
{
    if (pthread_start(NULL, NULL) != KERN_SUCCESS)
        panic("MIDO diagnostic pthread: native registration failed");
}

STARTUP(THREAD_CALL, STARTUP_RANK_LAST, mido_pthread_startup);
