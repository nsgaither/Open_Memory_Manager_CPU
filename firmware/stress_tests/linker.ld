OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{
    BOOT (rx) : ORIGIN = 0x00000000, LENGTH = 512
}

SECTIONS
{
    . = ORIGIN(BOOT);

    .text : {
        KEEP(*(.text.start))
        *(.text*)
        *(.rodata*)
    } > BOOT

    . = ALIGN(4);
    _end = .;

    ASSERT(_end <= ORIGIN(BOOT) + LENGTH(BOOT), "stress program exceeds 512-byte boot image")

    /DISCARD/ : {
        *(.comment)
        *(.eh_frame*)
        *(.note*)
        *(.riscv.attributes)
    }
}
