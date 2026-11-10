# GPU CP bring-up facts collected 2026-11-10 (read-only research; nothing here is hardware-proven)

## Verified on mido (logs/gpu-0138-live-20261110.txt, 42 reads, 0 aborts)
- CP idle: CP_CNTL=0 RB_BASE=0 RPTR=WPTR=0 PFP/PM4_BASE=0 INT_STATUS=0; CP_ME_CNTL=0x303; SECVID_TRUST_CNTL=0 TSB_CNTL=0
- SMMU 0x01c40000: sCR0=00200436 IDR0=78014404 (4 SMRs). SMR0=80010000(ids0-1)->CB0, SMR1(id2)->CB1, SMR2(id3)->CB3
- CBAR0/1/3=0001b003/b006/b008 (type 1 = S1 trans, S2 bypass; VMID 3/6/8; MEMATTR 0xb), CBA2R0=0 (32-bit ctx fmt)
- CB0/1/3 SCTLR=0 (disabled), CB0 TTBR0=0 MAIR0=0 TTBCR=80000000 FSR=00000200
- DT: gfx3d_user iommus <&smmu 0>; gfx3d_secure <&smmu 2>; smmu has qcom,enable-static-cb + qcom,skip-init

## Android (pinned dbe33d8d...) CP bring-up, a506 path (research/kgsl-ref, research/b138_facts*.txt)
- a5xx_start writes (byte offsets, verified vs a5xx_reg.h): VBIF_ROUND_ROBIN_QOS_ARB 0xc124=3, RBBM_AHB_CNTL0 0x24c=1,
  CP_MEQ_THRESHOLDS 0x2094, CP_MERCIU_SIZE 0x2098, CP_ROQ_THRESHOLDS_1/2 0x207c/0x2080 (a506: 0x40201B16/0x80000060 with 0x40/0x40 per the 4th branch),
  UCHE_*: CACHE_WAYS 0x3a58=2, TRAP_BASE 0x3a24=0x0001ffffffff0000, WRITE_THRU_BASE 0x3a1c=same, GMEM_RANGE_MIN/MAX 0x3a2c/0x3a34, PC_DBG_ECO 0x3400, UCHE_MODE 0x3a04, CP_CHICKEN_DBG 0x20cc=0x02000000
- a5xx_rb_start: CP_RB_RPTR_ADDR(64), CP_RB_CNTL=A5XX_CP_RB_CNTL_DEFAULT, CP_RB_BASE(64), microcode load (INSTR_BASE_LO/HI = GPU VA of fw buffer),
  CP_ME_CNTL=0 (clear halt), CP_ME_INIT (type7 packet, 8 dwords: mask, 3, 0x20000000, 0,0, 0xb, 0,0 ; mask bits 0,1,3,5), then unsecure mode via ring, GPMU init
- firmware buffers: fw->data+4, size-4 bytes (a530_pm4.fw 19572 B -> 4892 dwords; a530_pfp.fw 15876 B -> 3968 dwords); read-only, GPU VA through SMMU
- ZAP: PAS id 13, 'a506_zap', gpu_region@0 shared-dma-pool 8 MiB (alloc 0x80000000-0x90000000)

## Pixel 1 (ios-sailfish 0120-0131) lessons
- CP fetches microcode through the SMMU; its first fetch without a working SMMU context reset the phone.
- Context bank 0, S1 AArch64 4K, identity 1GB blocks, SMR0 = stream 0 only; an SMR matching all streams stalled the CPU on S2CR write.
- GPU starts in secure mode (RB writes nothing); leaving it needs ZAP via PAS or CP_SET_SECURE_MODE after ZAP.

## What is NOT known
- Whether EL1 may write CB0/CBAR/SMR/S2CR on this TZ build (static-cb: TZ owns them) - a write may reset the phone.
- Whether the SCM 'restore sec cfg' (0x0c02, already run) leaves CB0 programmable or locked.
- Whether SECVID_TRUST_CNTL=0 means unsecured or just an unreadable shadow.
