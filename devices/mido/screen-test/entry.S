.section .text.boot,"ax"
.global _start
.global screen_halt
_start:
    b screen_entry
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
screen_entry:
    msr daifset, #15
    mov x19, x0
    mrs x20, CurrentEL
    cmp x20, #4
    b.eq screen_el1
    cmp x20, #8
    b.ne screen_halt
    mrs x21, sctlr_el2
    adr x22, screen_vectors
    msr vbar_el2, x22
    b screen_setup
screen_el1:
    mrs x21, sctlr_el1
    adr x22, screen_vectors
    msr vbar_el1, x22
screen_setup:
    tst x21, #1
    b.ne screen_halt
    tst x21, #4
    b.ne screen_halt
    msr spsel, #1
    adr x22, _image_end
    mov sp, x22
    isb
    mov x0, x19
    lsr x1, x20, #2
    bl screen_main
screen_halt:
    wfe
    b screen_halt
.balign 2048
screen_vectors:
    .rept 16
    b screen_halt
    .space 124
    .endr
