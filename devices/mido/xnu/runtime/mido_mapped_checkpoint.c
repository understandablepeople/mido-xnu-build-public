#include <kern/debug.h>
#include <kern/startup.h>
#include <machine/machine_routines.h>
#include <pexpert/device_tree.h>
#include <pexpert/arm64/board_config.h>
#include "mapped_checkpoint.h"

#if !defined(ARM64_BOARD_CONFIG_MIDO) || !defined(MIDO_MAPPED_CHECKPOINT_DIAGNOSTIC) || USE_APPLEARMSMP
#error MIDO mapped checkpoint requires explicit single-CPU diagnostic configuration
#endif

static mido_fb_address map_framebuffer(mido_fb_u64 physical, mido_fb_u64 size)
{
    return ml_io_map(physical, size);
}

static void synchronize_framebuffer(void)
{
    __asm__ volatile("dsb sy" : : : "memory");
}

static void mido_mapped_checkpoint_startup(void)
{
    DTEntry node;
    const void *property;
    unsigned int size;
    struct mido_framebuffer_contract contract;
    const struct mido_framebuffer_io io = { map_framebuffer, synchronize_framebuffer };
    if (SecureDTLookupEntry(NULL, "/chosen", &node) != kSuccess ||
        SecureDTGetProperty(node, "mido,diagnostic-framebuffer", &property, &size) != kSuccess)
        return;
    if (size != sizeof(contract))
        panic("MIDO checkpoint: invalid framebuffer contract size");
    __builtin_memcpy(&contract, property, sizeof(contract));
    if (mido_mapped_checkpoint(&contract, &io) != 0)
        panic("MIDO checkpoint: framebuffer contract or mapping rejected");
}

STARTUP(EARLY_BOOT, STARTUP_RANK_MIDDLE, mido_mapped_checkpoint_startup);
