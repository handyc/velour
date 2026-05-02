/* xcc_button_kit — drop-in for cycling baked-in C snippets via a
 * button press.
 *
 * The 5 HTTP-less ESP targets in isolation/artifacts/ have the
 * embedded xcc700 compiler linked in (xcc_compile() is callable) but
 * no network endpoint to drive it. This kit is the thinnest possible
 * trigger surface: register a fixed table of C source snippets, call
 * xcc_button_advance() whenever your debounced button fires, and the
 * kit compiles the next snippet then hands the resulting ELF to a
 * caller-supplied apply callback that does whatever hot-load makes
 * sense for that target (load_elf_text + slot patch, write to
 * LittleFS, jump to entry, …).
 *
 * Debouncing is the caller's job. The kit is deliberately ignorant
 * of GPIO — point it at any trigger event you like (button, serial
 * char, sensor threshold, etc.).
 */
#ifndef XCC_BUTTON_KIT_H
#define XCC_BUTTON_KIT_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Apply callback — invoked after each successful compile. The kit
 * calls this with the compiled ELF; the caller decides what to do
 * with it (typical: extract .text via the same load_elf_text pattern
 * esp32_s3_xcc/main.cpp uses, then patch a hot-loop function pointer).
 *
 * If the apply callback is unset, xcc_button_advance() still cycles
 * the index + compiles, but the ELF is dropped on the floor. That's
 * useful for smoke-testing the compile path without wiring anything
 * downstream yet.
 *
 * snippet_idx: 0-based index in the registered table.
 * snippet_src: the C source pointer the kit was given for that slot.
 * elf, elf_size: the compile output (aliases an internal buffer
 *                owned by xcc_embedded; valid until the next
 *                xcc_button_advance call). */
typedef void (*xcc_button_apply_t)(int snippet_idx,
                                    const char *snippet_src,
                                    const uint8_t *elf, int elf_size);


/* Register the snippet table. Stores the array pointer — caller must
 * keep snippets[] alive for the program's lifetime (typical: const
 * char *const arr[] = {...} in flash). Resets the active index to 0.
 * Pass n=0 to clear. */
void xcc_button_register_snippets(const char *const *snippets, int n);

/* Register the apply callback. NULL clears it. */
void xcc_button_set_apply(xcc_button_apply_t cb);

/* Advance to the next snippet (wraps), compile it, invoke the apply
 * callback on success.
 * Returns the active index AFTER advancing on success, or -1 if no
 * snippets registered or the compile failed. The kit prints a one-
 * line summary to Serial in either case (compile time, ELF size on
 * success; first line of captured stderr on failure). */
int xcc_button_advance(void);

/* Re-run the currently active snippet without advancing. Useful for
 * a "retry" button distinct from a "next" button. */
int xcc_button_reapply(void);

/* Status accessors for HUDs. */
int xcc_button_active(void);
int xcc_button_total(void);
const char *xcc_button_active_src(void);

#ifdef __cplusplus
}
#endif

#endif
