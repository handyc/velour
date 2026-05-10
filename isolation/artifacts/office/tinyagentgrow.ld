/* tinyagentgrow.ld — pack .text/.rodata/.data into a single contiguous
 * LOAD segment so the linker doesn't waste 1968 B of zero-padding
 * page-aligning .data away from .rodata.  The combined segment is
 * RWX (the kernel can't enforce W^X across them without page
 * granularity).  Modern kernels warn but accept; older kernels
 * just load it.  Same trick old static binaries (a.out OMAGIC) used.
 *
 * Reference layout from default build (objdump-derived):
 *   .text   400178..405DDF (5C67)
 *   .rodata 405DE0..40784F (1A70)
 *   .data   408000..4081CF (01D0)   ← page-aligned, 1968 B gap
 *   .bss    4081E0..       (BSS, no on-disk cost)
 *
 * After packing:
 *   .text   400178..405DDF
 *   .rodata 405DE0..40784F
 *   .data   407850..407A1F   ← contiguous, no gap
 *   .bss    407A20..         (BSS, no on-disk cost)
 */
ENTRY(_start)
PHDRS {
    text PT_LOAD FLAGS(7);   /* R+W+X (single segment) */
}
SECTIONS {
    . = 0x400000 + SIZEOF_HEADERS;
    .text    : { *(.text .text.*) } :text
    .rodata  : { *(.rodata .rodata.*) } :text
    .data    : { *(.data .data.*) } :text
    .bss     : { *(.bss .bss.* COMMON) } :text
    /DISCARD/ : {
        *(.note.gnu.property)
        *(.comment)
        *(.eh_frame)
        *(.eh_frame_hdr)
    }
}
