#ifndef MIDO_EARLY_IRQ_TIMER_H
#define MIDO_EARLY_IRQ_TIMER_H

typedef __UINT32_TYPE__ mido_u32;
typedef __UINT64_TYPE__ mido_u64;

enum mido_status {
    MIDO_OK = 0,
    MIDO_SPURIOUS = 1,
    MIDO_INVALID = -1,
    MIDO_NOT_READY = -2,
    MIDO_UNSUPPORTED = -3,
    MIDO_BUSY = -4,
    MIDO_BAD_ID = -5
};

enum mido_gic_region { MIDO_GIC_DIST = 0, MIDO_GIC_CPU = 1 };

struct mido_gic_io {
    void *context;
    mido_u32 (*read32)(void *context, mido_u32 region, mido_u32 offset);
    void (*write32)(void *context, mido_u32 region, mido_u32 offset, mido_u32 value);
    void (*synchronize)(void *context);
};

struct mido_gic {
    const struct mido_gic_io *io;
    mido_u32 interrupt_count;
    mido_u32 active_iar;
    mido_u32 active;
    mido_u32 ready;
};

struct mido_timer_io {
    void *context;
    mido_u64 (*read_counter)(void *context);
    void (*write_control)(void *context, mido_u32 value);
    void (*write_compare)(void *context, mido_u64 value);
    void (*synchronize)(void *context);
};

int mido_gic_attach(struct mido_gic *state, const struct mido_gic_io *io);
int mido_gic_take(struct mido_gic *state, mido_u32 *interrupt_id);
int mido_gic_finish(struct mido_gic *state);
int mido_gic_prepare_virtual_timer(struct mido_gic *state, mido_u32 interrupt_id);
int mido_gic_prepare_self_sgi(struct mido_gic *state);
int mido_gic_send_self_sgi(struct mido_gic *state);
int mido_gic_dispatch_timer_or_signal(struct mido_gic *state,
    void (*timer_service)(void *context), void (*signal_service)(void *context), void *context);
int mido_gic_dispatch_timer(struct mido_gic *state, mido_u32 interrupt_id,
    void (*service)(void *context), void *context);
int mido_timer_arm_delta(const struct mido_timer_io *io, mido_u64 delta);
int mido_timer_stop(const struct mido_timer_io *io);
void mido_arm64_timer_bind(struct mido_timer_io *io);

#endif
