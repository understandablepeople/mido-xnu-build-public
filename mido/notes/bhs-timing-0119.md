# 0117 hardware result;0118 BHS preparation and0119 timing

## Confirmed hardware evidence

User reports0117 working as before except bottom Control Center absent.
Photo shows launchd/libignition/shared-region and wakeup notification
messages at a repeatable multi-minute pause, followed by successful UI.
Fresh recovery log logs/gpu-cx-0117-live-20261106.txt:229983 bytes,flush245.
L6/L10 and smpa2 CX192 requests all return0 with matching valid RPM ACKs.
This verifies0117 ACK fix and receipt of the CX request. Both snapshots
still show CX00222801/GX08225801, clocks halted, blockers1f. A rail-level
vote is not an enabled GDSC and is not acceleration.8/8 CPUs verified.

Source inspection explains the photo without hiding errors:
vm_shared_region_start_address returns KERN_INVALID_ADDRESS for an empty
shared region; shared_region_check_np logs the shown text and returns
ENOMEM. This is not by itself proof of physical memory exhaustion or
dyld-cache corruption. The current boot subsequently maps the cache and
executes SpringBoard/backboardd.0x10000003 is MACH_SEND_INVALID_DEST in
the CPU-wakeups exception notification path, not a GPU result or panic.
Ignition-level warnings are consistent with the deliberately configured
ignition_level1 boot. Exact cause/duration of the pause is NOT established
by these untimestamped lines. Do not silently suppress them as a fix.

## GPU0118

midogpubhs=1 (default0) runs only after the serialized CX request returned0.
Reads only previously audited GCC/LDO window, requires GX physically off,
SW-collapse asserted and no HW-control. Builds12 writes from pinned
msm8953 GFX-LDO init/enable_bhs_mode: clamp/CPR init, five board-specific
config registers, LDO software control, BHS selection/CPR bypass clearing,
BHS handoff to GDSC. Preserves unrelated control bits. Each write has a
barrier and exact readback; first mismatch stops, with no downstream work.
No GDSC collapse clearing, mem-acc, clock/PLL, GPU/SMMU/SCM/fuse accesses.
No automatic rollback of partial power config. This is preparation with
GX still off, not BHS power-good or rendering. Supply-status0 may persist.
The next real power-on stage still needs correct parent/memacc/root-clock
and GDSC sequencing. Do not treat blocker changes as a working GPU.

## Boot and Control Center diagnostics0119

Existing short exec logs get monotonic uptime-ms on MIDO. PID1 cache
map-and-slide syscall gets begin/end uptime, elapsed-ms and return code.
This brackets the actual map call; a pause outside those markers must
not be attributed to that call. No return values/cache/security changed.

Bounded first64 HID contact summaries additionally report monotonic
duration-ms and max inter-event gap-ms. This distinguishes a quick swipe
from a delayed/sparse stream at custom HID dispatch, not from userspace
recognizer state. No coordinates/masks/identities changed, no synthesized
swipes. System gesture policy and event-ABI compatibility remain open.

## Wi-Fi parallel source work

mido/wifi/mido_wcnss_control.h implements pure little-endian version
request and NV fragment builders matching pinned wcnss_wlan.c:
8byte control header,16byte NV header,3072byte chunks,zero-based fragment
IDs, LAST flag on final chunk, skip the four-byte validity bitmap.
Never claims calibration upload capability unless explicitly requested;
runtime path is not wired and receive handling must exist before doing so.
Supports bounded64KiB payload and unaligned output; rejects malformed size,
short output and invalid index before writes. No private NV bytes in git.
No SMD WCNSS channel/DXE DMA/network interface or radio startup yet.

## Validation

66 tests PASS, one NDK skip; includes ASan/UBSan BHS pure-plan bit
preservation65536 cases, runtime default/no-map/prerequisite gates, all12
readback failure positions, allowed write offsets; WCNSS fragment boundary
reassembly, actual private NV size31723 synthetic equivalent, bitmap skip,
capability flags and output sentinels; gesture duration tests and patch
reconstruction. Four ARM64 objects compile: MidoInput/MidoHID/kern_exec/
vm_unix. Full CI and BHS hardware result pending. Preserve0117 rollback.
