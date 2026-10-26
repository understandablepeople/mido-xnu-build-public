.macro MIDO_EARLY_MARK row
    movz x9, #((0x90001000 + (\row * 3240) + 180) & 0xffff)
    movk x9, #((0x90001000 + (\row * 3240) + 180) >> 16), lsl #16
    mov x10, #16
    mov w12, #-1
991:
    mov x11, #48
992:
    str w12, [x9], #4
    subs x11, x11, #1
    b.ne 992b
    add x9, x9, #3048
    subs x10, x10, #1
    b.ne 991b
    dsb sy
.endmacro
