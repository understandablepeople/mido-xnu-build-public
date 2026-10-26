.section .text.boot,"ax"
.global _start
.global screen_halt
.global diagnostics_brk_probe
.global diagnostics_brk_instruction
.global diagnostics_counter
.global diagnostics_frequency
_start:
    b diagnostics_entry
    nop
    .quad 0x80000
    .quad _image_end - _start
    .quad 0
    .quad 0
    .long 0
    .long _image_end - _start
    .quad 0
    .long 0x644d5241
    .long 0
diagnostics_entry:
    msr daifset, #15
    mov x19, x0
    mov x28, xzr
    mrs x20, CurrentEL
    cmp x20, #4
    b.ne screen_halt
    mrs x21, sctlr_el1
    tst x21, #1
    b.ne screen_halt
    tst x21, #4
    b.ne screen_halt
    msr spsel, #1
    adr x22, _image_end
    mov sp, x22
    adr x22, diagnostics_vectors
    msr vbar_el1, x22
    isb
    mov x0, x19
    mov x1, #1
    bl screen_main
screen_halt:
    wfe
    b screen_halt
.balign 2048
diagnostics_vectors:
    .rept 4
    b diagnostics_unexpected
    .space 124
    .endr
    b diagnostics_sync
    .space 124
    .rept 11
    b diagnostics_unexpected
    .space 124
    .endr
diagnostics_sync:
    stp x9, x10, [sp, #-32]!
    stp x11, x12, [sp, #16]
    mrs x9, esr_el1
    movz w10, #0x4d49
    movk w10, #0xf200, lsl #16
    cmp x9, x10
    b.ne diagnostics_unexpected
    mrs x11, elr_el1
    adr x12, diagnostics_brk_instruction
    cmp x11, x12
    b.ne diagnostics_unexpected
    add x11, x11, #4
    msr elr_el1, x11
    ldp x11, x12, [sp, #16]
    ldp x9, x10, [sp], #32
    eret
diagnostics_unexpected:
    msr daifset, #15
    cbz x28, screen_halt
    mov x0, x28
    mov x28, xzr
    adr x9, _image_end
    sub x9, x9, #12288
    mov sp, x9
    mrs x1, esr_el1
    mrs x2, elr_el1
    mrs x3, far_el1
    mrs x4, spsr_el1
    bl diagnostics_fault
    b screen_halt
diagnostics_brk_probe:
diagnostics_brk_instruction:
    brk #0x4d49
    mrs x9, esr_el1
    str x9, [x0]
    mrs x9, elr_el1
    str x9, [x0, #8]
    mrs x9, spsr_el1
    str x9, [x0, #16]
    mov x0, #1
    ret
diagnostics_counter:
    isb
    mrs x0, cntvct_el0
    ret
diagnostics_frequency:
    mrs x0, cntfrq_el0
    ret
