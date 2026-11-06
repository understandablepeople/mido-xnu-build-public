# 0128: linkable donor frontends, explicit hardware backend boundary

## What changed

The canonical GPU/WLAN IOKit frontends now live under mido/gpu and mido/wifi.
They derive from Sailfish6f27e41ff249f2680540ebe8ee5ab982c5e641c9, prepared
by tools/mido_prepare_donors.py. MidoGPU keeps the SweetGPU service and ABI
used by the existing Mesa/sweetgl bridge, but imports existing MidoSurface
buffers. MidoWLAN keeps the Apple80211/IOEthernet facade with mido callbacks.
The source lists, per-object private networking flags and IOKit matching
are wired in0128-mido-donor-backend-bridges.patch.

0128-stage-ionetworking.sh reuses the donor's staging procedure for Apple's
IONetworkingFamily170.140.2, pinned commitf9f7e57b2132b82de09a26ddcbf56fd8125b4933.
It only stages on MIDO/macOS13.5 and refuses to overwrite an existing family.
The twelve network compilation units are listed in the patch, not appended
by the script: appending first made the EOF source-list hunk fail in the
local integration check. That failure was caught and fixed before any CI.
The stage script does not access a phone or private firmware.

## What is NOT implemented

There is still NO hardware backend registered on the real phone. No code
currently calls mido_gpu_register_backend or mido_wlan_register_backend
outside tests. These are integration contracts, not replacement simulated
hardware. The wrappers return ENXIO/zero/unready until an actual built-in
hardware driver registers; an incomplete or not-ready backend is rejected.
No rendering, firmware boot, radio scan/join or frame transmission succeeded
as a result of this source integration. Do NOT describe it as accelerated
or network-capable firmware, and do not boot it just to see an empty service.

The physical blockers are unchanged: GPU access at01c013d4 caused a synchronous
external abort on0127; WCNSS still needs real PAS6 firmware loading/startup,
supplies/proxy clocks, SMD control and Prima/DXE transport. The Apple80211
scan/association dispatcher is still donor radio-specific C code and has
not been connected to Pronto. No Mesa dylib was built or installed.

## Runtime safety and backend contracts

GPU frontend is opt-in midogpubridge=1, WLAN frontend opt-in midowlan=1.
Both are off in the current working safe0127 image. SweetGPU user clients
refuse to initialize without a ready backend. The GPU registration validates
A506 identity05000600 and GMEM139264bytes, preserving the existing ABI instead
of exporting A530 identity. Backend functions are copied once and immutable
for the boot lifetime. No hot-unload/unregister contract is supported.
Ready callbacks remain authoritative after registration. GPU unmap still
reaches the registered backend after readiness is lost so clients can clean
up allocations. Fence-page delivery is one-shot and tested for either init
order. Hardware implementations own their DMA, isolation, fences and timeouts.
The shared GPU address-space security limitation of the donor frontend still
exists; this is experimental single-device bring-up, not a secure release.

The photographed crashing GPU status probe now additionally requires
sweet_gpu_ready before ANY mapping, not merely six clock status bits. With
no real backend, even accidental midogpustatus=1 cannot run that read path.
This is a guard, not a fix for the underlying hardware external abort.

WLAN does not hold IOKit busy waiting indefinitely for absent firmware.
No en0 is attached until a real backend is ready and supplies a MAC.
Transmit ownership is explicit: the registered backend consumes the mbuf;
without a ready backend it is freed and outputPacket reports dropped.
No fabricated MAC, scan results, link-up, DHCP or successful ioctls are used.

## Validation

Local single-file cross-compiles:17 ARM64 objects PASS, comprising both
frontends, both backend adapters, MidoInput and all twelve Apple network
sources. This is NOT a full linked kernel or CI result.
Local compiled-object import audit is recorded separately; comparison
against the linked0127 symbol table is not a substitute for a new kernel link.
Focused native adapter tests use ASan/UBSan: absent/not-ready/invalid/repeated
registration, donor chip rejection, forwarding, loss of readiness, cleanup,
buffer ownership and fence ordering. Source tests reconstruct all seven
canonical bridge sources from the patch and verify source lists and pins.
Full-suite result is recorded below after the final run.
Final full native suite:105 tests,OK,one NDK-dependent skip,8.464seconds.
Object import audit against externally defined0127+new-object symbols:
zero unmatched imports. Stage-order patch check and bash syntax check PASS.
Private logs/bridge-0128-arm64.txt, bridge-0128-symbols.json,
bridge-0128-full-tests-final.txt. Downloaded Apple sources and object files
stay ignored. No firmware/backups/calibration/device identifiers are committed.

## Next actual hardware work

Do not ask for a reboot of unchanged or inactive code. Before enabling GPU,
complete the Android-derived pre-MMIO power/frequency/AXI/SMMU prerequisites
and establish safe GPU access; then implement/validate the A506 CP/BO/fence
backend and register it through mido_gpu_register_backend. Do not transplant
Sailfish's A530 power thread, fixed carveouts or high-frequency votes.
For Wi-Fi, implement the mido PAS6/Pronto startup/control/DXE backend and
radio-independent Apple80211 dispatcher, then register and publish through
the existing mido_wlan_iokit callbacks. Hardware success requires fresh
runtime logs plus actual rendering/scan/association/network tests.
No long CI build or temporary phone boot is justified merely to activate
these currently unbacked interfaces. Stable touch/display/8CPU stay intact.
