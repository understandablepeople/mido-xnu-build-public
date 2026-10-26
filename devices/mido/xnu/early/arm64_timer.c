#include "irq_timer.h"

static mido_u64 read_counter(void *context)
{
    mido_u64 counter;
    (void)context;
    __asm__ volatile("isb\n\tmrs %0, cntvct_el0" : "=r"(counter) : : "memory");
    return counter;
}

static void write_control(void *context, mido_u32 value)
{
    (void)context;
    __asm__ volatile("msr cntv_ctl_el0, %0" : : "r"((mido_u64)value) : "memory");
}

static void write_compare(void *context, mido_u64 value)
{
    (void)context;
    __asm__ volatile("msr cntv_cval_el0, %0" : : "r"(value) : "memory");
}

static void synchronize(void *context)
{
    (void)context;
    __asm__ volatile("dsb sy\n\tisb" : : : "memory");
}

void mido_arm64_timer_bind(struct mido_timer_io *io)
{
    if (!io)
        return;
    io->context = 0;
    io->read_counter = read_counter;
    io->write_control = write_control;
    io->write_compare = write_compare;
    io->synchronize = synchronize;
}
