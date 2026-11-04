#include <pexpert/arm64/board_config.h>
#if defined(MIDO)
#include <device/device_types.h>
#include <IOKit/IOService.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOTimerEventSource.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/pwr_mgt/IOPMPowerSource.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSSymbol.h>
#include <libkern/c++/OSDictionary.h>
#include <pexpert/pexpert.h>
#include <machine/machine_routines.h>
#include "mido_qup_v2.h"
#include "mido_input_state.h"

extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern "C" void ml_io_unmap(vm_offset_t, vm_size_t);
extern "C" void mido_hid_key(int, int);
extern "C" void mido_hid_touch(int, int, int, int);
extern "C" int mido_hid_ready(void);

static uint32_t
input_read(vm_offset_t base, uint32_t offset)
{
    uint32_t value = *(volatile uint32_t *)(base + offset);
    __asm__ volatile("dmb oshld" ::: "memory");
    return value;
}

static void
input_write(vm_offset_t base, uint32_t offset, uint32_t value)
{
    __asm__ volatile("dmb oshst" ::: "memory");
    *(volatile uint32_t *)(base + offset) = value;
    __asm__ volatile("dsb osh" ::: "memory");
}

static uint32_t
qup_read(void *context, uint32_t offset)
{
    return input_read((vm_offset_t)context, offset);
}

static void
qup_write(void *context, uint32_t offset, uint32_t value)
{
    input_write((vm_offset_t)context, offset, value);
}

static void
qup_delay(void *, unsigned microseconds)
{
    IODelay(microseconds);
}

static void
input_touch(void *, unsigned slot, int down, unsigned x, unsigned y)
{
    mido_hid_touch((int)slot, down, (int)x, (int)y);
}

static void
input_home(void *, int down)
{
    mido_hid_key(3, down);
}

class MidoBattery : public IOPMPowerSource {
    OSDeclareDefaultStructors(MidoBattery);
public:
    using IOPMPowerSource::setBatteryInstalled;
    using IOPMPowerSource::setCurrentCapacity;
    using IOPMPowerSource::setMaxCapacity;
    using IOPMPowerSource::setExternalConnected;
    using IOPMPowerSource::setExternalChargeCapable;
    using IOPMPowerSource::setIsCharging;
    using IOPMPowerSource::setAtWarnLevel;
    using IOPMPowerSource::setAtCriticalLevel;
    using IOPMPowerSource::setTimeRemaining;
};

OSDefineMetaClassAndStructors(MidoBattery, IOPMPowerSource);

class MidoInput : public IOService {
    OSDeclareDefaultStructors(MidoInput);
public:
    bool start(IOService *) APPLE_KEXT_OVERRIDE;
    void stop(IOService *) APPLE_KEXT_OVERRIDE;
    void free(void) APPLE_KEXT_OVERRIDE;
private:
    IOWorkLoop *fLoop = NULL;
    IOTimerEventSource *fTimer = NULL;
    MidoBattery *fBattery = NULL;
    vm_offset_t fClock = 0, fQup = 0, fSda = 0, fScl = 0, fReset = 0;
    vm_offset_t fVolume = 0, fPmicCore = 0;
    vm_offset_t fObservers[5] = {};
    uint16_t fPpids[5] = {0x008, 0x240, 0x213, 0x210, 0x212};
    uint32_t fVersion = 0;
    struct mido_input_state fState = {};
    struct mido_input_sink fSink = {NULL, input_touch, input_home};
    struct mido_qup_io fIo = {};
    unsigned fTicks = 0, fFailures = 0, fProbeCount = 0, fPmicFailures = 0;
    unsigned fDebounce[3] = {}, fStable[3] = {};
    unsigned fLastPercent = 101;
    bool fInitialized = false, fTouch = false, fPmic = false;
    bool fRunning = false, fTimerAdded = false;
    void initialize(void);
    bool touchSetup(void);
    bool pmicSetup(void);
    bool pmicRead(unsigned, uint8_t, uint8_t *, unsigned = 1);
    void keys(void);
    void battery(void);
    void poll(void);
    void cleanup(void);
    static void fired(OSObject *, IOTimerEventSource *);
    static IOReturn halt(OSObject *, void *, void *, void *, void *);
};

OSDefineMetaClassAndStructors(MidoInput, IOService);

bool
MidoInput::touchSetup(void)
{
    fClock = ml_io_map(0x01800000, 0x46000);
    if (!fClock) {
        return false;
    }
    input_write(fClock, 0x45004, input_read(fClock, 0x45004) | (1U << 10));
    input_write(fClock, 0x4004, 1);
    input_write(fClock, 0x4000, input_read(fClock, 0x4000) | 1U);
    unsigned attempt = 0;
    for (; attempt < 2000 && (input_read(fClock, 0x4000) & 1U); attempt++) {
        IODelay(5);
    }
    if (attempt == 2000) {
        IOLog("MIDO INPUT: QUP3 clock update timed out\n");
        return false;
    }
    input_write(fClock, 0x4020, input_read(fClock, 0x4020) | 1U);
    for (attempt = 0; attempt < 2000; attempt++) {
        if ((input_read(fClock, 0x4020) & (1U << 31)) == 0 &&
            (input_read(fClock, 0x1008) & (1U << 31)) == 0) {
            break;
        }
        IODelay(5);
    }
    if (attempt == 2000) {
        IOLog("MIDO INPUT: BLSP1/QUP3 clock remains off\n");
        return false;
    }
    fSda = ml_io_map(0x0100a000, 0x1000);
    fScl = ml_io_map(0x0100b000, 0x1000);
    fReset = ml_io_map(0x01040000, 0x1000);
    if (!fSda || !fScl || !fReset) {
        return false;
    }
    input_write(fSda, 0, (input_read(fSda, 0) & ~0x3ffU) | (2U << 2));
    input_write(fScl, 0, (input_read(fScl, 0) & ~0x3ffU) | (2U << 2));
    input_write(fReset, 4, input_read(fReset, 4) | 2U);
    input_write(fReset, 0, (input_read(fReset, 0) & ~0x3ffU) | 0x2c3U);
    IOSleep(200);
    fQup = ml_io_map(0x078b7000, 0x1000);
    if (!fQup) {
        return false;
    }
    fIo.context = (void *)fQup;
    fIo.read = qup_read;
    fIo.write = qup_write;
    fIo.delay = qup_delay;
    uint8_t identity = 0, firmware = 0;
    int error = mido_qup_read(&fIo, 0x38, 0xa3, &identity, 1);
    IOLog("MIDO INPUT: QUP version=0x%x chip=0x%x read=%d\n",
        input_read(fQup, 0x30), identity, error);
    if (error || identity != 0x54) {
        IOLog("MIDO INPUT: FT5435 not verified; inherited L10/L6 supplies required\n");
        return false;
    }
    error = mido_qup_read(&fIo, 0x38, 0xa6, &firmware, 1);
    IOLog("MIDO INPUT: FT5435 verified, firmware=%u read=%d, v2 block polling\n", firmware, error);
    return true;
}

bool
MidoInput::pmicSetup(void)
{
    fPmicCore = ml_io_map(0x0200f000, 0x1000);
    if (!fPmicCore) {
        return false;
    }
    fVersion = input_read(fPmicCore, 0);
    if (fVersion < 0x20010000 || fVersion >= 0x60000000) {
        IOLog("MIDO INPUT: unsupported SPMI version 0x%x; no commands issued\n", fVersion);
        return false;
    }
    unsigned first = fVersion >= 0x50000000 ? 0x900 : 0x800;
    for (unsigned index = 0; index < 5; index++) {
        for (unsigned offset = first; offset < 0x1000; offset += 4) {
            uint32_t entry = input_read(fPmicCore, offset);
            if (entry != 0 && ((entry >> 8) & 0xfff) == fPpids[index]) {
                unsigned apid = (offset - first) / 4;
                unsigned channel = fVersion >= 0x50000000 ? 0x80 * apid : 0x8000 * apid;
                if (channel < 0x800000) {
                    fObservers[index] = ml_io_map(0x02c00000 + channel, 0x1000);
                }
                break;
            }
        }
        IOLog("MIDO INPUT: SPMI version=0x%x PPID=0x%x observer=%s\n",
            fVersion, fPpids[index], fObservers[index] ? "mapped" : "absent");
    }
    return true;
}

bool
MidoInput::pmicRead(unsigned index, uint8_t address, uint8_t *data, unsigned length)
{
    if (index >= 5 || !fObservers[index] || !data || length == 0 || length > 4) {
        return false;
    }
    vm_offset_t observer = fObservers[index];
    input_write(observer, 0, (1U << 27) | ((uint32_t)address << 4) | (length - 1));
    for (unsigned attempt = 0; attempt < 1000; attempt++) {
        uint32_t status = input_read(observer, 8);
        if (status & 1) {
            if (status & 0xe) {
                return false;
            }
            uint32_t word = input_read(observer, 0x18);
            for (unsigned byte = 0; byte < length; byte++) {
                data[byte] = (uint8_t)(word >> (8 * byte));
            }
            return true;
        }
        IODelay(1);
    }
    return false;
}

void
MidoInput::keys(void)
{
    unsigned values[3] = {};
    bool valid[3] = {};
    uint8_t pon = 0;
    if (fPmic && pmicRead(0, 0x10, &pon)) {
        values[0] = !!(pon & 1U);
        values[2] = !!(pon & 2U);
        valid[0] = valid[2] = true;
    }
    if (fVolume) {
        values[1] = !(input_read(fVolume, 4) & 1U);
        valid[1] = true;
    }
    for (unsigned key = 0; key < 3; key++) {
        if (!valid[key]) {
            fDebounce[key] = 0;
            if (fStable[key]) {
                mido_hid_key((int)key, 0);
                fStable[key] = 0;
            }
        } else if (values[key] == fStable[key]) {
            fDebounce[key] = 0;
        } else if (++fDebounce[key] >= 2) {
            fStable[key] = values[key];
            fDebounce[key] = 0;
            mido_hid_key((int)key, (int)values[key]);
        }
    }
}

void
MidoInput::battery(void)
{
    uint8_t soc[2] = {}, usb = 0, charger = 0, rt = 0, present = 0;
    bool valid = fPmic && pmicRead(1, 9, soc, 2) && soc[0] == soc[1] &&
        pmicRead(2, 0x10, &usb) && pmicRead(3, 0x0e, &charger) &&
        pmicRead(3, 0x10, &rt) && pmicRead(4, 0x10, &present);
    if (!valid) {
        if (++fPmicFailures == 1 || fPmicFailures % 10 == 0) {
            IOLog("MIDO BATTERY: hardware sample unavailable (%u), no percentage fabricated\n", fPmicFailures);
        }
        if (fBattery) {
            fBattery->setProperty("MidoHardwareSampleValid", false);
        }
        return;
    }
    fPmicFailures = 0;
    unsigned percent = soc[0] == 255 ? 100 : (soc[0] == 0 ? 0 :
        ((unsigned)(soc[0] - 1) * 98 + 126) / 253 + 1);
    bool external = (usb & 4) && !(usb & 2);
    bool full = external && (rt & 0x82);
    bool charging = external && !full && !(charger & 8) && (charger & 6);
    if (!fBattery) {
        fBattery = new MidoBattery;
        if (!fBattery || !fBattery->init() || !fBattery->attach(this) || !fBattery->start(this)) {
            IOLog("MIDO BATTERY: power-source registration failed\n");
            if (fBattery) {
                if (fBattery->getProvider()) {
                    fBattery->detach(this);
                }
                fBattery->release();
                fBattery = NULL;
            }
            return;
        }
        fBattery->setName("MidoBattery");
        fBattery->registerService();
    }
    fBattery->setBatteryInstalled(!(present & 0x40));
    fBattery->setCurrentCapacity(percent);
    fBattery->setMaxCapacity(100);
    fBattery->setExternalConnected(external);
    fBattery->setExternalChargeCapable(external);
    fBattery->setIsCharging(charging);
    fBattery->setAtWarnLevel(percent <= 15);
    fBattery->setAtCriticalLevel(false);
    fBattery->setTimeRemaining(-1);
    fBattery->setProperty("FullyCharged", full);
    fBattery->setProperty("MidoHardwareSampleValid", true);
    fBattery->setProperty("MidoRawSOC", (unsigned long long)soc[0], 32);
    fBattery->updateStatus();
    if (percent != fLastPercent) {
        IOLog("MIDO BATTERY: PMI8950 raw=%u percent=%u USB=%d charging=%d full=%d\n",
            soc[0], percent, external, charging, full);
        fLastPercent = percent;
    }
}

void
MidoInput::initialize(void)
{
    unsigned enabled = 1;
    PE_parse_boot_argn("midopmic", &enabled, sizeof(enabled));
    if (enabled) {
        fPmic = pmicSetup();
    }
    fVolume = ml_io_map(0x01055000, 0x1000);
    if (fVolume) {
        input_write(fVolume, 0, (input_read(fVolume, 0) & ~0x3ffU) | 3U);
    }
    enabled = 1;
    PE_parse_boot_argn("midotouch", &enabled, sizeof(enabled));
    if (enabled) {
        fTouch = touchSetup();
    }
    IOLog("MIDO INPUT: hardware setup touch=%d PMIC=%d volumeGPIO=%d\n",
        fTouch, fPmic, fVolume != 0);
    fInitialized = true;
}

void
MidoInput::poll(void)
{
    if (!mido_hid_ready()) {
        return;
    }
    if (!fInitialized) {
        initialize();
    }
    keys();
    if (fTouch) {
        uint8_t report[MIDO_FT_REPORT_BYTES];
        struct mido_ft_frame frame;
        int error = mido_qup_read(&fIo, 0x38, 0, report, sizeof(report));
        if (!error && mido_ft_decode(report, sizeof(report), &frame)) {
            fFailures = 0;
            mido_input_frame(&fState, &fSink, &frame);
        } else {
            if (++fFailures == 3) {
                mido_input_release(&fState, &fSink);
                IOLog("MIDO INPUT: report failed read=%d; contacts released\n", error);
            }
            if (fFailures >= 10) {
                fTouch = false;
                IOLog("MIDO INPUT: touch polling stopped after persistent errors\n");
            }
        }
    } else if (fQup && fProbeCount < 5 && fTicks % 250 == 0) {
        fProbeCount++;
        uint8_t identity = 0;
        int error = mido_qup_read(&fIo, 0x38, 0xa3, &identity, 1);
        fTouch = error == 0 && identity == 0x54;
        if (fTouch) {
            fFailures = 0;
        }
        IOLog("MIDO INPUT: bounded re-probe %u ID=0x%x read=%d\n", fProbeCount, identity, error);
    }
    if (fTicks++ % 1500 == 0) {
        battery();
    }
}

void
MidoInput::fired(OSObject *owner, IOTimerEventSource *timer)
{
    MidoInput *self = (MidoInput *)owner;
    if (self->fRunning) {
        self->poll();
        timer->setTimeoutMS(20);
    }
}

bool
MidoInput::start(IOService *provider)
{
    unsigned enabled = 1;
    PE_parse_boot_argn("midoinput", &enabled, sizeof(enabled));
    if (!enabled || !IOService::start(provider)) {
        return false;
    }
    fLoop = IOWorkLoop::workLoop();
    fTimer = IOTimerEventSource::timerEventSource(this, &MidoInput::fired);
    if (!fLoop || !fTimer || fLoop->addEventSource(fTimer) != kIOReturnSuccess) {
        cleanup();
        IOService::stop(provider);
        return false;
    }
    fTimerAdded = true;
    fRunning = true;
    fTimer->setTimeoutMS(10000);
    registerService();
    IOLog("MIDO INPUT: hardware poller scheduled, cpus unchanged\n");
    return true;
}

IOReturn
MidoInput::halt(OSObject *owner, void *, void *, void *, void *)
{
    MidoInput *self = (MidoInput *)owner;
    self->fRunning = false;
    if (self->fTimer) {
        self->fTimer->cancelTimeout();
    }
    mido_input_release(&self->fState, &self->fSink);
    for (unsigned key = 0; key < 3; key++) {
        if (self->fStable[key]) {
            mido_hid_key((int)key, 0);
            self->fStable[key] = 0;
        }
    }
    return kIOReturnSuccess;
}

void
MidoInput::cleanup(void)
{
    if (fLoop) {
        fLoop->runAction(&MidoInput::halt, this);
        if (fTimerAdded && fTimer) {
            fLoop->removeEventSource(fTimer);
            fTimerAdded = false;
        }
    }
    OSSafeReleaseNULL(fTimer);
    OSSafeReleaseNULL(fLoop);
    if (fBattery) {
        fBattery->stop(this);
        fBattery->detach(this);
        OSSafeReleaseNULL(fBattery);
    }
    vm_offset_t *maps[] = {&fClock, &fQup, &fSda, &fScl, &fReset, &fVolume, &fPmicCore};
    for (unsigned index = 0; index < sizeof(maps) / sizeof(maps[0]); index++) {
        if (*maps[index]) {
            ml_io_unmap(*maps[index], index == 0 ? 0x46000 : 0x1000);
            *maps[index] = 0;
        }
    }
    for (unsigned index = 0; index < 5; index++) {
        if (fObservers[index]) {
            ml_io_unmap(fObservers[index], 0x1000);
            fObservers[index] = 0;
        }
    }
}

void
MidoInput::stop(IOService *provider)
{
    cleanup();
    IOService::stop(provider);
}

void
MidoInput::free(void)
{
    cleanup();
    IOService::free();
}
#endif
