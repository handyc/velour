/* app0_greeter.c — workspace App 0: ANSI greeting.
 *
 * No-libc, static, x86_64 Linux ELF.  Designed to compile to <4096
 * bytes in -Os.  The four `SLOT_*` arrays below carry an 8-byte magic
 * prefix (CAFE BABE 00 00 00 0N) so spoeqi.workspace.builder can find
 * and patch them deterministically — at runtime we skip the prefix
 * and write the data straight to stdout.
 *
 * Build:
 *     make -C spoeqi/workspace/templates app0_greeter
 */

typedef long ssize_t;
typedef unsigned long size_t;

#define SYS_write      1
#define SYS_exit_group 231

static long sys3(long n, long a, long b, long c) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a), "S"(b), "d"(c)
                      : "rcx", "r11", "memory");
    return r;
}

static void writen(const char *p, size_t n) {
    sys3(SYS_write, 1, (long)p, (long)n);
}

/* Slot magic: CA FE BA BE 00 00 00 NN — `volatile` keeps the slot from
 * being constant-folded away by the optimiser; `used` keeps `--gc-
 * sections` from stripping it; explicit section keeps the relative
 * order predictable in the binary. */
#define SLOT(name, id, n) \
    __attribute__((used, section(".rodata.workspace_slots"))) \
    static const volatile unsigned char name[8 + n] = \
        { 0xCA, 0xFE, 0xBA, 0xBE, 0x00, 0x00, 0x00, id,

SLOT(SLOT_COLOR,    0x01, 16)
        '\033','[','1',';','3','6',';','4','4','m',' ',' ',' ',' ',' ',' '
};

SLOT(SLOT_GREETING, 0x02, 32)
        'h','e','l','l','o',' ','f','r','o','m',' ','a','n',' ','u','n','s','e','e','d','e','d',' ','p','a','c','t',' ',' ',' ',' ',' '
};

SLOT(SLOT_PACT_ID,  0x03, 24)
        'p','a','c','t','=','?','?','?','?','?','?','?','?',' ','t','i','c','k','=','0','0','0','0','0'
};

SLOT(SLOT_FOOTER,   0x04, 16)
        '~',' ','b','y','t','e','-','i','d','e','n','t','i','c','a','l'
};

#define RESET "\033[0m"

int _start(void) {
    /* Skip the 8-byte magic prefix on each slot when writing. */
    writen((const char *)SLOT_COLOR    + 8, 16);
    writen((const char *)SLOT_GREETING + 8, 32);
    writen(" (", 2);
    writen((const char *)SLOT_PACT_ID  + 8, 24);
    writen(") ", 2);
    writen((const char *)SLOT_FOOTER   + 8, 16);
    writen(RESET "\n", sizeof(RESET "\n") - 1);
    sys3(SYS_exit_group, 0, 0, 0);
    return 0;
}
