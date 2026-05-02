/* xcc_shim.c — implements the xcc_* libc replacements + the public
 * xcc_compile() API around the vendor compiler.
 *
 * Lives in its own translation unit so it can include real stdio /
 * stdlib / string headers without those fighting the relaxed
 * prototypes the vendor declares at the top of xcc700.c.
 */
#include "xcc_embedded.h"
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <setjmp.h>


/* ── shim state ───────────────────────────────────────────────── */

#define XCC_FD_INPUT  3
#define XCC_FD_OUTPUT 4

static const char *xcc_in_src   = NULL;
static int         xcc_in_size  = 0;
static int         xcc_in_pos   = 0;

static char       *xcc_out_buf  = NULL;
static int         xcc_out_cap  = 0;
static int         xcc_out_size = 0;
static int         xcc_out_pos  = 0;

static char        xcc_err_buf[XCC_ERR_BUF_SIZE];
static int         xcc_err_len  = 0;

static jmp_buf     xcc_exit_jmp;
static int         xcc_exit_code = 0;
static int         xcc_exit_taken = 0;


/* Forward decl from the vendor wrap TU — the vendor's main() under
 * a renamed symbol. */
extern int xcc_main_real(int argc, char **argv);

/* The vendor's file-scope globals (extern from this TU since we need
 * to reset them between calls). Names + types must match xcc700.c. */
extern char *src;
extern char *rodata; extern int rodata_sz; extern int rodata_cap;
extern int token; extern int num_val; extern int line; extern int token_cnt;
extern int str_len;
extern char *code_data; extern int code_size; extern int code_cap;
extern char *name_buf; extern int name_sz; extern int name_cap;
extern int n_vars; extern int locals; extern int esp; extern int expr_type;
extern int n_globals; extern int bss_size;
extern int n_funcs; extern int n_lits; extern int n_patches;


/* ── output buffer growth ────────────────────────────────────── */

static int xcc_out_grow_to(int needed) {
    if (needed <= xcc_out_cap) return 1;
    int cap = xcc_out_cap ? xcc_out_cap : 8192;
    while (cap < needed) cap *= 2;
    char *nb = (char *)realloc(xcc_out_buf, cap);
    if (!nb) return 0;
    xcc_out_buf = nb;
    xcc_out_cap = cap;
    return 1;
}


/* ── libc / syscall replacements (signatures match vendor) ────── */

int xcc_open(char *path, int flags, int mode) {
    (void)path; (void)mode;
    /* O_RDONLY=0, O_WRONLY=1 in the vendor's enum. */
    if ((flags & 3) == 0) return XCC_FD_INPUT;
    return XCC_FD_OUTPUT;
}

int xcc_close(int fd) { (void)fd; return 0; }

int xcc_read(int fd, void *buf, int count) {
    if (fd != XCC_FD_INPUT) return 0;
    int n = xcc_in_size - xcc_in_pos;
    if (n > count) n = count;
    if (n > 0) {
        memcpy(buf, xcc_in_src + xcc_in_pos, (size_t)n);
        xcc_in_pos += n;
    }
    return n;
}

int xcc_write(int fd, void *buf, int count) {
    if (fd != XCC_FD_OUTPUT) return 0;
    if (!xcc_out_grow_to(xcc_out_pos + count)) return 0;
    memcpy(xcc_out_buf + xcc_out_pos, buf, (size_t)count);
    xcc_out_pos += count;
    if (xcc_out_pos > xcc_out_size) xcc_out_size = xcc_out_pos;
    return count;
}

int xcc_lseek(int fd, int offset, int whence) {
    /* SEEK_SET=0, SEEK_END=2 in the vendor's enum. */
    if (fd == XCC_FD_INPUT) {
        if (whence == 2) return xcc_in_size;
        if (whence == 0) { xcc_in_pos = offset; return offset; }
        return -1;
    }
    if (fd == XCC_FD_OUTPUT) {
        if (whence == 2) return xcc_out_size;
        if (whence == 0) {
            if (!xcc_out_grow_to(offset)) return -1;
            if (offset > xcc_out_size) {
                memset(xcc_out_buf + xcc_out_size, 0,
                       (size_t)(offset - xcc_out_size));
                xcc_out_size = offset;
            }
            xcc_out_pos = offset;
            return offset;
        }
    }
    return -1;
}

int xcc_printf(char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    int avail = (int)sizeof(xcc_err_buf) - xcc_err_len - 1;
    if (avail > 0) {
        int n = vsnprintf(xcc_err_buf + xcc_err_len, (size_t)avail, fmt, ap);
        if (n > 0) {
            if (n > avail) n = avail;
            xcc_err_len += n;
        }
    }
    va_end(ap);
    return 0;
}

void xcc_exit(int code) {
    xcc_exit_code = code;
    xcc_exit_taken = 1;
    longjmp(xcc_exit_jmp, 1);
}

int xcc_clock(void) {
    /* Vendor uses this for the BUILD COMPLETED stats; we don't print
     * those, so timing is irrelevant. */
    return 0;
}


/* ── public API ──────────────────────────────────────────────── */

static void xcc_reset_vendor_globals(void) {
    src = NULL;
    rodata = NULL; rodata_sz = 0; rodata_cap = 0;
    token = 0; num_val = 0; line = 1; token_cnt = 0;
    str_len = 0;
    code_data = NULL; code_size = 0; code_cap = 0;
    name_buf = NULL; name_sz = 0; name_cap = 0;
    n_vars = 0; locals = 0; esp = 0; expr_type = 0;
    n_globals = 0; bss_size = 0; n_funcs = 0;
    n_lits = 0; n_patches = 0;
}


xcc_result_t xcc_compile(const char *src_buf, int src_len) {
    xcc_result_t r;
    memset(&r, 0, sizeof(r));

    xcc_in_src  = src_buf;
    xcc_in_size = src_len;
    xcc_in_pos  = 0;

    xcc_out_pos  = 0;
    xcc_out_size = 0;
    if (!xcc_out_grow_to(8192)) {
        r.err = "xcc: out of memory (output buffer)";
        r.err_len = (int)strlen(r.err);
        r.exit_code = 1;
        return r;
    }

    xcc_err_buf[0] = 0;
    xcc_err_len = 0;

    xcc_reset_vendor_globals();
    xcc_exit_code  = 0;
    xcc_exit_taken = 0;

    char prog[]   = "xcc";
    char inn[]    = "input.c";
    char dashO[]  = "-o";
    char outn[]   = "output.elf";
    char *argv[]  = { prog, inn, dashO, outn, NULL };

    if (setjmp(xcc_exit_jmp) == 0) {
        int ret = xcc_main_real(4, argv);
        r.exit_code = ret;
    } else {
        r.exit_code = xcc_exit_code;
    }

    if (r.exit_code == 0 && xcc_out_size > 0) {
        r.elf      = (const uint8_t *)xcc_out_buf;
        r.elf_size = xcc_out_size;
    }
    r.err     = xcc_err_buf;
    r.err_len = xcc_err_len;
    return r;
}


void xcc_free_output(void) {
    if (xcc_out_buf) {
        free(xcc_out_buf);
        xcc_out_buf = NULL;
        xcc_out_cap = 0;
        xcc_out_size = 0;
        xcc_out_pos = 0;
    }
}
