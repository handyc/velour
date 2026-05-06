/* jail.c — namespace launcher for office7 garden previews.
 *
 * Spawns office7 inside a fresh user/pid/net/mount/uts namespace
 * with a one-file chroot that contains only the office7 binary.
 * No libc, raw syscalls only — matches the office suite's house
 * style.
 *
 * Usage: jail OFFICE7_PATH GENOME_HEX
 *   OFFICE7_PATH = path to the office7 binary on the host
 *   GENOME_HEX   = 32 lowercase hex chars = 16 bytes of struct Genome
 *
 * The child execve's office7 with `preview-genome <hex>` so it
 * lands in the in-process render path.  No need for term_raw inside
 * the child — fd 0/1 are inherited from the parent which has already
 * put the tty in raw mode.
 *
 * Isolation provided:
 *   user-ns:   child is root-in-NS, mapped to host's real uid (no privilege)
 *   pid-ns:    child is PID 1, can't see host processes
 *   net-ns:    no network interfaces at all (not even loopback)
 *   mount-ns:  any mounts the child does don't touch the host
 *   uts-ns:    hostname/domainname isolated (cosmetic)
 *   chroot:    only /office7 is visible inside the jail
 *
 * Falls through to a clear error message + non-zero exit if the
 * kernel doesn't allow unprivileged user-ns creation.  The caller
 * (office7's garden_preview) treats that as a signal to fall back
 * to the in-process preview render so the feature degrades.
 */

typedef long ssize_t;
typedef unsigned long size_t;

static long sys1(long n, long a) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a)
                      : "rcx", "r11", "memory");
    return r;
}
static long sys3(long n, long a, long b, long c) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a), "S"(b), "d"(c)
                      : "rcx", "r11", "memory");
    return r;
}
static long sys4(long n, long a, long b, long c, long d) {
    long r;
    register long r10 __asm__("r10") = d;
    __asm__ volatile ("syscall" : "=a"(r)
                      : "0"(n), "D"(a), "S"(b), "d"(c), "r"(r10)
                      : "rcx", "r11", "memory");
    return r;
}
static long sys5(long n, long a, long b, long c, long d, long e) {
    long r;
    register long r10 __asm__("r10") = d;
    register long r8  __asm__("r8")  = e;
    __asm__ volatile ("syscall" : "=a"(r)
                      : "0"(n), "D"(a), "S"(b), "d"(c), "r"(r10), "r"(r8)
                      : "rcx", "r11", "memory");
    return r;
}

#define SYS_read       0
#define SYS_write      1
#define SYS_open       2
#define SYS_close      3
#define SYS_getpid     39
#define SYS_clone      56
#define SYS_execve     59
#define SYS_wait4      61
#define SYS_chdir      80
#define SYS_mkdir      83
#define SYS_rmdir      84
#define SYS_unlink     87
#define SYS_chmod      90
#define SYS_getuid     102
#define SYS_getgid     104
#define SYS_chroot     161
#define SYS_prctl      157
#define SYS_exit_group 231

#define O_RDONLY 0
#define O_WRONLY 1
#define O_CREAT  64
#define O_TRUNC  512

#define CLONE_NEWNS    0x00020000
#define CLONE_NEWUTS   0x04000000
#define CLONE_NEWUSER  0x10000000
#define CLONE_NEWPID   0x20000000
#define CLONE_NEWNET   0x40000000
#define SIGCHLD        17

#define wr(f, p, n)  sys3(SYS_write, f, (long)(p), (long)(n))
#define rd(f, p, n)  sys3(SYS_read,  f, (long)(p), (long)(n))
#define op(p, fl, m) sys3(SYS_open,  (long)(p), (long)(fl), (long)(m))
#define cl(f)        sys3(SYS_close, f, 0, 0)


static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }

static int sapp(char *dst, int off, const char *s) {
    int n = slen(s);
    for (int i = 0; i < n; i++) dst[off + i] = s[i];
    return off + n;
}

static int utoa(unsigned long u, char *out) {
    char t[24]; int n = 0;
    if (!u) t[n++] = '0';
    while (u) { t[n++] = '0' + (char)(u % 10); u /= 10; }
    for (int i = 0; i < n; i++) out[i] = t[n - 1 - i];
    return n;
}

static int err(const char *msg) {
    wr(2, "jail: ", 6);
    wr(2, msg, slen(msg));
    wr(2, "\n", 1);
    return 1;
}

/* Copy src → dst in 4 KB chunks.  dst is created mode 0755 and
 * chmod'd again afterwards in case open()'s mode is filtered by a
 * non-zero umask. */
static int copy_file(const char *src, const char *dst) {
    int s = (int)op(src, O_RDONLY, 0);
    if (s < 0) return -1;
    int d = (int)op(dst, O_WRONLY | O_CREAT | O_TRUNC, 0755);
    if (d < 0) { cl(s); return -1; }
    char buf[4096];
    long n;
    while ((n = rd(s, buf, sizeof buf)) > 0) {
        long off = 0;
        while (off < n) {
            long k = wr(d, buf + off, n - off);
            if (k <= 0) { cl(s); cl(d); return -1; }
            off += k;
        }
    }
    cl(s); cl(d);
    sys3(SYS_chmod, (long)dst, 0755, 0);
    return 0;
}

/* Write "0 <id> 1\n" to /proc/self/uid_map or gid_map.  Together
 * with deny_setgroups() this maps the child's uid/gid 0 inside the
 * userns to the parent's real uid/gid on the host. */
static int write_id_map(const char *path, long id) {
    int fd = (int)op(path, O_WRONLY, 0);
    if (fd < 0) return -1;
    char line[64];
    int p = sapp(line, 0, "0 ");
    p += utoa((unsigned long)id, line + p);
    p = sapp(line, p, " 1\n");
    long w = wr(fd, line, p);
    cl(fd);
    return w == p ? 0 : -1;
}

/* Required since 3.19: setgroups must be "deny" before an
 * unprivileged process can write its own gid_map. */
static int deny_setgroups(void) {
    int fd = (int)op("/proc/self/setgroups", O_WRONLY, 0);
    if (fd < 0) return -1;
    long w = wr(fd, "deny\n", 5);
    cl(fd);
    return w == 5 ? 0 : -1;
}

/* clone() with NULL stack — fork-like CoW semantics, plus all the
 * namespace flags in one shot.  On x86_64 the syscall arg order is
 * (flags, stack, ptid, tls, ctid) — different from glibc's wrapper. */
static long do_clone(unsigned long flags) {
    return sys5(SYS_clone, (long)flags, 0, 0, 0, 0);
}


/* ── seccomp BPF allowlists ───────────────────────────────────────
 *
 * Two filters: a tight one for `preview-genome` (no file I/O, no
 * fork) and a loose one that covers the full office9 suite (open,
 * close, lseek, getdents64, time, fork, wait4) so V mode can
 * actually use notepad / sheet / files / etc. inside the jail.
 *
 * The transition into office9 also needs execve — the filter is
 * installed *before* execve, so the execve syscall itself must be
 * allowed in both filters.
 *
 * Disallowed syscalls are answered with SECCOMP_RET_KILL_PROCESS so
 * a violation shows up as a clear SIGSYS rather than a quietly-failing
 * call.  If the kernel doesn't have CONFIG_SECCOMP_FILTER, install
 * fails and the launcher continues — namespaces + chroot still apply.
 */

struct sock_filter { unsigned short code; unsigned char jt, jf; unsigned int k; };
struct sock_fprog  { unsigned short len;  struct sock_filter *filter; };

#define BPF_LD_W_ABS  0x20    /* load 32-bit word at absolute offset */
#define BPF_JMP_JEQ_K 0x15
#define BPF_RET_K     0x06

#define AUDIT_ARCH_X86_64        0xC000003E
#define SECCOMP_RET_ALLOW        0x7FFF0000u
#define SECCOMP_RET_KILL_PROCESS 0x80000000u
#define SECCOMP_MODE_FILTER      2
#define PR_SET_NO_NEW_PRIVS      38
#define PR_SET_SECCOMP           22

#define SYS_rt_sigreturn 15
#define SYS_ioctl        16
#define SYS_open          2
#define SYS_close         3
#define SYS_lseek         8
#define SYS_fork         57
#define SYS_wait4_v      61
#define SYS_time        201
#define SYS_getdents64  217

/* Tight: preview-genome uses read/write/ioctl/exit_group only.
 * execve + rt_sigreturn rounded out for the jail-→office handoff
 * and any signal that arrives mid-render. */
static struct sock_filter seccomp_preview[] = {
    { BPF_LD_W_ABS,  0, 0, 4 },                            /* [0] A=arch */
    { BPF_JMP_JEQ_K, 0, 6, AUDIT_ARCH_X86_64 },            /* [1] arch != x86_64 → kill */
    { BPF_LD_W_ABS,  0, 0, 0 },                            /* [2] A=nr */
    { BPF_JMP_JEQ_K, 5, 0, SYS_write        },             /* [3] → allow */
    { BPF_JMP_JEQ_K, 4, 0, SYS_read         },
    { BPF_JMP_JEQ_K, 3, 0, SYS_ioctl        },
    { BPF_JMP_JEQ_K, 2, 0, SYS_rt_sigreturn },
    { BPF_JMP_JEQ_K, 1, 0, SYS_execve       },
    { BPF_JMP_JEQ_K, 0, 1, SYS_exit_group   },             /* [8] jf=1 → kill */
    { BPF_RET_K,     0, 0, SECCOMP_RET_ALLOW         },    /* [9] */
    { BPF_RET_K,     0, 0, SECCOMP_RET_KILL_PROCESS  },    /* [10] */
};

/* Loose: union of every syscall office9's apps issue.  Order picks
 * the most-frequent calls (read/write) first so the filter exits
 * the chain quickly on the hot path. */
static struct sock_filter seccomp_full[] = {
    { BPF_LD_W_ABS,  0, 0, 4 },                            /* [0] arch */
    { BPF_JMP_JEQ_K, 0,13, AUDIT_ARCH_X86_64 },            /* [1] arch != x86_64 → [15] kill */
    { BPF_LD_W_ABS,  0, 0, 0 },                            /* [2] nr */
    { BPF_JMP_JEQ_K,12, 0, SYS_write        },             /* [3] → allow [16] */
    { BPF_JMP_JEQ_K,11, 0, SYS_read         },
    { BPF_JMP_JEQ_K,10, 0, SYS_ioctl        },
    { BPF_JMP_JEQ_K, 9, 0, SYS_open         },
    { BPF_JMP_JEQ_K, 8, 0, SYS_close        },
    { BPF_JMP_JEQ_K, 7, 0, SYS_lseek        },
    { BPF_JMP_JEQ_K, 6, 0, SYS_getdents64   },
    { BPF_JMP_JEQ_K, 5, 0, SYS_time         },
    { BPF_JMP_JEQ_K, 4, 0, SYS_fork         },
    { BPF_JMP_JEQ_K, 3, 0, SYS_execve       },
    { BPF_JMP_JEQ_K, 2, 0, SYS_wait4_v      },
    { BPF_JMP_JEQ_K, 1, 0, SYS_rt_sigreturn },
    { BPF_JMP_JEQ_K, 0, 1, SYS_exit_group   },             /* [15] jf=1 → [17] kill */
    { BPF_RET_K,     0, 0, SECCOMP_RET_ALLOW         },    /* [16] */
    { BPF_RET_K,     0, 0, SECCOMP_RET_KILL_PROCESS  },    /* [17] */
};

static int install_seccomp(struct sock_filter *filter, unsigned short n) {
    /* Required for unprivileged seccomp install: ensures setuid
     * binaries can't gain privileges past the filter. */
    if (sys5(SYS_prctl, PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0)
        return -1;
    struct sock_fprog prog = { .len = n, .filter = filter };
    if (sys5(SYS_prctl, PR_SET_SECCOMP, SECCOMP_MODE_FILTER,
             (long)&prog, 0, 0) < 0)
        return -1;
    return 0;
}


int main_c(int argc, char **argv, char **envp) {
    if (argc < 3) {
        wr(2, "usage: jail OFFICE_PATH SUBCOMMAND [ARGS...]\n"
              "       jail OFFICE_PATH HEX  (legacy: preview-genome)\n", 99);
        return 2;
    }
    const char *src = argv[1];

    /* Argv to feed the jailed office.  Legacy 3-arg form
     * `jail PATH HEX` is rewritten to `jail PATH preview-genome HEX`
     * so office7 keeps working unchanged. */
    char *xargs[16];
    int xn = 0;
    xargs[xn++] = (char *)"office";
    if (argc == 3) {
        xargs[xn++] = (char *)"preview-genome";
        xargs[xn++] = argv[2];
    } else {
        for (int i = 2; i < argc && xn < 15; i++)
            xargs[xn++] = argv[i];
    }
    xargs[xn] = 0;

    /* Per-invocation jail dir under /tmp.  Parent's pid keeps it
     * unique enough; we unlink + rmdir on exit so collisions only
     * matter if two jails launch in the same microsecond. */
    long pid = sys1(SYS_getpid, 0);
    char dir[64];
    int p = sapp(dir, 0, "/tmp/o7jail.");
    p += utoa((unsigned long)pid, dir + p);
    dir[p] = 0;

    if (sys3(SYS_mkdir, (long)dir, 0700, 0) < 0)
        return err("mkdir failed");

    char dst[96];
    int q = sapp(dst, 0, dir);
    q = sapp(dst, q, "/office7");
    dst[q] = 0;
    if (copy_file(src, dst) < 0) {
        sys3(SYS_rmdir, (long)dir, 0, 0);
        return err("copy failed (is OFFICE7_PATH correct?)");
    }

    long uid = sys1(SYS_getuid, 0);
    long gid = sys1(SYS_getgid, 0);

    unsigned long flags = CLONE_NEWUSER | CLONE_NEWPID | CLONE_NEWNS
                        | CLONE_NEWNET  | CLONE_NEWUTS | SIGCHLD;
    long child = do_clone(flags);
    if (child < 0) {
        sys3(SYS_unlink, (long)dst, 0, 0);
        sys3(SYS_rmdir,  (long)dir, 0, 0);
        return err("clone(CLONE_NEW*) failed — kernel without "
                   "unprivileged userns?");
    }

    if (child == 0) {
        /* In the freshly-cloned child.  Until uid_map is written
         * we have the overflow uid (nobody) and no caps; once the
         * mapping is in place we are root *inside the namespace*
         * and can chroot.  setgroups "deny" must come first or the
         * gid_map write is rejected by the kernel. */
        deny_setgroups();
        write_id_map("/proc/self/uid_map", uid);
        write_id_map("/proc/self/gid_map", gid);

        if (sys1(SYS_chroot, (long)dir) < 0) {
            wr(2, "jail/child: chroot failed\n", 26);
            sys3(SYS_exit_group, 1, 0, 0);
        }
        sys1(SYS_chdir, (long)"/");

        /* Pick the right seccomp filter for this subcommand.  Tight
         * for preview-genome (no file I/O); full for view-genome and
         * anything else (suite needs open/close/lseek/getdents64/
         * time/fork/wait4 to actually function).  Failure here is
         * non-fatal — namespaces + chroot are already a real jail. */
        int is_preview = xargs[1] && xargs[1][0] == 'p' &&
                         xargs[1][1] == 'r';   /* preview-genome */
        if (is_preview) {
            install_seccomp(seccomp_preview,
                            sizeof seccomp_preview / sizeof seccomp_preview[0]);
        } else {
            install_seccomp(seccomp_full,
                            sizeof seccomp_full / sizeof seccomp_full[0]);
        }

        sys3(SYS_execve, (long)"/office7", (long)xargs, (long)envp);
        wr(2, "jail/child: execve failed\n", 26);
        sys3(SYS_exit_group, 127, 0, 0);
    }

    /* Parent: wait for the child to render+read, then tear the jail
     * dir down so /tmp doesn't accumulate empty shells. */
    int st = 0;
    sys4(SYS_wait4, child, (long)&st, 0, 0);

    sys3(SYS_unlink, (long)dst, 0, 0);
    sys3(SYS_rmdir,  (long)dir, 0, 0);

    int sig = st & 0x7f;
    int ec  = (st >> 8) & 0xff;
    return sig ? 1 : ec;
}


__asm__ (
    ".global _start\n"
    "_start:\n"
    "    movq (%rsp), %rdi\n"
    "    leaq 8(%rsp), %rsi\n"
    "    leaq 16(%rsp,%rdi,8), %rdx\n"
    "    andq $-16, %rsp\n"
    "    call main_c\n"
    "    movl %eax, %edi\n"
    "    movl $231, %eax\n"
    "    syscall\n"
);
