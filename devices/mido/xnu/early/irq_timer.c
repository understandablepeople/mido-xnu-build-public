#include "irq_timer.h"

#define GICD_CTLR 0x000u
#define GICD_TYPER 0x004u
#define GICC_CTLR 0x000u
#define GICC_IAR 0x00cu
#define GICC_EOIR 0x010u
#define GICC_SPLIT_EOI ((1u << 9) | (1u << 10))

static int cpu_mode(const struct mido_gic_io *io)
{
    mido_u32 control = io->read32(io->context, MIDO_GIC_CPU, GICC_CTLR);
    if (control & GICC_SPLIT_EOI)
        return MIDO_UNSUPPORTED;
    if (!(control & 3u))
        return MIDO_NOT_READY;
    return MIDO_OK;
}

int mido_gic_attach(struct mido_gic *state, const struct mido_gic_io *io)
{
    mido_u32 count;
    int status;
    if (!state || !io || !io->read32 || !io->write32 || !io->synchronize)
        return MIDO_INVALID;
    if (state->active)
        return MIDO_BUSY;
    state->ready = 0;
    state->io = 0;
    state->interrupt_count = 0;
    state->active_iar = 0;
    if (!(io->read32(io->context, MIDO_GIC_DIST, GICD_CTLR) & 3u))
        return MIDO_NOT_READY;
    status = cpu_mode(io);
    if (status != MIDO_OK)
        return status;
    count = ((io->read32(io->context, MIDO_GIC_DIST, GICD_TYPER) & 31u) + 1u) * 32u;
    state->interrupt_count = count > 1020u ? 1020u : count;
    state->io = io;
    state->ready = 1;
    return MIDO_OK;
}

int mido_gic_take(struct mido_gic *state, mido_u32 *interrupt_id)
{
    mido_u32 token;
    mido_u32 identifier;
    int status;
    if (!state || !interrupt_id)
        return MIDO_INVALID;
    if (!state->ready || !state->io)
        return MIDO_NOT_READY;
    if (state->active)
        return MIDO_BUSY;
    status = cpu_mode(state->io);
    if (status != MIDO_OK)
        return status;
    token = state->io->read32(state->io->context, MIDO_GIC_CPU, GICC_IAR);
    state->io->synchronize(state->io->context);
    identifier = token & 1023u;
    if (identifier >= 1020u)
        return MIDO_SPURIOUS;
    state->active_iar = token;
    state->active = 1;
    if (identifier >= state->interrupt_count)
        return MIDO_BAD_ID;
    *interrupt_id = identifier;
    return MIDO_OK;
}

int mido_gic_finish(struct mido_gic *state)
{
    int status;
    if (!state || !state->ready || !state->io || !state->active)
        return MIDO_INVALID;
    if ((state->active_iar & 1023u) >= state->interrupt_count)
        return MIDO_BAD_ID;
    status = cpu_mode(state->io);
    if (status != MIDO_OK)
        return status;
    state->io->synchronize(state->io->context);
    state->io->write32(state->io->context, MIDO_GIC_CPU, GICC_EOIR, state->active_iar);
    state->io->synchronize(state->io->context);
    state->active = 0;
    state->active_iar = 0;
    return MIDO_OK;
}

static int timer_valid(const struct mido_timer_io *io)
{
    return io && io->read_counter && io->write_control && io->write_compare && io->synchronize;
}

int mido_gic_prepare_virtual_timer(struct mido_gic *state, mido_u32 interrupt_id)
{
    const struct mido_gic_io *io;
    mido_u32 priority;
    mido_u32 priority_offset;
    mido_u32 priority_shift;
    int status;
    if (!state || interrupt_id < 16u || interrupt_id >= 32u)
        return MIDO_INVALID;
    if (!state->ready || !state->io)
        return MIDO_NOT_READY;
    if (state->active)
        return MIDO_BUSY;
    io = state->io;
    status = cpu_mode(io);
    if (status != MIDO_OK)
        return status;
    if (!(io->read32(io->context, MIDO_GIC_DIST, 0x080u) & (1u << interrupt_id)))
        return MIDO_UNSUPPORTED;
    if (io->read32(io->context, MIDO_GIC_DIST, 0xc04u) & (2u << ((interrupt_id - 16u) * 2u)))
        return MIDO_UNSUPPORTED;
    priority_offset = 0x400u + (interrupt_id & ~3u);
    priority_shift = (interrupt_id & 3u) * 8u;
    priority = io->read32(io->context, MIDO_GIC_DIST, priority_offset);
    io->write32(io->context, MIDO_GIC_DIST, priority_offset,
        (priority & ~(0xffu << priority_shift)) | (0xa0u << priority_shift));
    io->write32(io->context, MIDO_GIC_CPU, 0x004u, 0xffu);
    io->write32(io->context, MIDO_GIC_DIST, 0x100u, 1u << interrupt_id);
    io->synchronize(io->context);
    if (!(io->read32(io->context, MIDO_GIC_DIST, 0x100u) & (1u << interrupt_id)))
        return MIDO_NOT_READY;
    return MIDO_OK;
}

int mido_gic_prepare_self_sgi(struct mido_gic *state)
{
    const struct mido_gic_io *io;
    mido_u32 priority;
    int status;
    if (!state)
        return MIDO_INVALID;
    if (!state->ready || !state->io)
        return MIDO_NOT_READY;
    if (state->active)
        return MIDO_BUSY;
    io = state->io;
    status = cpu_mode(io);
    if (status != MIDO_OK)
        return status;
    if (!(io->read32(io->context, MIDO_GIC_DIST, 0x080u) & 1u))
        return MIDO_UNSUPPORTED;
    priority = io->read32(io->context, MIDO_GIC_DIST, 0x400u);
    io->write32(io->context, MIDO_GIC_DIST, 0x400u, (priority & ~0xffu) | 0x80u);
    io->write32(io->context, MIDO_GIC_DIST, 0x100u, 1u);
    io->synchronize(io->context);
    if (!(io->read32(io->context, MIDO_GIC_DIST, 0x100u) & 1u))
        return MIDO_NOT_READY;
    return MIDO_OK;
}

int mido_gic_send_self_sgi(struct mido_gic *state)
{
    const struct mido_gic_io *io;
    int status;
    if (!state)
        return MIDO_INVALID;
    if (!state->ready || !state->io)
        return MIDO_NOT_READY;
    if (state->active)
        return MIDO_BUSY;
    io = state->io;
    status = cpu_mode(io);
    if (status != MIDO_OK)
        return status;
    if (!(io->read32(io->context, MIDO_GIC_DIST, 0x080u) & 1u) ||
        !(io->read32(io->context, MIDO_GIC_DIST, 0x100u) & 1u))
        return MIDO_NOT_READY;
    io->synchronize(io->context);
    io->write32(io->context, MIDO_GIC_DIST, 0xf00u, 2u << 24);
    io->synchronize(io->context);
    return MIDO_OK;
}

int mido_gic_dispatch_timer_or_signal(struct mido_gic *state,
    void (*timer_service)(void *context), void (*signal_service)(void *context), void *context)
{
    mido_u32 acknowledged;
    int status;
    if (!timer_service || !signal_service)
        return MIDO_INVALID;
    status = mido_gic_take(state, &acknowledged);
    if (status != MIDO_OK)
        return status;
    if (acknowledged == 20u)
        timer_service(context);
    else if (acknowledged == 0u) {
        status = mido_gic_finish(state);
        if (status != MIDO_OK)
            return status;
        signal_service(context);
        return MIDO_OK;
    } else
        return MIDO_UNSUPPORTED;
    return mido_gic_finish(state);
}

int mido_gic_dispatch_timer(struct mido_gic *state, mido_u32 interrupt_id,
    void (*service)(void *context), void *context)
{
    mido_u32 acknowledged;
    int status;
    if (!service || interrupt_id < 16u || interrupt_id >= 32u)
        return MIDO_INVALID;
    status = mido_gic_take(state, &acknowledged);
    if (status != MIDO_OK)
        return status;
    if (acknowledged != interrupt_id)
        return MIDO_UNSUPPORTED;
    service(context);
    return mido_gic_finish(state);
}

int mido_timer_arm_delta(const struct mido_timer_io *io, mido_u64 delta)
{
    mido_u64 now;
    mido_u64 deadline;
    if (!timer_valid(io) || !delta || delta >= ((mido_u64)1 << 63))
        return MIDO_INVALID;
    now = io->read_counter(io->context);
    if (delta > ~(mido_u64)0 - now)
        return MIDO_INVALID;
    deadline = now + delta;
    io->write_control(io->context, 2u);
    io->synchronize(io->context);
    io->write_compare(io->context, deadline);
    io->synchronize(io->context);
    io->write_control(io->context, 1u);
    io->synchronize(io->context);
    return MIDO_OK;
}

int mido_timer_stop(const struct mido_timer_io *io)
{
    if (!timer_valid(io))
        return MIDO_INVALID;
    io->write_control(io->context, 2u);
    io->synchronize(io->context);
    return MIDO_OK;
}
