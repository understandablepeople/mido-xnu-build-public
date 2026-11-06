## MIDO active 2026-11-06:0127 GPU external abort; safe temporary boot accepted

User panic photo resolves against exact0127 kernel: PCfffffff007a6a638,
MidoInput::touchRails+14d8, instructionb953d695 LDRw21,[x20,#13d4].
First GPU RBBM_STATUS read, PA01c013d4. ESR96000210 DFSC10 is synchronous
external abort, NOT previous permanent-map cleanup fault. Clock readiness
does not establish safe GPU MMIO. Missing prerequisite is not yet identified.
Recovery pull logs/cbcr-0127-panic-live-20261106.txt is STALE identical0126:
308360bytes SHA25bd9a6459df2d40efae3b6b5643f3c02a8be2a0d0a679b7252e8a4536b09cd8.
No fresh0127 console or successful GPU read established.
Recovery image uses SAME verified0127 kernel, only midogpustatus=0; all
other flags incl8CPU, CC, six clock checks, PAS and WiFi snapshot retained.
Image out/safe-0127-no-gpu-mmio-8cpu/package/mido-xnu-shim.img SHA256
243a362bdb3ff26918df2d6a32e857bb336ef0730190997c67482605180218f3.
Packaging/instruction scan/memory plan PASS. GitHub API unavailable; used
previous local validation plus exact pinned kernel hash, no new CI claimed.
Verified TWRPmido->stockmido->knownlk2nd->lk2nd-msm8953, RAMboot OKAY/status0.
Private logs/safe-0127-validation.json and safe-0127-temp-boot-20261106.json.
NO flash, rootfs or firmware writes. Physical boot/UI outcome still unknown.
NEXT user physical check, then fresh recovery log; investigate Android GPU
bus/security/reset prerequisites before any further GPU MMIO. Do not re-enable
midogpustatus=1 on hardware: source still contains unsafe opt-in probe.
ml_probe_read is unimplemented here; ml_nofault_copy is not MMIO fault recovery.
GPU acceleration and WiFi network remain unimplemented, not fixed by this boot.
