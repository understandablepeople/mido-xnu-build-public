#include <kern/debug.h>
#include <machine/machine_routines.h>
#include <pexpert/device_tree.h>
#include <pexpert/arm64/board_config.h>
#include "pmic_rtc.h"
#include "mido_pmic_clock.h"

#if !defined(ARM64_BOARD_CONFIG_MIDO) || !defined(MIDO_DIAGNOSTIC_PLATFORM) || USE_APPLEARMSMP
#error MIDO PMIC clock requires explicit single-CPU diagnostic configuration
#endif

static vm_offset_t core_base;
static vm_offset_t observer_base;
static mido_rtc_u32 mapped_observer_offset;
static struct mido_pmic_rtc rtc;
static struct mido_pmic_rtc_io rtc_io;

int mido_pmic_clock_available(void)
{
    static const uint32_t expected[] = {
        0x0200f000, 0x1000, 0x02c00000, 0x800000, 0, 0, 0x6000, 0,
        0x20010000, 19200000
    };
    DTEntry chosen;
    const void *property;
    const uint32_t *words;
    unsigned int size;
    unsigned int index;
    uint64_t frequency;
    if (SecureDTLookupEntry(NULL, "/chosen", &chosen) != kSuccess ||
        SecureDTGetProperty(chosen, "mido,pm8953-rtc-readonly", &property, &size) != kSuccess)
        return 0;
    if (size != sizeof(expected) || ml_get_cpu_count() != 1 || ml_get_boot_cpu_number() != 0)
        panic("MIDO RTC: invalid explicit read-only contract");
    words = property;
    for (index = 0; index < sizeof(expected) / sizeof(expected[0]); index++) {
        if (words[index] != expected[index])
            panic("MIDO RTC: unreviewed platform contract");
    }
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frequency));
    if (frequency != 19200000)
        panic("MIDO RTC: unexpected counter frequency");
    return 1;
}

static int read_register(void *context __unused, mido_rtc_u32 region,
    mido_rtc_u32 offset, mido_rtc_u32 *value)
{
    vm_offset_t base;
    if (offset & 3u)
        return -1;
    if (region == MIDO_RTC_CORE && offset < 0x1000u)
        base = core_base;
    else if (region == MIDO_RTC_OBSERVER &&
        (offset == mapped_observer_offset + 8u || offset == mapped_observer_offset + 0x18u)) {
        base = observer_base;
        offset -= mapped_observer_offset;
    }
    else
        return -1;
    *value = *(volatile mido_rtc_u32 *)(base + offset);
    return 0;
}

static int read_command(void *context __unused, mido_rtc_u32 offset, mido_rtc_u32 command)
{
    if (offset != mapped_observer_offset ||
        !(command == ((1u << 27) | (5u << 4)) ||
          command == ((1u << 27) | (0x46u << 4)) ||
          command == ((1u << 27) | (0x48u << 4)) ||
          command == ((1u << 27) | (0x48u << 4) | 3u)))
        return -1;
    *(volatile mido_rtc_u32 *)observer_base = command;
    return 0;
}

static mido_rtc_u64 read_counter(void *context __unused)
{
    mido_rtc_u64 value;
    __asm__ volatile("mrs %0, cntvct_el0" : "=r"(value));
    return value;
}

static void synchronize(void *context __unused)
{
    __asm__ volatile("dsb sy\n\tisb" : : : "memory");
}

void mido_pmic_clock_initialize(void)
{
    int status;
    if (!mido_pmic_clock_available())
        return;
    if (core_base || observer_base)
        panic("MIDO RTC: duplicate initialization");
    core_base = ml_io_map(0x0200f000, 0x1000);
    if (!core_base)
        panic("MIDO RTC: mapping failed");
    rtc_io.context = NULL;
    rtc_io.read32 = read_register;
    rtc_io.read_command = read_command;
    rtc_io.counter = read_counter;
    rtc_io.synchronize = synchronize;
    status = mido_pmic_rtc_discover(&rtc_io, &mapped_observer_offset);
    if (status != MIDO_RTC_OK)
        panic("MIDO RTC: read-only channel discovery failed (%d)", status);
    observer_base = ml_io_map(0x02c00000 + mapped_observer_offset, 0x1000);
    if (!observer_base)
        panic("MIDO RTC: observer channel mapping failed");
}

int mido_pmic_clock_read(unsigned int *seconds)
{
    boolean_t interrupts;
    int status;
    if (!seconds || !mido_pmic_clock_available() || !core_base || !observer_base)
        return MIDO_RTC_UNSUPPORTED;
    interrupts = ml_set_interrupts_enabled(FALSE);
    status = rtc.ready ? MIDO_RTC_OK : mido_pmic_rtc_attach(&rtc, &rtc_io);
    if (status == MIDO_RTC_OK)
        status = mido_pmic_rtc_seconds(&rtc, seconds);
    ml_set_interrupts_enabled(interrupts);
    return status;
}
