#include <pexpert/arm64/board_config.h>
/*
 * The Pixel 1's QCA6174 Wi-Fi as an IOEthernetController, so that iOS's
 * configd names it (en0 through IONetworkStack) and IPConfiguration runs
 * DHCP on it. The radio, firmware, association and WPA2 live in
 * bsd/dev/sailfish_wlan.c; this class only bridges frames and link state.
 *
 * The IORegistry is held busy from start() until the interface exists:
 * configd builds the first network configuration (a DHCP service per
 * interface, kept in preferences.plist) when IOKit goes quiet.
 *
 * For iOS's Wi-Fi stack (wifid, Settings) the interface looks like
 * Apple's: classes named IO80211Controller / IO80211Interface (configd
 * and wifid classify by class name), IEEE 802.11 media (IO80211.framework
 * lists interfaces by SIOCGIFMEDIA type), IO80211InterfaceRole
 * Infrastructure, and SIOCGA80211/SIOCSA80211 answered by
 * mido_wlan_a80211(). No IO80211 user client: IO80211.framework falls
 * back to the ioctls when IOServiceOpen fails.
 */
#if defined(MIDO)
#include <IOKit/IOLib.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/network/IOEthernetController.h>
#include <IOKit/network/IOEthernetInterface.h>
#include <IOKit/network/IONetworkMedium.h>
#include <IOKit/network/IOOutputQueue.h>      /* kIOReturnOutputSuccess */
#include <IOKit/network/IONetworkTypesPrivate.h>        /* kIONetworkInterfaceSubTypeWiFi */
#include <pexpert/pexpert.h>
#include <sys/proc.h>
#include "mido_wlan_backend.h"
extern "C" {
#include <sys/kern_event.h>
}

/* Apple80211 events (IO80211.framework listens on KEV_VENDOR_APPLE / class 6 / subclass 1). */
#define KEV_IEEE80211_CLASS     6
#define KEV_APPLE80211_SUBCLASS 1

/* bsd/dev/sailfish_wlan.c */
extern "C" void mido_wlan_output(mbuf_t m);
extern "C" int mido_wlan_a80211(int set, uint32_t type, int32_t *val, user_addr_t data, uint32_t *len);

#define WLAN_SPEED      54000000ULL     /* legacy 11g rates for now */
#define SIOCSA80211     0x802869c8UL    /* _IOW('i', 200, struct apple80211req) */
#define SIOCGA80211     0xc02869c9UL    /* _IOWR('i', 201, struct apple80211req) */

struct apple80211req {
	char     req_if_name[16];
	int32_t  req_type;
	int32_t  req_val;
	uint32_t req_len;
	uint64_t req_data;      /* user pointer (64-bit callers) */
};

class IO80211Controller : public IOEthernetController {
	OSDeclareAbstractStructors(IO80211Controller);
};
OSDefineMetaClassAndAbstractStructors(IO80211Controller, IOEthernetController);

class IO80211Interface : public IOEthernetInterface {
	OSDeclareDefaultStructors(IO80211Interface);
public:
	SInt32 performCommand(IONetworkController *ctr, unsigned long cmd, void *arg0, void *arg1) APPLE_KEXT_OVERRIDE;
	bool setUnitNumber(UInt16 unit) APPLE_KEXT_OVERRIDE;
};
OSDefineMetaClassAndStructors(IO80211Interface, IOEthernetInterface);

/* IO80211.framework finds the service of an interface by IOInterfaceName (en0); IONetworkStack registers it again after naming. */
bool
IO80211Interface::setUnitNumber(UInt16 unit)
{
	char name[16];
	snprintf(name, sizeof(name), "%s%u", getNamePrefix(), unit);
	setProperty("IOInterfaceName", name);
	return IOEthernetInterface::setUnitNumber(unit);
}

SInt32
IO80211Interface::performCommand(IONetworkController *ctr, unsigned long cmd, void *arg0, void *arg1)
{
	static int logged;
	if ((cmd == SIOCGA80211 || cmd == SIOCSA80211) && arg1) {
		struct apple80211req *r = (struct apple80211req *)arg1;
		return mido_wlan_a80211(cmd == SIOCSA80211, (uint32_t)r->req_type, &r->req_val, (user_addr_t)r->req_data,
		           &r->req_len);
	}
	SInt32 ret = IOEthernetInterface::performCommand(ctr, cmd, arg0, arg1);
	if (logged < 40) {
		logged++;
		IOLog("MIDO WLAN: ioctl %#lx from %s -> %d\n", cmd, current_proc() ? proc_best_name(current_proc()) : "?", (int)ret);
	}
	return ret;
}

class MidoWLAN : public IO80211Controller {
	OSDeclareDefaultStructors(MidoWLAN);
public:
	bool start(IOService *provider) APPLE_KEXT_OVERRIDE;
	bool interfaceAttached() const { return fNetif != NULL; }
	bool createWorkLoop(void) APPLE_KEXT_OVERRIDE;
	IOWorkLoop *getWorkLoop(void) const APPLE_KEXT_OVERRIDE;
	IOReturn enable(IONetworkInterface *netif) APPLE_KEXT_OVERRIDE;
	IOReturn disable(IONetworkInterface *netif) APPLE_KEXT_OVERRIDE;
	IOReturn getHardwareAddress(IOEthernetAddress *addr) APPLE_KEXT_OVERRIDE;
	UInt32 outputPacket(mbuf_t m, void *param) APPLE_KEXT_OVERRIDE;
	IOReturn setMulticastMode(bool active) APPLE_KEXT_OVERRIDE;
	IOReturn setMulticastList(IOEthernetAddress *addrs, UInt32 count) APPLE_KEXT_OVERRIDE;
	IOReturn setPromiscuousMode(bool active) APPLE_KEXT_OVERRIDE;
	IONetworkInterface *createInterface(void) APPLE_KEXT_OVERRIDE;

	void attach(const uint8_t *mac);
	void link(bool up);
	void input(mbuf_t m);
	void event(uint32_t code, const void *data, uint32_t len);
private:
	IOWorkLoop *fLoop;
	IOEthernetInterface *fNetif;
	IONetworkMedium *fMedium;
	IOEthernetAddress fMac;
	bool fBusy;
};
OSDefineMetaClassAndStructors(MidoWLAN, IO80211Controller);
#define super IO80211Controller

static MidoWLAN *gWLAN;

bool
MidoWLAN::start(IOService *provider)
{
	int on = 0;
	if (!PE_parse_boot_argn("midowlan", &on, sizeof(on)) || on != 1) {
		return false;
	}
	fNetif = NULL;
	fLoop = NULL;
	fMedium = NULL;
	fBusy = false;
	bzero(&fMac, sizeof(fMac));
	IOLog("MIDO WLAN: IOEthernetController start\n");
	if (!super::start(provider)) {
		IOLog("MIDO WLAN: IONetworkController::start FAILED\n");
		return false;
	}
	OSDictionary *media = OSDictionary::withCapacity(1);
	fMedium = IONetworkMedium::medium(kIOMediumIEEE80211Auto, WLAN_SPEED);
	if (!media || !fMedium || !IONetworkMedium::addMedium(media, fMedium) || !publishMediumDictionary(media)) {
		IOLog("MIDO WLAN: medium dictionary FAILED\n");
		OSSafeReleaseNULL(media);
		return false;
	}
	media->release();
	setSelectedMedium(fMedium);     /* SIOCGIFMEDIA's current type: IO80211.framework lists 802.11 interfaces by it */
	fBusy = false;
	gWLAN = this;
	IOLog("MIDO WLAN: IOEthernetController started, waiting for the radio\n");
	return true;
}

bool
MidoWLAN::createWorkLoop(void)
{
	fLoop = IOWorkLoop::workLoop();
	return fLoop != NULL;
}

IOWorkLoop *
MidoWLAN::getWorkLoop(void) const
{
	return fLoop;
}

IOReturn
MidoWLAN::enable(IONetworkInterface *netif __unused)
{
	return kIOReturnSuccess;
}

IOReturn
MidoWLAN::disable(IONetworkInterface *netif __unused)
{
	return kIOReturnSuccess;
}

IOReturn
MidoWLAN::getHardwareAddress(IOEthernetAddress *addr)
{
	*addr = fMac;
	return kIOReturnSuccess;
}

UInt32
MidoWLAN::outputPacket(mbuf_t m, void *param __unused)
{
	bool ready = mido_wlan_backend_ready();
	mido_wlan_output(m);        /* takes the mbuf */
	return ready ? kIOReturnOutputSuccess : kIOReturnOutputDropped;
}

/* The firmware passes all multicast and broadcast frames of the BSS. */
IOReturn
MidoWLAN::setMulticastMode(bool active __unused)
{
	return kIOReturnSuccess;
}

IOReturn
MidoWLAN::setMulticastList(IOEthernetAddress *addrs __unused, UInt32 count __unused)
{
	return kIOReturnSuccess;
}

IOReturn
MidoWLAN::setPromiscuousMode(bool active __unused)
{
	return kIOReturnSuccess;
}

IONetworkInterface *
MidoWLAN::createInterface(void)
{
	IO80211Interface *netif = new IO80211Interface;
	if (!netif) {
		return NULL;
	}
	if (!netif->init(this)) {
		netif->release();
		return NULL;
	}
	/* Before registerService: wifid waits for a service with this role (match notification). */
	netif->setProperty("IO80211InterfaceRole", "Infrastructure");
	netif->setInterfaceSubType(kIONetworkInterfaceSubTypeWiFi);     /* ifnet subfamily Wi-Fi (configd, IPConfiguration) */
	return netif;
}

/* The radio knows its MAC address (or failed: mac NULL): publish the interface, release IOKit. */
void
MidoWLAN::attach(const uint8_t *mac)
{
	if (mac && !fNetif && mido_wlan_backend_ready()) {
		memcpy(fMac.bytes, mac, sizeof(fMac.bytes));
		setLinkStatus(kIONetworkLinkValid, fMedium);
		if (attachInterface((IONetworkInterface **)&fNetif, true)) {
			IOLog("MIDO WLAN: IO80211Interface attached\n");
		} else {
			IOLog("MIDO WLAN: attachInterface FAILED\n");
		}
	}
	if (fBusy) {
		fBusy = false;
		adjustBusy(-1);
	}
}

/* Event data: the interface name (16 bytes), then the payload. */
void
MidoWLAN::event(uint32_t code, const void *data, uint32_t len)
{
	char name[16] = "";
	struct kev_msg ev = {};
	if (!fNetif) {
		return;
	}
	snprintf(name, sizeof(name), "%s%u", fNetif->getNamePrefix(), fNetif->getUnitNumber());
	ev.vendor_code = KEV_VENDOR_APPLE;
	ev.kev_class = KEV_IEEE80211_CLASS;
	ev.kev_subclass = KEV_APPLE80211_SUBCLASS;
	ev.event_code = code;
	ev.dv[0].data_length = sizeof(name);
	ev.dv[0].data_ptr = name;
	if (len) {
		ev.dv[1].data_length = len;
		ev.dv[1].data_ptr = __DECONST(void *, data);
	}
	kev_post_msg(&ev);
}

void
MidoWLAN::link(bool up)
{
	setLinkStatus(up ? kIONetworkLinkValid | kIONetworkLinkActive : kIONetworkLinkValid, fMedium,
	    up ? WLAN_SPEED : 0);
	IOLog("MIDO WLAN: link %s\n", up ? "up" : "down");
}

void
MidoWLAN::input(mbuf_t m)
{
	if (fNetif) {
		fNetif->inputPacket(m);
	} else {
		mbuf_freem(m);
	}
}

/* For bsd/dev/sailfish_wlan.c (its thread runs after IOKit matched us, or never finds gWLAN). */
extern "C" bool
mido_wlan_iokit_attach(const uint8_t *mac)
{
	if (!gWLAN) {
		return false;
	}
	gWLAN->attach(mac);
	return gWLAN->interfaceAttached();
}

extern "C" void
mido_wlan_iokit_link(bool up)
{
	if (gWLAN) {
		gWLAN->link(up);
	}
}

extern "C" void
mido_wlan_iokit_event(uint32_t code, const void *data, uint32_t len)
{
	if (gWLAN) {
		gWLAN->event(code, data, len);
	}
}

extern "C" void
mido_wlan_iokit_input(mbuf_t m)
{
	if (gWLAN) {
		gWLAN->input(m);
	} else {
		mbuf_freem(m);
	}
}
#endif /* MIDO */
