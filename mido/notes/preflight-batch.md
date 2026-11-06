# Batched GPU/Wi-Fi preflight

Run from the Windows repository root:

    python -I tools/mido-preflight.py --recovery-read

Omit --recovery-read for host-only checks. Requires the existing Ubuntu
WSL toolchain/buildtree and private firmware directory; downloads nothing.
At most3 independent checks run together. Every check has a300second
limit and an individual log; failures do not suppress the other checks.
Output is a new local logs/preflight-TIMESTAMP directory and report.json.
Device logs, firmware hashes and source fingerprints stay local, not git.
No reboot, flash, debugfs/MMIO probe, radio scan or firmware upload.

## Coverage

- Native input/HID/scanout, RPM ACK, GPU corner/BHS/CX power and WCNSS
  firmware/protocol/discovery tests, including ASan/UBSan host executables.
- Added WCNSS audit runtime test: disabled/invalid modes cannot dereference
  a bogus context; null/short/unsupported heap mappings fail closed;
  allocation offset/size/base_ext bounds, valid discovery and no SMEM writes.
- Four ARM64 objects together: MidoInput, MidoHID, kern_exec, vm_unix.
  Canonical input/GPU/Wi-Fi files must match the local compilation tree.
- Own A506 ZAP/microcode bundle structure and WCNSS bundle plus board DT
  reservation/relocation validation. Not cryptographic authentication.
- Existing whole-repository syntax/patch-number validator, reported without
  masking unrelated failures or silently repairing existing files.
- Optional recovery-only console ring pull and Linux dmesg collection.

## Actual2026-11-06 batch

Private report logs/preflight-20261106T154513Z/report.json.
Six of seven checks passed; full batch intentionally returns failure because
repository-integrity failed. Native suite reports74tests, one NDK skip.
All four ARM64 objects compile. A506/WCNSS structural checks pass.
Maximum task duration19.4seconds; no repeated CI allocation attempt.
Whole-repo validator reports12 historical numbering gaps and CRLF-related
bash syntax errors in3 unchanged scripts: mkiosroot.sh, sweet-log-pull.sh,
sweet-usbnet.sh. These scripts have no local diff; gaps predate0121/0122.
Python tool syntax passes. Do not call the whole batch fully green.

Recovery ring is still318745bytes/flush468 and byte-identical to the
previous0120log. This is NOT a new0121hardware execution. TWRP dmesg
is Linux reference evidence only. No0122kernel/image exists, full link
and runtime CX/WCNSS/spawn diagnostics are pending a build runner.

User clarifies app icons darken but no app window appears. This confirms
visible press feedback, not why launch is rejected. The log lacks app
exec/crash records; do not call it an app crash or declare a security fix.

## Next hardware cycle

Keep0120working edge gesture unchanged. Once a complete kernel is built,
use the already prepared0122candidate flags for CX-domain stage, Wi-Fi
SMEM discovery and bounded spawn errors together. One physical check and
one recovery log can cover all three instead of separate reboot cycles.
Power dependencies must remain sequenced and gated: passing host checks
cannot authorize skipping rail/BHS/readback/memory/clock prerequisites.
This preflight does not implement GPU rendering or a WLAN network driver.
