# 0120 hardware findings and guarded0121/0122 follow-up

## Actual0120 evidence

User confirms bottom Control Center now opens, but apps no longer open;
reports roughly5FPS, not an instrumented frame-rate measurement.
Fresh TWRP recovery log logs/bhs-0120-live-20261106.txt has318745bytes,
flush468. All12 BHS preparation writes match exact readback; result1.
Supply control changed80000038->20000038, CX/GX/clocks still off,
supply-status0/blockers1f. Preparation is NOT acceleration/power-good.
HID bottom-edge mask includes0x800; interior taps have0x3, so edge flag
is not simply stuck on every contact. There are no exec lines for
Preferences/MobileSafari/MobileSMS and no corresponding app crash lines.
This does not establish why UI launch was blocked, or prove the apps
crashed. Do not undo the working gesture or alter authentication blindly.

Launchd exec uptime41035ms; PID1 dyld-map begins517556ms and returns0
at517644ms, elapsed87ms. SpringBoard exec530997ms, backboardd532008ms.
The long pre-map interval is established; its internal cause is not.
Do not blame an87ms syscall for the whole multi-minute delay.

## GPU0121

midogpucxpower=1 defaults0. After valid RPM CX ACK and successful BHS
preparation, requires GXoff/SWcontrolled, CXoff/SWcontrolled, BHS-mode
control/clamp/CPR prerequisites. Writes only CX GDSCR0185904c bit0 clear,
preserving all other programmable bits. Polls power-on bit31 at1us
intervals for at most1000polls; stops on readback mismatch or timeout.
No GX, root-clock/PLL, mem-acc, GPU/SMMU/SCM/fuse accesses. No rollback
of a possibly enabled shared domain. A failure is logged, not retried.

Pinned Android source dbe33d8d742974d65b20971bcb91dee26ea56892 gdsc.c
clears SW_COLLAPSE after checking HW_CONTROL and waits for PWR_ON.
Actual recovery DT CX node185904c has core_clk but no force-root or
parent-supply; GX185901c has force-enable-root-clk and GFX-LDO parent.
Therefore this stage stops at CX and does NOT copy the GX sequence.
GFX init corner4/RPM CX192 and BHS readbacks are already verified.
GX still needs mem-acc/root-clock/parent handling before power-on.
Even working GPU power does not implement command submission, graphics
memory management, shader/Metal integration or accelerated composition.

## Wi-Fi0121

midowifiaudit=1 defaults0. Reuses already mapped legacy SMEM after the
serialized RPM work, never opens any channel or writes shared state.
Bounds-checks the legacy allocation table and finds allocated exact
WCNSS_CTRL on APPS-WCNSS edge6, recording CID/type/reference count.
Rejects malformed sizes, invalid CID and duplicate matching entries.
No PAS/firmware/NV/IPC/DXE writes, networking or radio startup. Discovery
may return absent: it is evidence for the remoteproc bring-up dependency,
not a reason to impersonate a ready remote with an invented channel.

## App diagnostics0122

midospawndiag=1 defaults0. Logs original nonzero posix_spawn error,
parent name, best-effort bounded user path and monotonic uptime at
common cleanup label. Atomic cap64 reports per boot. Does not change
errno, launch arguments, entitlements, keybags or successful spawn path.
If no launch attempt reaches posix_spawn, this diagnostic cannot establish
the userspace launch rejection: collect UI behavior, do not claim a fix.

## Local validation

68 unittest cases PASS, one NDK skip; includes ASan/UBSan CX success,
last-poll success, timeout, readback mismatch, no-map/prerequisite gates
and whitelist that permits exactly one CX GDSCR write; WCNSS table
bounds/name/edge/duplicates/read-only checks and patch reconstruction.
MidoInput.cpp and kern_exec.c ARM64 object compile PASS.
Control Center0120 code remains unchanged. Full CI/hardware follow-up pending.

Published792ee02bca205b6f1f3ce419ee570e89a60caf28; CI42240304550 attempt1
never acquired a hosted runner and failed after15m with no compile steps.
One infrastructure rerun (job127977446146) also failed after15m without
acquiring a runner or compiling anything. No further blind retries.
No candidate kernel/image or reboot occurred. Phone verified still in
recovery. Next requires an available full-build runner, successful CI,
then strict candidate validation before temporary boot. Local tests and
ARM64 object checks are not substituted for a complete linked kernel.

User-authorized retry attempt3 acquired a runner and compiled7m54s.
Actual source error at kern_exec.c4207: declaration immediately after
bad: label. CI compiler rejects this pre-C23 syntax while the newer
local compiler accepted it. Diagnostic is now enclosed in a compound
statement. Regression test requires that statement block after the label.
New local preflight75tests(oneNDKskip),4ARM64objects and firmwarechecks
PASS; existing whole-repo validator failures unchanged. New fullCI needed.
