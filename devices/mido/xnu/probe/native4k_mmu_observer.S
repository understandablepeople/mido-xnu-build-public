.text
.balign 16
.global mido_native_mmu_trampoline
mido_native_mmu_trampoline:
    mov x27, x0
    mov x28, sp
    mrs x11, sctlr_el1
    mrs x12, tcr_el1
    mrs x13, ttbr0_el1
    mrs x14, ttbr1_el1
    mrs x15, mair_el1
    mrs x16, vbar_el1
    ldr x17, [x0, #8]
    ldur x18, [sp, #-8]
    movz x9, #0
    movk x9, #0x1240, lsl #16
    add x9, x9, #(mido_native_mmu_trampoline_low - mido_native_mmu_trampoline)
    br x9
mido_native_mmu_trampoline_low:
    dsb sy
    movz x10, #0x0800
    movk x10, #0xc0, lsl #16
    msr sctlr_el1, x10
    isb
    tlbi vmalle1
    dsb sy
    isb
    br x29
