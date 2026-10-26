ENTRY(mido_bridge_test_start)
SECTIONS
{
    . = 0x10000000;
    .text : { *(.text .text.*) }
    .rodata : { *(.rodata .rodata.*) }
    . = ALIGN(4096);
    _writable_start = .;
    .data : { *(.data .data.*) }
    .bss (NOLOAD) : { *(.bss .bss.* COMMON) }
    _image_end = .;
    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) }
}
