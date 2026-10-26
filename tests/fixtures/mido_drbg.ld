ENTRY(mido_drbg_init)
SECTIONS
{
    . = 0x10000000;
    .text : { *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    .data : { *(.data .data.*) }
    .bss : { *(.bss .bss.* COMMON) }
    ASSERT(SIZEOF(.bss) == 0, "DRBG test must not have global mutable state")
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
