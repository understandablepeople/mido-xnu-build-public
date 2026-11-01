.text
.balign 16
.global mido_ttbr0_return
.global mido_ttbr0_return_restore_ttbr0
.global mido_ttbr0_return_capture
.global mido_ttbr0_return_restore
.global mido_ttbr0_return_restored
.global mido_ttbr0_return_branch
.global mido_ttbr0_return_reject
.global mido_ttbr0_return_end
.global mido_ttbr0_return_record
.global mido_ttbr0_return_magic
.equ mido_ttbr0_return_record, 0x12400900
.equ mido_ttbr0_return_magic, 0x3130305445523054
mido_ttbr0_return:
    mrs x10, ttbr0_el1
    movz x9, #0x1000
    movk x9, #0x1240, lsl #16
    cmp x10, x9
    b.ne mido_ttbr0_return_reject
    mrs x11, ttbr1_el1
    movz x9, #0x2000
    movk x9, #0x1240, lsl #16
    cmp x11, x9
    b.ne mido_ttbr0_return_reject
    mrs x12, daif
    cmp x12, #0x3c0
    b.ne mido_ttbr0_return_reject
    mrs x13, tcr_el1
    movz x9, #0x251a
    movk x9, #0xa51a, lsl #16
    movk x9, #0x22, lsl #32
    cmp x13, x9
    b.ne mido_ttbr0_return_reject
    movz x9, #0x2000
    movk x9, #0x1135, lsl #16
    dsb sy
mido_ttbr0_return_restore_ttbr0:
    msr ttbr0_el1, x9
    isb
    tlbi vmalle1
    dsb sy
    isb
mido_ttbr0_return_capture:
    movz x9, #0x0900
    movk x9, #0x1240, lsl #16
    movz x17, #0x3054
    movk x17, #0x4552, lsl #16
    movk x17, #0x3054, lsl #32
    movk x17, #0x3130, lsl #48
    mrs x14, sctlr_el1
    mov x15, sp
    mrs x16, vbar_el1
    stp x17, x11, [x9]
    stp x10, x13, [x9, #16]
    stp x14, x12, [x9, #32]
    stp x15, x16, [x9, #48]
    mrs x10, ttbr0_el1
    str x10, [x9, #72]
    movz x10, #0x3000
    movk x10, #0x1135, lsl #16
    dsb sy
mido_ttbr0_return_restore:
    msr ttbr1_el1, x10
    isb
    tlbi vmalle1
    dsb sy
    isb
mido_ttbr0_return_restored:
    mrs x10, ttbr1_el1
    str x10, [x9, #64]
    movz x10, #0
    movk x10, #0x0820, lsl #16
    movk x10, #0xfff0, lsl #32
    movk x10, #0xffff, lsl #48
mido_ttbr0_return_branch:
    br x10
mido_ttbr0_return_reject:
    wfe
    b mido_ttbr0_return_reject
mido_ttbr0_return_end:
