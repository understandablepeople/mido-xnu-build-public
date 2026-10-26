#include <IOKit/IOPlatformExpert.h>
#include <libkern/c++/OSData.h>
#include <kern/debug.h>
#include <machine/machine_routines.h>
#include <pexpert/device_tree.h>
#include <pexpert/arm64/board_config.h>
#include "platform_contract.h"
#include "mido_pmic_clock.h"

#if !defined(ARM64_BOARD_CONFIG_MIDO) || !defined(MIDO_DIAGNOSTIC_PLATFORM) || USE_APPLEARMSMP
#error MIDO diagnostic platform requires explicit single-CPU diagnostic configuration
#endif

class MidoDiagnosticPlatform : public IOPlatformExpert {
    OSDeclareDefaultStructors(MidoDiagnosticPlatform);

public:
    IOService *probe(IOService *provider, SInt32 *score) APPLE_KEXT_OVERRIDE;
    bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
    long getGMTTimeOfDay(void) APPLE_KEXT_OVERRIDE;
    void setGMTTimeOfDay(long seconds) APPLE_KEXT_OVERRIDE;
    int haltRestart(unsigned int type) APPLE_KEXT_OVERRIDE;
    void sleepKernel(void) APPLE_KEXT_OVERRIDE;
};

OSDefineMetaClassAndStructors(MidoDiagnosticPlatform, IOPlatformExpert);

static bool diagnostic_contract_matches(IOService *provider)
{
    DTEntry chosen;
    const void *property;
    unsigned int size;
    uint64_t frequency;
    if (!provider)
        return false;
    OSData *compatible = OSDynamicCast(OSData, provider->getProperty("compatible"));
    if (!compatible || SecureDTLookupEntry(NULL, "/chosen", &chosen) != kSuccess ||
        SecureDTGetProperty(chosen, "mido,diagnostic-platform", &property, &size) != kSuccess)
        return false;
    __asm__ volatile("mrs %0, cntfrq_el0" : "=r"(frequency));
    return mido_platform_contract_matches(compatible->getBytesNoCopy(), compatible->getLength(),
        property, size, ml_get_cpu_count(), ml_get_boot_cpu_number(), frequency) != 0;
}

IOService *MidoDiagnosticPlatform::probe(IOService *provider, SInt32 *score)
{
    if (!diagnostic_contract_matches(provider))
        return NULL;
    return IOPlatformExpert::probe(provider, score);
}

bool MidoDiagnosticPlatform::start(IOService *provider)
{
    if (!diagnostic_contract_matches(provider))
        return false;
    mido_pmic_clock_initialize();
    if (!setProperty("MidoDiagnosticOnly", true) ||
        !setProperty("MidoRTCUnavailable", mido_pmic_clock_available() == 0))
        return false;
    if (!IOPlatformExpert::start(provider))
        return false;
    ml_set_max_cpus(1);
    return true;
}

long MidoDiagnosticPlatform::getGMTTimeOfDay(void)
{
    unsigned int seconds;
    if (!mido_pmic_clock_available())
        panic("MIDO diagnostic platform: RTC read is not implemented");
    int status = mido_pmic_clock_read(&seconds);
    if (status != 0)
        panic("MIDO diagnostic platform: read-only RTC failed (%d)", status);
    return seconds;
}

void MidoDiagnosticPlatform::setGMTTimeOfDay(long seconds __unused)
{
    panic("MIDO diagnostic platform: RTC write is not implemented");
}

int MidoDiagnosticPlatform::haltRestart(unsigned int type __unused)
{
    panic("MIDO diagnostic platform: halt/restart is not implemented");
}

void MidoDiagnosticPlatform::sleepKernel(void)
{
    panic("MIDO diagnostic platform: suspend is not implemented");
}
