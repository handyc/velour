/* soulvote.c — N-agent ensemble orchestrator for officesoulmin.
 *
 * Spawns N child processes, each running ./officesoulmin with a
 * different --seed and a shared --temp, --max, prompt.  Reads each
 * child's --ids stdout, votes per token position (plurality with
 * smallest-ID tiebreak), writes the consensus token sequence
 * decoded to stdout.
 *
 * No namespace isolation here — children are plain forks.  The
 * jail-trampoline path (each child in its own user/pid/net ns +
 * seccomp) is a separate fork once this proves out the orchestration.
 *
 * Build (matches officesoulmin's flags + #includes soul_data.h
 * just for the vocab tables — the model weights are inert here):
 *   cc -DTINY -std=c99 -Os -Wall -Wextra \
 *      -fno-stack-protector -fno-asynchronous-unwind-tables \
 *      -fno-unwind-tables -fno-builtin -ffreestanding \
 *      -ffunction-sections -fdata-sections \
 *      -nostdlib -nostartfiles -static \
 *      -Wl,--gc-sections -Wl,--build-id=none \
 *      -Wl,-z,noseparate-code -Wl,-z,common-page-size=512 -s \
 *      -o soulvote soulvote.c
 *
 * Use:
 *   echo "the cat" | ./soulvote --n 64 --temp 256 --max 16
 *   ./soulvote --n 8 "the cat sat"
 *
 * Flags:
 *   --n N      number of agents (default 8, max 256)
 *   --temp Q   temperature passed to each child (default 256)
 *   --max M    max tokens per agent (default 24, max 63)
 *   --raw      also dump each agent's raw IDs to stderr (debug)
 *
 * Output: decoded consensus tokens to stdout, no trailing newline.
 * Exit: 0 if at least one child produced any output, else 1. */

#include "soul_data.h"


/* ── syscalls ──────────────────────────────────────────── */
typedef long  ssize_t;
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

#define SYS_read       0
#define SYS_write      1
#define SYS_close      3
#define SYS_pipe       22
#define SYS_dup2       33
#define SYS_clone      56
#define SYS_execve     59
#define SYS_wait4      61
#define SYS_exit_group 231

#define SIGCHLD 17

#define rd(f, p, n)  sys3(SYS_read,  f, (long)(p), (long)(n))
#define wr(f, p, n)  sys3(SYS_write, f, (long)(p), (long)(n))
#define cl(f)        sys3(SYS_close, f, 0, 0)


/* ── string + memory helpers ───────────────────────────── */
static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }
static int scmp(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return (unsigned char)*a - (unsigned char)*b;
}
static void *mcpy(void *d, const void *s, size_t n) {
    char *dd = (char *)d; const char *ss = (const char *)s;
    while (n--) *dd++ = *ss++;
    return d;
}
static int atoi_(const char *s) {
    int sign = 1, n = 0;
    while (*s == ' ' || *s == '\t') s++;
    if (*s == '-') { sign = -1; s++; }
    else if (*s == '+') s++;
    while (*s >= '0' && *s <= '9') { n = n * 10 + (*s - '0'); s++; }
    return sign * n;
}
static int utoa(unsigned u, char *out) {
    char t[12]; int n = 0;
    if (!u) t[n++] = '0';
    while (u) { t[n++] = '0' + u % 10; u /= 10; }
    for (int i = 0; i < n; i++) out[i] = t[n - 1 - i];
    return n;
}


/* ── fork+exec one child reading from pipe[1] → fd 1 ──── */
static long do_clone_simple(void) {
    /* clone(SIGCHLD) — equivalent to fork() but via the raw syscall. */
    return sys4(SYS_clone, SIGCHLD, 0, 0, 0);
}

/* Pipe buffers used by parent.  Children inherit the kernel
 * resources via clone().  Each child gets its own pipe pair. */
#define MAX_AGENTS 256
#define MAX_TOKENS 63
#define VS_LIMIT   128

#define IDS_BUF_BYTES 1024            /* ample for 63 ids × 4 chars */
static char child_buf[MAX_AGENTS][IDS_BUF_BYTES];
static int  child_buf_len[MAX_AGENTS];
static int  child_fd      [MAX_AGENTS];
static int  child_pid     [MAX_AGENTS];

static int spawn_one(int idx, int seed, int temp_q8, int max_new,
                     const char *prompt, char **envp) {
    int pfd[2];
    if (sys1(SYS_pipe, (long)pfd) < 0) return -1;

    long pid = do_clone_simple();
    if (pid < 0) {
        cl(pfd[0]); cl(pfd[1]);
        return -1;
    }
    if (pid == 0) {
        /* Child: redirect stdout to pipe write end, exec officesoulmin. */
        sys3(SYS_dup2, pfd[1], 1, 0);
        cl(pfd[0]);
        cl(pfd[1]);
        /* Build argv on the stack — small, fixed layout. */
        char seed_s[12], temp_s[12], max_s[12];
        seed_s[utoa((unsigned)seed, seed_s)] = 0;
        temp_s[utoa((unsigned)temp_q8, temp_s)] = 0;
        max_s [utoa((unsigned)max_new, max_s)] = 0;
        char *xargv[16];
        int xn = 0;
        xargv[xn++] = (char *)"officesoulmin";
        xargv[xn++] = (char *)"--seed"; xargv[xn++] = seed_s;
        xargv[xn++] = (char *)"--temp"; xargv[xn++] = temp_s;
        xargv[xn++] = (char *)"--max";  xargv[xn++] = max_s;
        xargv[xn++] = (char *)"--ids";
        if (prompt && *prompt) xargv[xn++] = (char *)prompt;
        xargv[xn] = 0;
        sys3(SYS_execve, (long)"./officesoulmin", (long)xargv, (long)envp);
        /* If execve returns, something failed — write a marker to
         * stdout (the pipe) so the parent sees an empty/garbage
         * line and skips this agent. */
        sys3(SYS_exit_group, 127, 0, 0);
    }
    /* Parent: keep read end, close write end, record state. */
    cl(pfd[1]);
    child_fd [idx] = pfd[0];
    child_pid[idx] = (int)pid;
    return 0;
}


/* Parse a child's "id id id ...\n" line into ids[].  Returns count;
 * stops at newline or buffer end.  Tolerates trailing whitespace. */
static int parse_ids(const char *buf, int blen, int *ids, int cap) {
    int n = 0;
    int i = 0;
    while (i < blen && n < cap) {
        while (i < blen && (buf[i] == ' ' || buf[i] == '\t'
                         || buf[i] == '\n' || buf[i] == '\r')) i++;
        if (i >= blen) break;
        int v = 0;
        int started = 0;
        while (i < blen && buf[i] >= '0' && buf[i] <= '9') {
            v = v * 10 + (buf[i] - '0');
            started = 1;
            i++;
        }
        if (!started) break;
        ids[n++] = v;
    }
    return n;
}


/* ── main ──────────────────────────────────────────────── */
static char prompt_buf[4096];

int main_c(int argc, char **argv, char **envp) {
    int n_agents = 8;
    int temp_q8  = 256;
    int max_new  = 24;
    int dump_raw = 0;
    const char *argv_prompt = 0;
    for (int i = 1; i < argc; i++) {
        if (scmp(argv[i], "--n") == 0 && i + 1 < argc) {
            n_agents = atoi_(argv[++i]);
        } else if (scmp(argv[i], "--temp") == 0 && i + 1 < argc) {
            temp_q8 = atoi_(argv[++i]);
        } else if (scmp(argv[i], "--max") == 0 && i + 1 < argc) {
            max_new = atoi_(argv[++i]);
        } else if (scmp(argv[i], "--raw") == 0) {
            dump_raw = 1;
        } else if (scmp(argv[i], "--help") == 0
                || scmp(argv[i], "-h") == 0) {
            static const char H[] =
                "soulvote — N-agent ensemble over officesoulmin\n"
                "  echo 'prompt' | ./soulvote --n 64 --temp 256\n"
                "  ./soulvote [--n N] [--temp Q] [--max M] [--raw] [PROMPT]\n"
                "    --n N      agents (default 8, max 256)\n"
                "    --temp Q   temperature for each agent (default 256)\n"
                "    --max M    max tokens per agent (default 24, max 63)\n"
                "    --raw      also dump per-agent IDs to stderr\n"
                "  output: decoded consensus tokens, no trailing newline\n";
            wr(1, H, sizeof H - 1);
            return 0;
        } else if (argv[i][0] != '-') {
            argv_prompt = argv[i];
        }
    }
    if (n_agents < 1) n_agents = 1;
    if (n_agents > MAX_AGENTS) n_agents = MAX_AGENTS;
    if (max_new  < 1)  max_new = 1;
    if (max_new  > MAX_TOKENS) max_new = MAX_TOKENS;

    /* Acquire prompt: argv > stdin. */
    int plen = 0;
    if (argv_prompt) {
        int slen_p = slen(argv_prompt);
        if (slen_p > (int)sizeof prompt_buf - 1) slen_p = sizeof prompt_buf - 1;
        mcpy(prompt_buf, argv_prompt, slen_p);
        plen = slen_p;
    } else {
        long n;
        while (plen < (int)sizeof prompt_buf - 1
            && (n = rd(0, prompt_buf + plen,
                       sizeof prompt_buf - 1 - plen)) > 0) {
            plen += (int)n;
        }
    }
    while (plen > 0 && (prompt_buf[plen - 1] == '\n'
                     || prompt_buf[plen - 1] == '\r')) plen--;
    prompt_buf[plen] = 0;

    /* Spawn N agents.  Seed N+1 so seed 0 doesn't collapse to the
     * default mix. */
    int spawned = 0;
    for (int i = 0; i < n_agents; i++) {
        child_fd[i] = -1;
        child_buf_len[i] = 0;
        if (spawn_one(i, i + 1, temp_q8, max_new,
                      plen ? prompt_buf : 0, envp) == 0) {
            spawned++;
        }
    }
    if (spawned == 0) {
        wr(2, "soulvote: no agents spawned\n", 28);
        return 1;
    }

    /* Drain each child's stdout to its buffer.  Simple sequential
     * read; the children are independent so order of draining
     * doesn't matter.  In practice the children block until their
     * pipe drains which can serialise things — for N≤64 with each
     * child outputting <500 bytes, no concern. */
    for (int i = 0; i < n_agents; i++) {
        if (child_fd[i] < 0) continue;
        long m;
        while (child_buf_len[i] < IDS_BUF_BYTES - 1
            && (m = rd(child_fd[i],
                       child_buf[i] + child_buf_len[i],
                       IDS_BUF_BYTES - 1 - child_buf_len[i])) > 0) {
            child_buf_len[i] += (int)m;
        }
        cl(child_fd[i]);
    }

    /* Reap. */
    for (int i = 0; i < n_agents; i++) {
        if (child_pid[i] <= 0) continue;
        int st = 0;
        sys4(SYS_wait4, child_pid[i], (long)&st, 0, 0);
    }

    /* Optional debug dump. */
    if (dump_raw) {
        for (int i = 0; i < n_agents; i++) {
            if (child_buf_len[i] == 0) continue;
            char hdr[24]; int hl = 0;
            hl  = utoa((unsigned)i, hdr);
            hdr[hl++] = ':'; hdr[hl++] = ' ';
            wr(2, hdr, hl);
            wr(2, child_buf[i], child_buf_len[i]);
            if (child_buf[i][child_buf_len[i] - 1] != '\n')
                wr(2, "\n", 1);
        }
    }

    /* Parse each agent's IDs into a (n_agents × max_new) matrix.
     * Missing positions are -1 (skipped from voting). */
    int agent_ids[MAX_AGENTS][MAX_TOKENS];
    int agent_len[MAX_AGENTS];
    for (int i = 0; i < n_agents; i++) {
        agent_len[i] = parse_ids(child_buf[i], child_buf_len[i],
                                 agent_ids[i], MAX_TOKENS);
        for (int j = agent_len[i]; j < MAX_TOKENS; j++)
            agent_ids[i][j] = -1;
    }

    /* Per-position plurality vote.  Tiebreak: smallest token ID. */
    int consensus[MAX_TOKENS];
    int consensus_len = 0;
    for (int pos = 0; pos < max_new; pos++) {
        int counts[VS_LIMIT];
        for (int v = 0; v < VS_LIMIT; v++) counts[v] = 0;
        int total = 0;
        for (int i = 0; i < n_agents; i++) {
            int id = agent_ids[i][pos];
            if (id >= 0 && id < VS_LIMIT) {
                counts[id]++;
                total++;
            }
        }
        if (total == 0) break;     /* all agents stopped at this pos */
        int best = -1, best_c = 0;
        for (int v = 0; v < VS_LIMIT; v++) {
            if (counts[v] > best_c) { best_c = counts[v]; best = v; }
        }
        if (best < 0) break;
        consensus[consensus_len++] = best;
    }

    /* Decode consensus to stdout. */
    for (int i = 0; i < consensus_len; i++) {
        int id = consensus[i];
        if (id < 0 || id >= 128) continue;
        if (id == 0 || id == 1 || id == 2 || id == 3) continue; /* PAD/SEP/UNK/END */
        wr(1, (const char *)(VOCAB_STR_BLOB + VOCAB_OFFSETS[id]),
           VOCAB_LEN_TBL[id]);
    }
    return 0;
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
