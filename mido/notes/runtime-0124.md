# 0124 hardware results (2026-11-06)

Fresh persistent console pulled read-only from TWRP into private
logs/gx-scm-0124-live-20261106.txt (254533 bytes, flush 277).

- CX POWER_ON a0222800; GX POWER_ON a0225800, first poll.
- Root command 2, configuration 0: forced XO, no PLL programming.
- Mem-acc 0 -> 0; clamp 1101 -> 1100; supply status 3: BHS ack set.
- Coarse GPU blocker mask 04: clocks remain disabled.
- SCM64 INFO self-query result 0 / available 1; PAS commands 1,2,5,6,7
  likewise available. This does not prove PAS6/13 peripheral support.
- WCNSS_CTRL edge6 absent; no firmware uploaded or radio started.
- vmd exec at 681351ms remains present despite plist experiment;
  Preferences 751192ms and MobileSMS 810246ms exec observed.

No GPU acceleration, authenticated firmware, network interface or vmd
causality claimed. Next candidate must gate branch enables on successful
CX/GX/BHS and unchanged XO root; include BIMC_GFX CBCR 59034 in addition
to the five earlier snapshot branches. No blind GPU register reads.

References: own board DT and pinned Android kernel
xiaomi-msm8953-devs/kernel_xiaomi_msm8953 at
 dbe33d8d742974d65b20971bcb91dee26ea56892:
clock-gcc-8953.c (BIMC_GPU GCC base, BIMC_GFX GFX base; both have no
programmable parent), msm-clocks-hwio-8953.h, clock-local2.c.
PAS supported semantics: upstream Linux v4.9 drivers/firmware/qcom_scm-64.c,
__qcom_scm_pas_supported: one scalar peripheral argument, result in x1.
Pinned scm.c/scm.h establish yielding SIP FNID plus SMC64 convention;
PAS supported must not accidentally reuse the atomic INFO function ID.
