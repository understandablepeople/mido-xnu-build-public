ENTRY(_start)
SECTIONS
{
    . = 0;
    .text : { KEEP(*(.text.boot)) *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    .data : { *(.data .data.*) }
    .bss : { *(.bss .bss.* COMMON) }
    ASSERT(SIZEOF(.bss) == 0, "Unexpected BSS requires explicit initialization")
    .stack : { . = ALIGN(16); BYTE(0); . += 16383; . = ALIGN(16); }
    _image_end = .;
    ASSERT(_image_end < 0x10000, "Payload exceeds 64 KiB limit")
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
