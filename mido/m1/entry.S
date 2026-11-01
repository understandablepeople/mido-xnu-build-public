.section .text.boot,"ax"
.global _start
.global m1_halt
_start:
    b m1_entry
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
m1_entry:
    msr daifset, #15
    mov x19, x0
    mrs x20, CurrentEL
    cmp x20, #4
    b.eq m1_el1
    cmp x20, #8
    b.ne m1_halt
    mrs x21, sctlr_el2
    adr x22, m1_vectors
    msr vbar_el2, x22
    b m1_setup
m1_el1:
    mrs x21, sctlr_el1
    adr x22, m1_vectors
    msr vbar_el1, x22
m1_setup:
    tst x21, #1
    b.ne m1_halt
    tst x21, #4
    b.ne m1_halt
    msr spsel, #1
    adr x22, _image_end
    mov sp, x22
    isb
    mov x0, x19
    lsr x1, x20, #2
    bl m1_main
m1_halt:
    wfe
    b m1_halt
.macro vent slot
    .balign 128
    mov x0, #\slot
    b m1_exc
.endm
.balign 2048
m1_vectors:
    vent 0
    vent 1
    vent 2
    vent 3
    vent 4
    vent 5
    vent 6
    vent 7
    vent 8
    vent 9
    vent 10
    vent 11
    vent 12
    vent 13
    vent 14
    vent 15
m1_exc:
    bl m1_exception
    b m1_halt
