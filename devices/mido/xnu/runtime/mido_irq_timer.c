#include <kern/debug.h>
#include <kern/startup.h>
#include <kern/thread.h>
#include <arm/rtclock.h>
#include <arm/cpu_data.h>
#include <arm/cpu_data_internal.h>
#include <arm/machine_cpu.h>
#include <machine/machine_routines.h>
#include <pexpert/device_tree.h>
#include <pexpert/arm64/board_config.h>
#include "irq_timer.h"

#if !defined(ARM64_BOARD_CONFIG_MIDO) || !defined(MIDO_IRQ_TIMER_DIAGNOSTIC) || USE_APPLEARMSMP
#error MIDO IRQ timer requires explicit single-CPU diagnostic configuration
#endif

static vm_offset_t distributor_base;
static vm_offset_t interface_base;
static struct mido_gic controller;
static struct mido_gic_io controller_io;
static struct mido_timer_io timer_io;
static boolean_t self_signal_enabled;

static mido_u32 read_register(void *context __unused, mido_u32 region, mido_u32 offset)
{
    vm_offset_t base = region == MIDO_GIC_DIST ? distributor_base : interface_base;
    if (offset >= 4096 || (offset & 3u))
        panic("MIDO IRQ: invalid register offset");
    return *(volatile mido_u32 *)(base + offset);
}

static void write_register(void *context __unused, mido_u32 region, mido_u32 offset, mido_u32 value)
{
    vm_offset_t base = region == MIDO_GIC_DIST ? distributor_base : interface_base;
    if (offset >= 4096 || (offset & 3u))
        panic("MIDO IRQ: invalid register offset");
    *(volatile mido_u32 *)(base + offset) = value;
}

static void synchronize(void *context __unused)
{
    __asm__ volatile("dsb sy\n\tisb" : : : "memory");
}

static void service_timer(void *context __unused)
{
    if (mido_timer_stop(&timer_io) != MIDO_OK)
        panic("MIDO IRQ: timer masking failed");
    rtclock_intr(0);
}

static void mido_irq_set_decrementer(uint32_t ticks)
{
    __asm__ volatile("msr cntv_tval_el0, %0" : : "r"((uint64_t)ticks) : "memory");
    timer_io.write_control(timer_io.context, 1);
    timer_io.synchronize(timer_io.context);
}

static void service_signal(void *context __unused)
{
    cpu_signal_handler();
}

static void mido_irq_handler(void *target __unused, void *refcon __unused,
    void *nub __unused, int source __unused)
{
    int status = self_signal_enabled ?
        mido_gic_dispatch_timer_or_signal(&controller, service_timer, service_signal, NULL) :
        mido_gic_dispatch_timer(&controller, 20, service_timer, NULL);
    if (status != MIDO_OK && status != MIDO_SPURIOUS)
        panic("MIDO IRQ: unhandled interrupt or controller failure %d", status);
}

static void mido_irq_timer_startup(void)
{
    DTEntry node;
    const void *property;
    unsigned int size;
    const uint64_t *registers;
    uint32_t interrupt_id;
    uint64_t frequency;
    if (ml_get_interrupts_enabled())
        panic("MIDO IRQ: initialization requires masked interrupts");
    if (SecureDTLookupEntry(NULL, "/arm-io/interrupt-controller", &node) != kSuccess ||
        SecureDTGetProperty(node, "reg", &property, &size) != kSuccess || size != 4 * sizeof(uint64_t))
        panic("MIDO IRQ: missing GICv2 aperture");
    registers = property;
    if (registers[0] != 0 || registers[1] != 4096 || registers[2] != 8192 || registers[3] != 4096)
        panic("MIDO IRQ: unreviewed GICv2 aperture");
    if (SecureDTGetProperty(node, "mido,virtual-timer-intid", &property, &size) != kSuccess || size != sizeof(uint32_t))
        panic("MIDO IRQ: missing timer routing contract");
    interrupt_id = *(const uint32_t *)property;
    if (interrupt_id != 20)
        panic("MIDO IRQ: unreviewed virtual timer interrupt");
    if (SecureDTGetProperty(node, "mido,boot-self-sgi-intid", &property, &size) == kSuccess) {
        if (size != sizeof(uint32_t) || *(const uint32_t *)property != 0 ||
            ml_get_cpu_count() != 1 || ml_get_boot_cpu_number() != 0)
            panic("MIDO IRQ: unreviewed boot self-SGI contract");
        self_signal_enabled = TRUE;
    }
    if (SecureDTLookupEntry(NULL, "/arm-io", &node) != kSuccess ||
        SecureDTGetProperty(node, "ranges", &property, &size) != kSuccess || size != 3 * sizeof(uint64_t))
        panic("MIDO IRQ: missing GICv2 translation");
    registers = property;
    if (registers[0] != 0 || registers[1] != 0x0b000000 || registers[2] != 0x3000)
        panic("MIDO IRQ: unreviewed GICv2 translation");
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frequency));
    if (frequency != 19200000)
        panic("MIDO IRQ: unexpected architectural timer frequency");
    distributor_base = ml_io_map(0x0b000000, 4096);
    interface_base = ml_io_map(0x0b002000, 4096);
    if (!distributor_base || !interface_base)
        panic("MIDO IRQ: mapping failed");
    controller_io.context = NULL;
    controller_io.read32 = read_register;
    controller_io.write32 = write_register;
    controller_io.synchronize = synchronize;
    mido_arm64_timer_bind(&timer_io);
    if (mido_timer_stop(&timer_io) != MIDO_OK ||
        mido_gic_attach(&controller, &controller_io) != MIDO_OK ||
        mido_gic_prepare_virtual_timer(&controller, interrupt_id) != MIDO_OK)
        panic("MIDO IRQ: GICv2 timer route is unavailable");
    ml_install_interrupt_handler(NULL, 0, NULL, mido_irq_handler, NULL);
    if (getCpuDatap()->cpu_set_decrementer_func != NULL)
        panic("MIDO IRQ: decrementer backend already installed");
    getCpuDatap()->cpu_set_decrementer_func = mido_irq_set_decrementer;
    timer_io.write_control(timer_io.context, 1);
    timer_io.synchronize(timer_io.context);
    if (self_signal_enabled && (mido_gic_prepare_self_sgi(&controller) != MIDO_OK ||
        mido_gic_send_self_sgi(&controller) != MIDO_OK))
        panic("MIDO IRQ: boot self-SGI route is unavailable");
}

STARTUP(EARLY_BOOT, STARTUP_RANK_LAST, mido_irq_timer_startup);
