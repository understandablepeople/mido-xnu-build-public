#include "mapped_checkpoint.h"

int mido_mapped_checkpoint(const struct mido_framebuffer_contract *contract,
    const struct mido_framebuffer_io *io)
{
    mido_fb_address base;
    unsigned int row;
    unsigned int word;
    if (!contract || !io || !io->map || !io->synchronize)
        return -1;
    if (contract->version != 1 || contract->physical != 0x90001000ULL ||
        contract->size != 6220800 || contract->width != 1080 ||
        contract->height != 1920 || contract->stride != 3240 || contract->depth != 24)
        return -1;
    base = io->map(contract->physical, contract->size);
    if (!base || (base & 3) || base > (mido_fb_address)-1 - contract->size)
        return -2;
    for (row = 608; row < 624; row++) {
        volatile __UINT32_TYPE__ *pixels =
            (volatile __UINT32_TYPE__ *)(base + row * 3240 + 180);
        for (word = 0; word < 48; word++)
            pixels[word] = 0xffffffffU;
    }
    io->synchronize();
    return 0;
}
