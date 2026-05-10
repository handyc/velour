/* officemoe.c — keyword-routed Mixture-of-Experts dispatcher.
 *
 * Reads a prompt from stdin (or argv), classifies it into one of
 * four domain specialists, and execve's the matching officesoulflt_*
 * binary with the prompt + any pass-through flags.  The specialist
 * inherits stdin/stdout/stderr so its output goes straight to the
 * caller — officemoe is just a router, not a wrapper.
 *
 * Specialists (each a separate trained soul):
 *   chat    — greetings, farewells, "who are you", "where am i"
 *   apps    — "what is X" for project apps (velour, office, rpg…)
 *   theory  — "what is X" for CS concepts (hex, ca, transformer…)
 *   mood    — "i'm Y" / "my Z" / "i found/fixed", advice, comfort
 *
 * Router heuristic (in order):
 *   1. Starts with "i'm" / "i am" / "my " / "i found" / "i fixed"
 *      / "tell me something" / "give me advice"   → mood
 *   2. Contains "what is" or "tell me about" + topical keyword:
 *        - velour / office / supercell / xpg / rpg / hxhnt / lsys
 *          / coder / tinydb / soul / esp / gary / mabel / hazel
 *          / terry  → apps
 *        - hex / ca / ga / transformer / attention / softmax
 *          / rmsnorm / bpe / int / q  → theory
 *      (default → apps if neither set matches)
 *   3. Anything else → chat.
 *
 * Specialist binaries must live in the same directory as officemoe;
 * we look them up via /proc/self/exe.
 *
 * Build:  cc -Os -nostdlib -fno-builtin -static -o officemoe officemoe.c
 */

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

#define SYS_read       0
#define SYS_write      1
#define SYS_readlink   89
#define SYS_execve     59
#define SYS_exit_group 231

#define rd(f, p, n)  sys3(SYS_read,     f, (long)(p), (long)(n))
#define wr(f, p, n)  sys3(SYS_write,    f, (long)(p), (long)(n))


/* ── string helpers ────────────────────────────────────── */
static int slen(const char *s) { int n = 0; while (s[n]) n++; return n; }
static int scmp(const char *a, const char *b) {
    while (*a && *a == *b) { a++; b++; }
    return (unsigned char)*a - (unsigned char)*b;
}
static char tolow(char c) { return (c >= 'A' && c <= 'Z') ? (char)(c + 32) : c; }

/* find lower-cased needle in lower-cased haystack; word boundary lite */
static int contains_word(const char *hay, int hlen, const char *needle) {
    int nlen = slen(needle);
    for (int i = 0; i + nlen <= hlen; i++) {
        int eq = 1;
        for (int j = 0; j < nlen; j++) {
            char c = tolow(hay[i + j]);
            if (c != needle[j]) { eq = 0; break; }
        }
        if (!eq) continue;
        /* Word-boundary check: char before/after must be non-alpha. */
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


/* ── classifier ────────────────────────────────────────── */
static const char *classify(const char *prompt, int plen) {
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

    /* "soul" alone is ambiguous (project + concept).  Prefer apps. */
    if (hit_apps)   return "apps";
    if (hit_theory) return "theory";
    if (has_what)   return "apps";

    return "chat";
}


/* ── path resolution ───────────────────────────────────── */
/* Read /proc/self/exe → basename → replace with binary name. */
static char exe_path[1024];

static int resolve_specialist(const char *kind, char *out, int cap) {
    long n = sys3(SYS_readlink, (long)"/proc/self/exe",
                  (long)exe_path, sizeof exe_path - 1);
    if (n <= 0) return -1;
    exe_path[n] = 0;
    /* strip trailing basename */
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


/* ── main ──────────────────────────────────────────────── */
static char prompt_buf[4096];

int main_c(int argc, char **argv) {
    /* Two passes: classify flags as either standalone, value-taking,
     * or positional.  Value-taking flags (--temp/--max/--seed) consume
     * the next argv as their value — we must NOT treat that value as
     * part of the prompt.  Standalone --verbose/-v are absorbed.
     * Anything else with a leading '-' is passed through to the
     * specialist; bare positional args concatenate into the prompt. */
    int plen = 0;
    int verbose = 0;
    int is_prompt_arg[64];     /* 1 if argv[i] is positional prompt token */
    for (int i = 0; i < 64; i++) is_prompt_arg[i] = 0;
    int n_args = argc < 64 ? argc : 64;

    for (int i = 1; i < n_args; i++) {
        const char *a = argv[i];
        if (scmp(a, "--verbose") == 0 || scmp(a, "-v") == 0) {
            verbose = 1;
            continue;
        }
        if (scmp(a, "--help") == 0 || scmp(a, "-h") == 0) {
            static const char H[] =
                "officemoe — keyword-routed soul dispatcher\n"
                "  echo PROMPT | ./officemoe [--verbose] [--temp Q] [--max N] [--seed N]\n"
                "  ./officemoe [--verbose] PROMPT...\n"
                "Specialists: chat | apps | theory | mood\n";
            wr(1, H, sizeof H - 1);
            return 0;
        }
        if (scmp(a, "--") == 0) {
            /* Everything after -- is passed verbatim to specialist. */
            break;
        }
        /* Value-taking flags: skip both the flag and its value. */
        if (scmp(a, "--temp") == 0 || scmp(a, "--max") == 0
         || scmp(a, "--seed") == 0) {
            i++;            /* consume value, not positional */
            continue;
        }
        if (a[0] == '-') continue;   /* unknown flag, pass through */
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

    const char *kind = classify(prompt_buf, plen);
    if (verbose) {
        wr(2, "[moe->", 6);
        wr(2, kind, slen(kind));
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

    /* Build argv for execve: target + prompt + pass-through flags
     * (everything that wasn't classified as positional or absorbed). */
    char *new_argv[32];
    int na = 0;
    new_argv[na++] = target;
    new_argv[na++] = prompt_buf;
    for (int i = 1; i < n_args && na < 30; i++) {
        const char *a = argv[i];
        if (is_prompt_arg[i]) continue;
        if (scmp(a, "--verbose") == 0 || scmp(a, "-v") == 0) continue;
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
