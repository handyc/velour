/* officemoe.c — Mixture-of-Experts dispatcher with two routing modes.
 *
 * Reads a prompt from stdin (or argv), picks one of four domain
 * specialists, and execve's the matching officesoulflt_* binary
 * with the prompt + any pass-through flags.  Specialist inherits
 * stdin/stdout/stderr — officemoe is a router, not a wrapper.
 *
 * Routing:
 *   Default = best-of-N likelihood.  Forks each specialist in
 *   --score mode, captures their 4-byte IEEE-float scores
 *   (= log P(top1 next token), so higher = more confident on this
 *   prompt), picks the max.  Each forward pass is ~30-100 ms;
 *   four serially is ~0.2 s.
 *
 *   --keyword forces the legacy keyword classifier.
 *   --score-only just prints "name=<f> name=<f> ..." for inspection.
 *
 * Specialists:
 *   chat   — greetings, farewells, identity, locale.
 *   apps   — "what is X" for project apps.
 *   theory — "what is X" for CS concepts.
 *   mood   — "i'm Y" / "my Z" / advice / comfort.
 *
 * Sibling binaries are resolved relative to /proc/self/exe.
 *
 * Build:  cc -Os -nostdlib -fno-builtin -static -o officemoe officemoe.c
 */

typedef long  ssize_t;
typedef unsigned long size_t;
typedef int   pid_t;

static long sys1(long n, long a) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a)
                      : "rcx", "r11", "memory");
    return r;
}
static long sys2(long n, long a, long b) {
    long r;
    __asm__ volatile ("syscall" : "=a"(r) : "0"(n), "D"(a), "S"(b)
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
#define SYS_pipe2      293
#define SYS_dup2       33
#define SYS_clone      56
#define SYS_execve     59
#define SYS_wait4      61
#define SYS_readlink   89
#define SYS_exit_group 231

#define rd(f, p, n)  sys3(SYS_read,  f, (long)(p), (long)(n))
#define wr(f, p, n)  sys3(SYS_write, f, (long)(p), (long)(n))


/* ── string helpers ────────────────────────────────────── */
static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }
static int scmp(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return (unsigned char)*a - (unsigned char)*b;
}
static char tolow(char c) { return (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c; }

static int contains_word(const char *hay, int hlen, const char *needle) {
    int nlen = slen(needle);
    for (int i = 0; i + nlen <= hlen; i++) {
        int eq = 1;
        for (int j = 0; j < nlen; j++) {
            char c = tolow(hay[i + j]);
            if (c != needle[j]) { eq = 0; break; }
        }
        if (!eq) continue;
        char pre  = (i == 0)             ? ' ' : hay[i - 1];
        char post = (i + nlen == hlen)   ? ' ' : hay[i + nlen];
        int pre_alpha  = (pre  >= 'a' && pre  <= 'z')
                      || (pre  >= 'A' && pre  <= 'Z')
                      || (pre  >= '0' && pre  <= '9');
        int post_alpha = (post >= 'a' && post <= 'z')
                      || (post >= 'A' && post <= 'Z')
                      || (post >= '0' && post <= '9');
        if (!pre_alpha && !post_alpha) return 1;
    }
    return 0;
}

static int starts_with(const char *hay, int hlen, const char *prefix) {
    int plen = slen(prefix);
    if (hlen < plen) return 0;
    for (int i = 0; i < plen; i++)
        if (tolow(hay[i]) != prefix[i]) return 0;
    return 1;
}


/* ── keyword classifier (fallback) ─────────────────────── */
static const char *classify_keyword(const char *prompt, int plen) {
    if (starts_with(prompt, plen, "i'm")
     || starts_with(prompt, plen, "i am")
     || starts_with(prompt, plen, "my ")
     || starts_with(prompt, plen, "i found")
     || starts_with(prompt, plen, "i fixed")
     || starts_with(prompt, plen, "tell me something")
     || starts_with(prompt, plen, "give me advice"))
        return "mood";

    int has_what  = contains_word(prompt, plen, "what")
                 || contains_word(prompt, plen, "tell")
                 || contains_word(prompt, plen, "about");

    static const char *apps_kw[] = {
        "velour", "office", "supercell", "xpg", "rpg", "hxhnt",
        "lsys", "coder", "tinydb", "esp", "gary", "mabel",
        "hazel", "terry", 0
    };
    static const char *theory_kw[] = {
        "hex", "ca", "ga", "transformer", "attention", "softmax",
        "rmsnorm", "bpe", "int", 0
    };

    int hit_apps = 0, hit_theory = 0;
    for (int i = 0; apps_kw[i]; i++)
        if (contains_word(prompt, plen, apps_kw[i])) { hit_apps = 1; break; }
    for (int i = 0; theory_kw[i]; i++)
        if (contains_word(prompt, plen, theory_kw[i])) { hit_theory = 1; break; }

    if (hit_apps)   return "apps";
    if (hit_theory) return "theory";
    if (has_what)   return "apps";
    return "chat";
}


/* ── path resolution ───────────────────────────────────── */
static char exe_path[1024];

static int resolve_specialist(const char *kind, char *out, int cap) {
    long n = sys3(SYS_readlink, (long)"/proc/self/exe",
                  (long)exe_path, sizeof exe_path - 1);
    if (n <= 0) return -1;
    exe_path[n] = 0;
    int slash = -1;
    for (int i = 0; i < n; i++) if (exe_path[i] == '/') slash = i;
    if (slash < 0) return -1;
    int dlen = slash + 1;
    static const char prefix[] = "officesoulflt_";
    int pl = (int)sizeof prefix - 1;
    int kl = slen(kind);
    if (dlen + pl + kl + 1 > cap) return -1;
    for (int i = 0; i < dlen; i++) out[i] = exe_path[i];
    for (int i = 0; i < pl;   i++) out[dlen + i] = prefix[i];
    for (int i = 0; i < kl;   i++) out[dlen + pl + i] = kind[i];
    out[dlen + pl + kl] = 0;
    return 0;
}


/* ── invoke one specialist, capturing its stdout ───────── */
/* Forks officesoulflt_<kind> with the given extra-args, reads its
 * stdout into out_buf (cap bytes).  Returns the number of bytes
 * read on success (could be 0), or -1 on failure to spawn.  Used
 * both by score_specialist (to capture the 4-byte float) and by
 * route_via_router (to capture a few text bytes of "apps\n"). */
static int invoke_specialist_capture(const char *kind, const char *prompt,
                                     const char *extra_arg,
                                     char *out_buf, int cap) {
    static char target[1024];
    if (resolve_specialist(kind, target, sizeof target) < 0) return -1;

    int pipefd[2];
    if (sys2(SYS_pipe2, (long)pipefd, 0) < 0) return -1;

    long pid = sys4(SYS_clone, 17 /* SIGCHLD */, 0, 0, 0);
    if (pid < 0) {
        sys1(SYS_close, pipefd[0]);
        sys1(SYS_close, pipefd[1]);
        return -1;
    }
    if (pid == 0) {
        sys1(SYS_close, pipefd[0]);
        sys2(SYS_dup2, pipefd[1], 1);
        sys1(SYS_close, pipefd[1]);
        char *argv2[8];
        int an = 0;
        argv2[an++] = target;
        if (extra_arg) {
            /* extra_arg may be a space-delimited list ("--temp 0 --max 6"). */
            static char tmp[256];
            int tn = 0;
            for (int i = 0; extra_arg[i] && tn < (int)sizeof tmp - 1; i++)
                tmp[tn++] = extra_arg[i];
            tmp[tn] = 0;
            int s = 0;
            for (int i = 0; i <= tn && an < 6; i++) {
                if (tmp[i] == ' ' || tmp[i] == 0) {
                    if (i > s) {
                        tmp[i] = 0;
                        argv2[an++] = tmp + s;
                    }
                    s = i + 1;
                }
            }
        }
        argv2[an++] = (char *)prompt;
        argv2[an]   = 0;
        char *envp[1] = { 0 };
        sys3(SYS_execve, (long)target, (long)argv2, (long)envp);
        sys1(SYS_exit_group, 127);
    }
    sys1(SYS_close, pipefd[1]);
    int got = 0;
    while (got < cap) {
        long n = rd(pipefd[0], out_buf + got, cap - got);
        if (n <= 0) break;
        got += (int)n;
    }
    sys1(SYS_close, pipefd[0]);
    int status = 0;
    sys4(SYS_wait4, pid, (long)&status, 0, 0);
    return got;
}


static int score_specialist(const char *kind, const char *prompt,
                            float *out_score) {
    char buf[8];
    int got = invoke_specialist_capture(kind, prompt, "--score",
                                        buf, sizeof buf);
    if (got != 4) return 0;
    /* IEEE little-endian on x86_64 — copy the 4 bytes as a float. */
    union { char b[4]; float f; } u;
    for (int i = 0; i < 4; i++) u.b[i] = buf[i];
    *out_score = u.f;
    return 1;
}


/* ── route via router-soul ─────────────────────────────── */
/* Forks officesoulflt_router with greedy decoding (--temp 0 --max 6),
 * captures its text output, finds the first occurrence of one of the
 * four kind names.  Returns the kind on success or 0 if no kind name
 * appeared in the output (caller falls back).  One forward pass —
 * ~25-100 ms vs 4× that for best-of-N. */
static const char *route_via_router(const char *prompt) {
    char buf[64];
    int got = invoke_specialist_capture("router", prompt,
                                        "--temp 0 --max 6",
                                        buf, sizeof buf - 1);
    if (got <= 0) return 0;
    buf[got] = 0;
    static const char *KS[4] = { "chat", "apps", "theory", "mood" };
    /* Find first occurrence of any kind name in buf. */
    int best_pos = 9999;
    const char *best = 0;
    for (int k = 0; k < 4; k++) {
        int kl = slen(KS[k]);
        for (int i = 0; i + kl <= got; i++) {
            int eq = 1;
            for (int j = 0; j < kl; j++)
                if (buf[i + j] != KS[k][j]) { eq = 0; break; }
            if (eq && i < best_pos) {
                best_pos = i;
                best = KS[k];
                break;
            }
        }
    }
    return best;
}


/* ── float printer for verbose / --score-only ─────────── */
static int int_to_str(int x, char *out) {
    char tmp[16]; int tn = 0;
    int neg = (x < 0);
    unsigned int u = neg ? (unsigned int)-x : (unsigned int)x;
    if (u == 0) tmp[tn++] = '0';
    while (u) { tmp[tn++] = '0' + (u % 10); u /= 10; }
    int n = 0;
    if (neg) out[n++] = '-';
    while (tn > 0) out[n++] = tmp[--tn];
    return n;
}
static int float_fmt(float f, char *out) {
    /* fixed-point 4 decimals, range ~ [-99, 0]. */
    int n = 0;
    if (f != f) { for (const char *s = "nan"; *s; ) out[n++] = *s++; return n; }
    if (f < 0) { out[n++] = '-'; f = -f; }
    int whole = (int)f;
    float frac = f - (float)whole;
    n += int_to_str(whole, out + n);
    out[n++] = '.';
    int frac_int = (int)(frac * 10000.0f + 0.5f);
    /* zero-pad */
    char fbuf[8]; int fn = 0;
    if (frac_int == 0) fbuf[fn++] = '0';
    else { int t = frac_int; while (t) { fbuf[fn++] = '0' + (t % 10); t /= 10; } }
    while (fn < 4) fbuf[fn++] = '0';
    while (fn > 0) out[n++] = fbuf[--fn];
    return n;
}


/* ── main ──────────────────────────────────────────────── */
static char prompt_buf[4096];

static const char *KINDS[4] = { "chat", "apps", "theory", "mood" };

int main_c(int argc, char **argv) {
    int plen = 0;
    int verbose = 0;
    int use_keyword = 0;
    int use_bofN = 0;
    int score_only = 0;
    int is_prompt_arg[64];
    for (int i = 0; i < 64; i++) is_prompt_arg[i] = 0;
    int n_args = argc < 64 ? argc : 64;

    for (int i = 1; i < n_args; i++) {
        const char *a = argv[i];
        if (scmp(a, "--verbose") == 0 || scmp(a, "-v") == 0) {
            verbose = 1; continue;
        }
        if (scmp(a, "--keyword") == 0) {
            use_keyword = 1; continue;
        }
        if (scmp(a, "--bofN") == 0 || scmp(a, "--bestofn") == 0) {
            use_bofN = 1; continue;
        }
        if (scmp(a, "--score-only") == 0) {
            score_only = 1; continue;
        }
        if (scmp(a, "--help") == 0 || scmp(a, "-h") == 0) {
            static const char H[] =
                "officemoe — router-soul dispatcher (default)\n"
                "  echo PROMPT | ./officemoe [--verbose] [--temp Q] [--max N]\n"
                "  ./officemoe [--verbose] PROMPT...\n"
                "Modes:\n"
                "  (default)      router-soul: 1 forward pass picks specialist\n"
                "  --bofN         best-of-N: each specialist scores prompt, max wins\n"
                "  --keyword      legacy keyword router\n"
                "  --score-only   print specialist=<f> table (forces --bofN)\n"
                "Specialists: chat | apps | theory | mood\n";
            wr(1, H, sizeof H - 1);
            return 0;
        }
        if (scmp(a, "--") == 0) break;
        if (scmp(a, "--temp") == 0 || scmp(a, "--max") == 0
         || scmp(a, "--seed") == 0) { i++; continue; }
        if (a[0] == '-') continue;
        is_prompt_arg[i] = 1;
    }

    int any_prompt_arg = 0;
    for (int i = 1; i < n_args; i++) if (is_prompt_arg[i]) any_prompt_arg = 1;

    if (any_prompt_arg) {
        for (int i = 1; i < n_args; i++) {
            if (!is_prompt_arg[i]) continue;
            int n = slen(argv[i]);
            if (plen + n + 2 >= (int)sizeof prompt_buf) break;
            if (plen > 0) prompt_buf[plen++] = ' ';
            for (int j = 0; j < n; j++) prompt_buf[plen++] = argv[i][j];
        }
    } else {
        long n;
        while (plen < (int)sizeof prompt_buf - 1
            && (n = rd(0, prompt_buf + plen,
                       sizeof prompt_buf - 1 - plen)) > 0) {
            plen += (int)n;
        }
        while (plen > 0 && (prompt_buf[plen - 1] == '\n'
                         || prompt_buf[plen - 1] == '\r')) plen--;
    }
    prompt_buf[plen] = 0;

    /* Pick the kind. */
    const char *kind = 0;
    float scores[4]; int got_score[4] = { 0, 0, 0, 0 };
    int actually_bofN = use_bofN || score_only;
    if (use_keyword) {
        kind = classify_keyword(prompt_buf, plen);
    } else if (actually_bofN) {
        float best = -1e30f;
        int best_i = 0;
        for (int i = 0; i < 4; i++) {
            float s;
            if (score_specialist(KINDS[i], prompt_buf, &s)) {
                scores[i] = s; got_score[i] = 1;
                if (s > best) { best = s; best_i = i; }
            } else {
                scores[i] = -1e30f;
            }
        }
        kind = KINDS[best_i];

        if (score_only) {
            char line[512]; int ln = 0;
            for (int i = 0; i < 4; i++) {
                int kl = slen(KINDS[i]);
                for (int j = 0; j < kl; j++) line[ln++] = KINDS[i][j];
                line[ln++] = '=';
                if (got_score[i]) ln += float_fmt(scores[i], line + ln);
                else { line[ln++] = 'N'; line[ln++] = 'A'; }
                line[ln++] = (i == 3) ? '\n' : ' ';
            }
            wr(1, line, ln);
            return 0;
        }
    } else {
        /* Default: router-soul. */
        kind = route_via_router(prompt_buf);
        if (kind == 0) {
            /* Router-soul didn't emit a kind name; fall back to keyword. */
            kind = classify_keyword(prompt_buf, plen);
        }
    }

    if (verbose) {
        wr(2, "[moe->", 6);
        wr(2, kind, slen(kind));
        if (actually_bofN) {
            wr(2, " ", 1);
            char line[256]; int ln = 0;
            for (int i = 0; i < 4; i++) {
                int kl = slen(KINDS[i]);
                for (int j = 0; j < kl; j++) line[ln++] = KINDS[i][j];
                line[ln++] = '=';
                if (got_score[i]) ln += float_fmt(scores[i], line + ln);
                else { line[ln++] = 'N'; line[ln++] = 'A'; }
                if (i < 3) line[ln++] = ' ';
            }
            wr(2, line, ln);
        }
        wr(2, "] ", 2);
        wr(2, prompt_buf, plen);
        wr(2, "\n", 1);
    }

    static char target[1024];
    if (resolve_specialist(kind, target, sizeof target) < 0) {
        static const char err[] = "officemoe: cannot resolve specialist path\n";
        wr(2, err, sizeof err - 1);
        return 1;
    }

    char *new_argv[32];
    int na = 0;
    new_argv[na++] = target;
    new_argv[na++] = prompt_buf;
    for (int i = 1; i < n_args && na < 30; i++) {
        const char *a = argv[i];
        if (is_prompt_arg[i]) continue;
        if (scmp(a, "--verbose") == 0 || scmp(a, "-v") == 0) continue;
        if (scmp(a, "--keyword") == 0) continue;
        if (scmp(a, "--bofN") == 0 || scmp(a, "--bestofn") == 0) continue;
        if (scmp(a, "--score-only") == 0) continue;
        if (scmp(a, "--") == 0) continue;
        new_argv[na++] = argv[i];
    }
    new_argv[na] = 0;

    char *envp[1] = { 0 };
    sys3(SYS_execve, (long)target, (long)new_argv, (long)envp);
    static const char err2[] = "officemoe: execve failed\n";
    wr(2, err2, sizeof err2 - 1);
    return 127;
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
