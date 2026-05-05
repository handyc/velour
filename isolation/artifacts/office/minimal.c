/* minimal.c — the smallest no-libc Linux x86_64 program built with
 * the same flags as office.c.  officelab uses this as the baseline
 * "Linux ELF + raw _start + syscall stub" overhead so feature-level
 * byte attribution can subtract OS tax from useful code.
 *
 * It does nothing except call exit_group(0). */

static long sys3(long n, long a, long b, long c) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a), "S"(b), "d"(c)
                      : "rcx", "r11", "memory");
    return r;
}
#define SYS_exit_group 231

int main_c(int argc, char **argv) {
    (void)argc; (void)argv;
    return 0;
}

__asm__ (
    ".global _start\n"
    "_start:\n"
    "    movq (%rsp), %rdi\n"
    "    leaq 8(%rsp), %rsi\n"
    "    andq $-16, %rsp\n"
    "    call main_c\n"
    "    movl %eax, %edi\n"
    "    movl $231, %eax\n"
    "    syscall\n"
);
