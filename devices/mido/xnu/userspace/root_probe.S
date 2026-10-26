.text
.p2align 2
.globl _start
_start:
    mov x16, #20
    svc #0x80
    mov x19, x0
    mov x20, #0x4d49
    movk x20, #0x444f, lsl #16
1:
    yield
    b 1b
