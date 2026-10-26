#ifndef MIDO_MAPPED_CHECKPOINT_H
#define MIDO_MAPPED_CHECKPOINT_H

typedef __UINT64_TYPE__ mido_fb_u64;
typedef __UINTPTR_TYPE__ mido_fb_address;

struct mido_framebuffer_contract {
    mido_fb_u64 version;
    mido_fb_u64 physical;
    mido_fb_u64 size;
    mido_fb_u64 width;
    mido_fb_u64 height;
    mido_fb_u64 stride;
    mido_fb_u64 depth;
};

struct mido_framebuffer_io {
    mido_fb_address (*map)(mido_fb_u64 physical, mido_fb_u64 size);
    void (*synchronize)(void);
};

int mido_mapped_checkpoint(const struct mido_framebuffer_contract *contract,
    const struct mido_framebuffer_io *io);

#endif
