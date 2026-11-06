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
#include <kern/clock.h>
#include "mido_qup_v2.h"
#include "mido_rpm_smd.h"
#include "mido_input_state.h"
#include "mido_gpu_cx.h"
#include "mido_gpu_audit.h"
#include "mido_gpu_bhs_runtime.h"

extern "C" vm_offset_t ml_io_map(vm_offset_t, vm_size_t);
extern "C" void ml_io_unmap(vm_offset_t, vm_size_t);
extern "C" void mido_hid_key(int, int);
extern "C" void mido_hid_touch(int, int, int, int);
extern "C" int mido_hid_ready(void);
extern "C" void mido_display_power(int);

/* Framebuffer RequestPowerChange: -1 none, 0 off, 1 on; applied from the poll thread. */
static volatile int gDisplayRequest = -1;
void
mido_display_power(int on)
{
    __atomic_store_n(&gDisplayRequest, on ? 1 : 0, __ATOMIC_RELEASE);
}

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
    unsigned fLastPower = 8;
    uint64_t fNextBattery = 0, fLastPoll = 0;
    unsigned fSlowPolls = 0;
    vm_offset_t fWledRead = 0, fWledWrite = 0;
    vm_offset_t fWledControlRead = 0, fWledControlWrite = 0;
    unsigned fInvalidReports = 0;
    uint8_t fWledSaved[4] = {};
    bool fDisplayOn = true;
    bool fInitialized = false, fTouch = false, fPmic = false;
    bool fRunning = false, fTimerAdded = false;
    void initialize(void);
    bool touchSetup(void);
    bool pmicSetup(void);
    bool touchRails(void);
    bool wledSetup(void);
    bool wledRead(uint8_t, uint8_t *, bool = false);
    bool wledWrite(uint8_t, uint8_t, bool = false);
    void backlight(bool);
    bool pmicRead(unsigned, uint8_t, uint8_t *, unsigned = 1);
    void keys(void);
    void battery(void);
    void poll(void);
    void cleanup(void);
    static void fired(OSObject *, IOTimerEventSource *);
    static IOReturn halt(OSObject *, void *, void *, void *, void *);
};

OSDefineMetaClassAndStructors(MidoInput, IOService);

static void
rpm_notify(void *context)
{
    input_write((vm_offset_t)context, 8, 1);
}

static void
rpm_delay(void *, unsigned microseconds)
{
    IODelay(microseconds);
}

/* Linux sets these active-set votes via rpm-smd; lk2nd closes its channel before boot. */
bool
MidoInput::touchRails(void)
{
    unsigned enabled = 1;
    PE_parse_boot_argn("midorails", &enabled, sizeof(enabled));
    if (!enabled) {
        return true;
    }
    /* ponytail: ml_io_map entries are permanent (ml_io_unmap panics in vm_map_delete); mapped once, kept. */
    vm_offset_t smem = ml_io_map(0x86300000, 0x100000), ipc = ml_io_map(0x0b011000, 0x1000);
    vm_offset_t ext = ml_io_map(0x00060000, 0x20000);
    if (!smem || !ipc || !ext) {
        IOLog("MIDO RPM: SMEM/IPC mapping failed\n");
        return false;
    }
    struct mido_rpm_io rpm = {};
    rpm.smem = (volatile uint32_t *)smem;
    rpm.smem_size = 0x100000;
    rpm.ext = (volatile uint32_t *)ext;
    rpm.ext_phys = 0x60000;
    rpm.ext_size = 0x20000;
    rpm.context = (void *)ipc;
    rpm.notify = rpm_notify;
    rpm.delay = rpm_delay;
    static const struct { unsigned id, microvolt, milliamp; const char *name; } rails[2] = {
        {6, 1800000, 100, "L6 1.8V"}, {10, 2850000, 100, "L10 2.85V"},
    };
    bool ok = true;
    for (unsigned index = 0; index < 2; index++) {
        const uint32_t kvp[9] = {MIDO_RPM_KEY_ENABLE, 4, 1, MIDO_RPM_KEY_UV, 4, rails[index].microvolt,
            MIDO_RPM_KEY_MA, 4, rails[index].milliamp};
        int result = mido_rpm_request(&rpm, MIDO_RPM_LDOA, rails[index].id, kvp, 9, 0x4d49 + index);
        IOLog("MIDO RPM: %s vote result=%d ack=0x%x,0x%x\n", rails[index].name, result, rpm.ack[0], rpm.ack[1]);
        if (result == -3 && index == 0) {
            uint32_t size = 0;
            volatile uint32_t *table = mido_smem_item(&rpm, MIDO_SMEM_CHANNEL_TBL, &size);
            volatile uint32_t *info = rpm.smem + 52 + 4 * MIDO_SMEM_CHANNEL_TBL;
            IOLog("MIDO RPM: smem ver=%u heap=%u item13 alloc=%u off=0x%x size=0x%x ext=0x%x\n",
                rpm.smem[48], rpm.smem[49], info[0], info[1], info[2], info[3]);
            for (unsigned entry = 0; table && entry < 64 && entry < size / 32; entry++) {
                uint32_t cid = table[entry * 8 + 5], ctype = table[entry * 8 + 6];
                if (table[entry * 8] || ctype) {
                    volatile uint32_t *item = rpm.smem + 52 + 4 * (MIDO_SMEM_SMD_BASE + cid);
                    volatile uint32_t *fifo = rpm.smem + 52 + 4 * (MIDO_SMEM_SMD_FIFO + cid);
                    IOLog("MIDO RPM: ch%u %.8s cid=%u type=0x%x port(a=%u o=0x%x s=0x%x e=0x%x) fifo(a=%u s=0x%x e=0x%x)\n",
                        entry, (const char *)(table + entry * 8), cid, ctype, item[0], item[1], item[2], item[3],
                        fifo[0], fifo[2], fifo[3]);
                }
            }
        }
        ok = ok && result == 0;
    }
    unsigned gpu_cx = 0;
    PE_parse_boot_argn("midogpucx", &gpu_cx, sizeof(gpu_cx));
    if (gpu_cx == 1 && ok) {
        int result = mido_gpu_cx_vote(&rpm);
        IOLog("MIDO GPU CX: smpa2 level=%u result=%d ack=0x%x,0x%x\n",
            MIDO_GPU_CX_INITIAL_LEVEL, result, rpm.ack[0], rpm.ack[1]);
        IOLog("MIDO GPU CX: audit after vote; no GDSC/GFX-LDO/GPU/SMMU writes\n");
        mido_gpu_audit();
        int bhs_result = mido_gpu_bhs_prepare(result);
        if (bhs_result != 0) {
            IOLog("MIDO GPU BHS: result=%d; snapshot after preparation\n", bhs_result);
            mido_gpu_audit();
        }
    } else if (gpu_cx) {
        IOLog("MIDO GPU CX: skipped mode=%u touch-rails-ok=%u\n", gpu_cx, ok ? 1U : 0U);
    }
    IOSleep(50);
    return ok;
}

bool
MidoInput::touchSetup(void)
{
    touchRails();
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
    IOLog("MIDO INPUT: QUP status=0x%x errors=0x%x operational=0x%x pos=%u\n",
        fIo.last_status, fIo.last_errors, fIo.last_operational, fIo.last_position);
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

/*
 * PMI8950 SID3 WLED sink (peripheral 0xd9, PPID 0x3d9): per-string brightness
 * is 12 bit at sink+0x57/0x58 (+0x10 per string), applied by toggling sync at
 * sink+0x47 (leds-qpnp-wled.c). Writes go through the arbiter write channel.
 */
bool
MidoInput::wledSetup(void)
{
    if (!fPmicCore || fVersion < 0x20010000 || fVersion >= 0x50000000) {
        return false;
    }
    for (unsigned offset = 0x800; offset < 0x1000; offset += 4) {
        uint32_t entry = input_read(fPmicCore, offset);
        if (entry != 0 && ((entry >> 8) & 0xfff) == 0x3d9) {
            unsigned channel = 0x8000 * ((offset - 0x800) / 4);
            if (channel < 0x800000) {
                fWledRead = ml_io_map(0x02c00000 + channel, 0x1000);
                fWledWrite = ml_io_map(0x02400000 + channel, 0x1000);
            }
            break;
        }
    }
    IOLog("MIDO WLED: read=%s write=%s\n", fWledRead ? "mapped" : "absent", fWledWrite ? "mapped" : "absent");
    for (unsigned offset = 0x800; offset < 0x1000; offset += 4) {
        uint32_t entry = input_read(fPmicCore, offset);
        if (entry != 0 && ((entry >> 8) & 0xfff) == 0x3d8) {
            unsigned channel = 0x8000 * ((offset - 0x800) / 4);
            if (channel < 0x800000) {
                fWledControlRead = ml_io_map(0x02c00000 + channel, 0x1000);
                fWledControlWrite = ml_io_map(0x02400000 + channel, 0x1000);
            }
            break;
        }
    }
    IOLog("MIDO WLED: control PPID=0x3d8 read=%s write=%s\n",
        fWledControlRead ? "mapped" : "absent", fWledControlWrite ? "mapped" : "absent");
    return fWledRead && fWledWrite && fWledControlRead && fWledControlWrite;
}

bool
MidoInput::wledRead(uint8_t reg, uint8_t *value, bool control)
{
    vm_offset_t channel = control ? fWledControlRead : fWledRead;
    if (!channel || !value) {
        return false;
    }
    input_write(channel, 0, (1U << 27) | ((uint32_t)reg << 4));
    for (unsigned attempt = 0; attempt < 1000; attempt++) {
        uint32_t status = input_read(channel, 8);
        if (status & 1) {
            if (status & 0xe) {
                return false;
            }
            *value = (uint8_t)input_read(channel, 0x18);
            return true;
        }
        IODelay(1);
    }
    return false;
}

bool
MidoInput::wledWrite(uint8_t reg, uint8_t value, bool control)
{
    vm_offset_t channel = control ? fWledControlWrite : fWledWrite;
    if (!channel) {
        return false;
    }
    input_write(channel, 0x10, value);
    input_write(channel, 0, (uint32_t)reg << 4);
    for (unsigned attempt = 0; attempt < 1000; attempt++) {
        uint32_t status = input_read(channel, 8);
        if (status & 1) {
            return !(status & 0xe);
        }
        IODelay(1);
    }
    return false;
}

void
MidoInput::backlight(bool on)
{
    if (!fWledRead || !fWledWrite || on == fDisplayOn) {
        return;
    }
    static const uint8_t regs[4] = {0x57, 0x58, 0x67, 0x68};
    bool ok = true;
    if (!on) {
        for (unsigned index = 0; index < 4 && ok; index++) {
            ok = wledRead(regs[index], &fWledSaved[index]);
        }
        if (ok && !(fWledSaved[0] | (fWledSaved[1] & 0xf) | fWledSaved[2] | (fWledSaved[3] & 0xf))) {
            fWledSaved[1] = fWledSaved[3] = 0x08;
        }
        IOLog("MIDO WLED: off, saved level %02x%02x/%02x%02x ok=%d\n", fWledSaved[1], fWledSaved[0],
            fWledSaved[3], fWledSaved[2], ok);
    }
    for (unsigned index = 0; index < 4 && ok; index++) {
        ok = wledWrite(regs[index], on ? fWledSaved[index] : 0);
    }
    ok = ok && wledWrite(0x47, 0x0f);
    IODelay(1000);
    ok = ok && wledWrite(0x47, 0);
    uint8_t control = 0, verified = 0;
    ok = ok && wledRead(0x46, &control, true);
    if (ok) {
        uint8_t requested = on ? (control | 0x80) : (control & ~0x80);
        ok = wledWrite(0x46, requested, true) &&
            wledRead(0x46, &verified, true) && verified == requested;
    }
    IOLog("MIDO WLED: module enable readback=0x%x requested=%d ok=%d\n", verified, on, ok);
    if (ok) {
        fDisplayOn = on;
    }
    IOLog("MIDO WLED: %s ok=%d\n", on ? "on" : "off", ok);
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
    unsigned power = external | (charging << 1) | (full << 2);
    if (percent != fLastPercent || power != fLastPower) {
        IOLog("MIDO BATTERY: PMI8950 raw=%u percent=%u USB=%d charging=%d full=%d\n",
            soc[0], percent, external, charging, full);
        fLastPercent = percent;
        fLastPower = power;
    }
}

void
MidoInput::initialize(void)
{
    unsigned enabled = 1;
    PE_parse_boot_argn("midopmic", &enabled, sizeof(enabled));
    if (enabled) {
        fPmic = pmicSetup();
        if (fPmic) {
            wledSetup();
        }
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
    uint64_t now = mach_absolute_time(), elapsed = 0;
    if (fLastPoll) {
        absolutetime_to_nanoseconds(now - fLastPoll, &elapsed);
        if (elapsed > 1000000000ULL && fSlowPolls++ < 20) {
            IOLog("MIDO INPUT: scheduling gap %llu ms\n", elapsed / 1000000);
        }
    }
    fLastPoll = now;
    if (!mido_hid_ready()) {
        return;
    }
    if (!fInitialized) {
        initialize();
    }
    int request = __atomic_exchange_n(&gDisplayRequest, -1, __ATOMIC_ACQ_REL);
    if (request >= 0) {
        backlight(request != 0);
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
            if (!error && fInvalidReports++ < 12) {
                IOLog("MIDO INPUT: rejected report %u status=0x%x op=0x%x pos=%u\n",
                    fInvalidReports, fIo.last_status, fIo.last_operational, fIo.last_position);
                for (unsigned offset = 0; offset < sizeof(report); offset += 3) {
                    IOLog("MIDO INPUT: raw[%u]=%02x %02x %02x\n",
                        offset, report[offset], report[offset + 1], report[offset + 2]);
                }
            }
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
        IOLog("MIDO INPUT: QUP status=0x%x errors=0x%x operational=0x%x pos=%u\n",
            fIo.last_status, fIo.last_errors, fIo.last_operational, fIo.last_position);
    }
    fTicks++;
    if (!fNextBattery || now >= fNextBattery) {
        battery();
        uint64_t interval = 0;
        clock_interval_to_absolutetime_interval(5, NSEC_PER_SEC, &interval);
        fNextBattery = mach_absolute_time() + interval;
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
