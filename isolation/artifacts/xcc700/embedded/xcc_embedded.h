/* xcc_embedded.h — invoke the xcc700 mini-C compiler in-process.
 *
 * The vendor xcc700 is a host CLI: read input.c, write output.elf,
 * fprintf errors to stderr, exit() on failure. Embedded callers want
 * none of that — they have C source as a memory buffer and want the
 * resulting Xtensa-LX7 ELF as another memory buffer plus a captured
 * error string. This header is the contract for the in-process port.
 *
 * Single-call API. NOT thread-safe: xcc700 keeps lots of state in
 * file-scope globals; concurrent calls would race. Wrap in a mutex if
 * you need to compile from multiple tasks.
 *
 * Memory ownership:
 *   - The returned `elf` pointer aliases an internal heap buffer
 *     OWNED by the embedded module. Valid until the next call to
 *     xcc_compile() (which frees + reallocs). Copy out if you need
 *     to outlive that.
 *   - The `err` pointer aliases a small static buffer (see
 *     XCC_ERR_BUF_SIZE). Always null-terminated. Empty on success.
 */
#ifndef XCC_EMBEDDED_H
#define XCC_EMBEDDED_H

#ifdef __cplusplus
extern "C" {
#endif

#include <stddef.h>
#include <stdint.h>

#define XCC_ERR_BUF_SIZE 1024

typedef struct {
    const uint8_t *elf;        /* compiled Xtensa-LX7 ELF, or NULL */
    int            elf_size;
    const char    *err;        /* null-terminated; "" on success */
    int            err_len;
    int            exit_code;  /* 0 = success, nonzero = compile error */
} xcc_result_t;

/* Compile `src` (length `src_len`) into Xtensa-LX7 relocatable ELF.
 * Result.elf valid until the next xcc_compile() call. */
xcc_result_t xcc_compile(const char *src, int src_len);

/* Free the internal output buffer. Optional; call on shutdown to
 * release the ~32 KiB heap allocation. */
void xcc_free_output(void);

#ifdef __cplusplus
}
#endif

#endif
