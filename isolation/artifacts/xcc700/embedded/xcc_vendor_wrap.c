/* xcc_vendor_wrap.c — pulls in the verbatim vendor compiler with all
 * libc / syscall references rewired to xcc_* shim functions defined
 * in xcc_shim.c. This translation unit deliberately does NOT include
 * stdio/stdlib/string — the vendor declares its own (relaxed) libc
 * prototypes at the top of xcc700.c, and we don't want the system
 * headers to fight them (e.g. real strtol returns long, not int).
 *
 * Macro substitution rewrites both the vendor's prototypes (line 4-11
 * of xcc700.c) and every call site, so they line up with the xcc_*
 * declarations below. The shim definitions live in xcc_shim.c.
 */

/* ── forward-declare the shim symbols using the vendor's int types ── */
int  xcc_printf(char *fmt, ...);
void xcc_exit(int status);
int  xcc_clock(void);
int  xcc_open(char *pathname, int flags, int mode);
int  xcc_close(int fd);
int  xcc_read(int fd, void *buf, int count);
int  xcc_write(int fd, void *buf, int count);
int  xcc_lseek(int fd, int offset, int whence);


/* ── rewire everything the vendor uses ──────────────────────────── */
#define open    xcc_open
#define close   xcc_close
#define read    xcc_read
#define write   xcc_write
#define lseek   xcc_lseek
#define printf  xcc_printf
#define exit    xcc_exit
#define clock   xcc_clock
#define main    xcc_main_real

/* The vendor's enum already provides O_RDONLY/O_WRONLY/O_CREAT/O_TRUNC/
 * SEEK_SET/SEEK_END as integer constants — DO NOT macro-define them
 * here, that would collide with the enum members. xcc_open / xcc_lseek
 * just ignore the values anyway since I/O is in-memory. */

#include "../vendor/xcc700.c"

#undef main
#undef open
#undef close
#undef read
#undef write
#undef lseek
#undef printf
#undef exit
#undef clock
